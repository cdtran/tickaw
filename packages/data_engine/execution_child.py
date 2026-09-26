"""Private trusted subprocess entry point; never accepts SQL from a caller."""

import json
import math
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlglot import ErrorLevel, exp

from packages.data_engine.execution import ExecutionLimits, ExecutionProblem
from packages.data_engine.query_compiler import build_ast
from packages.data_engine.query_plan import RowCount, validate_plan
from packages.data_engine.result_types import ResultCheck, ResultColumn, TableResult

INTEGER_TYPES = {
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "UHUGEINT",
}


def logical_type(database_type: str) -> str:
    if database_type in INTEGER_TYPES:
        return "integer"
    if database_type in {"FLOAT", "DOUBLE"} or database_type.startswith("DECIMAL("):
        return "number"
    if database_type == "VARCHAR":
        return "text"
    if database_type == "BOOLEAN":
        return "boolean"
    if database_type == "DATE":
        return "date"
    raise ExecutionProblem("UNSUPPORTED_TYPE", "The dataset contains an unsupported database type.")


def apply_process_limits(policy):
    # macOS does not enforce RLIMIT_AS reliably; Linux workers get an address-space cap.
    import resource

    cpu = max(1, math.ceil(policy.timeout_seconds))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (policy.max_result_bytes, policy.max_result_bytes))
    if sys.platform.startswith("linux"):
        cap = 2 * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))


def execution_connection(policy):
    import duckdb

    return duckdb.connect(
        ":memory:",
        config={
            "threads": 1,
            "memory_limit": f"{policy.memory_mb}MB",
            "max_temp_directory_size": "0B",
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
        },
    )


def encode_table(description, raw_rows, plan, catalog, truncated):
    names = [item[0] for item in description]
    expected_names = plan.dimensions + [metric.alias for metric in plan.metrics]
    if names != expected_names or any(len(row) != len(names) for row in raw_rows):
        raise ExecutionProblem(
            "RESULT_CHECK_FAILED", "Result columns do not match the validated plan."
        )
    if len(raw_rows) > plan.limit:
        raise ExecutionProblem("RESULT_CHECK_FAILED", "Result exceeded the requested row limit.")
    expected_types = [catalog[name] for name in plan.dimensions]
    for metric in plan.metrics:
        if isinstance(metric, RowCount) or metric.op == "count_non_null":
            expected_types.append("integer")
        elif metric.op == "avg":
            expected_types.append("number")
        else:
            expected_types.append(catalog[metric.column])
    result_columns, encoded_columns = [], []
    for index, item in enumerate(description):
        physical = str(item[1])
        kind = logical_type(physical)
        if kind != expected_types[index]:
            raise ExecutionProblem(
                "RESULT_CHECK_FAILED", "Result types do not match the validated plan."
            )
        values = [row[index] for row in raw_rows]
        if any(isinstance(value, float) and not math.isfinite(value) for value in values):
            raise ExecutionProblem("NON_FINITE_RESULT", "The result contains a non-finite number.")
        encoding = "json"
        if physical.startswith("DECIMAL("):
            encoding = "decimal_string"
        elif kind == "integer" and any(
            value is not None and abs(value) > 2**53 - 1 for value in values
        ):
            encoding = "integer_string"
        elif kind == "date":
            encoding = "iso_date"
        encoded = []
        for value in values:
            if value is None:
                encoded.append(None)
            elif encoding in {"decimal_string", "integer_string"}:
                encoded.append(str(value))
            elif isinstance(value, date):
                encoded.append(value.isoformat())
            elif isinstance(value, Decimal):
                raise ExecutionProblem("RESULT_CHECK_FAILED", "Unexpected numeric encoding.")
            else:
                encoded.append(value)
        result_columns.append(
            ResultColumn(
                name=names[index],
                logical_type=kind,
                database_type=physical,
                encoding=encoding,
            )
        )
        encoded_columns.append(encoded)
    if plan.dimensions:
        keys = [tuple(row[: len(plan.dimensions)]) for row in raw_rows]
        if len(set(keys)) != len(keys):
            raise ExecutionProblem("RESULT_CHECK_FAILED", "Grouped result contains duplicate keys.")
    checks = [
        ResultCheck(name=name, status="passed")
        for name in (
            "output_columns",
            "output_types",
            "row_limit",
            "finite_numbers",
        )
    ]
    checks.append(
        ResultCheck(
            name="unique_group_keys",
            status="passed" if plan.dimensions else "not_checked",
        )
    )
    checks.append(ResultCheck(name="question_meaning", status="not_checked"))
    return TableResult(
        columns=result_columns,
        rows=[list(row) for row in zip(*encoded_columns)] if raw_rows else [],
        returned_rows=len(raw_rows),
        requested_limit=plan.limit,
        truncated=truncated,
        warnings=["RESULT_TRUNCATED"] if truncated else [],
        checks=checks,
    )


def run(request, source):
    import duckdb

    policy = ExecutionLimits.model_validate(request["limits"])
    catalog = request["columns"]
    plan = validate_plan(request["plan"], catalog)
    with execution_connection(policy) as connection:
        try:
            relation = connection.read_parquet(str(source))
            actual = dict(zip(relation.columns, (logical_type(str(t)) for t in relation.types)))
            if actual != catalog:
                raise ExecutionProblem(
                    "SCHEMA_MISMATCH", "Parquet schema differs from the pinned catalog."
                )
            if len(actual) > policy.max_source_columns:
                raise ExecutionProblem("SOURCE_LIMIT", "Dataset exceeds the column limit.")
            # Materialize only a bounded input, then remove all file access before the query.
            row_bound = min(policy.max_source_rows, policy.max_source_cells // len(actual))
            connection.execute(
                "CREATE TEMP TABLE dataset AS SELECT * FROM read_parquet(?) LIMIT ?",
                [str(source), row_bound + 1],
            )
            count = connection.execute("SELECT count(*) FROM dataset").fetchone()[0]
            if count > row_bound:
                raise ExecutionProblem("SOURCE_LIMIT", "Dataset exceeds the row or cell limit.")
        except (duckdb.InvalidInputException, duckdb.IOException):
            raise ExecutionProblem(
                "INVALID_SOURCE", "The normalized dataset is not readable Parquet."
            )
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
        tree = build_ast(plan.model_dump(), catalog).limit(exp.Literal.number(plan.limit + 1))
        sql = tree.sql(dialect="duckdb", unsupported_level=ErrorLevel.RAISE)
        result = connection.execute(sql)
        description = result.description
        rows = result.fetchmany(plan.limit + 1)
        return encode_table(description, rows[: plan.limit], plan, catalog, len(rows) > plan.limit)


def main():
    request = json.loads(Path("request.json").read_text())
    policy = ExecutionLimits.model_validate(request["limits"])
    apply_process_limits(policy)
    import duckdb

    try:
        result = run(request, Path("dataset.parquet").resolve()).model_dump()
        serialized = json.dumps(result, allow_nan=False).encode()
        if len(serialized) > policy.max_result_bytes:
            raise ExecutionProblem(
                "RESULT_LIMIT", "The query result exceeds its serialized size limit."
            )
    except ExecutionProblem as error:
        result = {"error": {"code": error.code, "message": error.message}}
    except (duckdb.OutOfMemoryException, MemoryError):
        result = {"error": {"code": "MEMORY_LIMIT", "message": "Query exceeded its memory budget."}}
    except (duckdb.Error, ValueError, TypeError, OSError, OverflowError):
        # Engine diagnostics can contain local paths or data; do not expose them to clients.
        result = {
            "error": {"code": "EXECUTION_FAILED", "message": "The query could not be executed."}
        }
    Path("result.json").write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
