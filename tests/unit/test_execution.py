"""Parquet-to-JSON integration coverage for the isolated execution boundary."""

import hashlib
import json
import subprocess
from pathlib import Path

import duckdb
import pytest
from pydantic import TypeAdapter

from packages.data_engine.execution import ExecutionLimits, catalog_from_profile, execute_plan
from packages.data_engine.execution_child import execution_connection
from packages.data_engine.result_types import ExecutionResult

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "query_plans"
FIXTURE = json.loads((EXAMPLES / "sales.fixture.json").read_text())
CASES = [json.loads(path.read_text()) for path in sorted(EXAMPLES.glob("*.case.json"))]
CATALOG = FIXTURE["columns"]


def plan():
    return {
        "plan_version": 1,
        "dimensions": ["region"],
        "metrics": [{"op": "sum", "column": "revenue", "alias": "total"}],
        "filters": [],
        "order_by": [],
        "limit": 100,
    }


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "sales.parquet"
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE fixture(region VARCHAR, product VARCHAR, revenue DOUBLE, "
            "sold_on DATE, refunded BOOLEAN)"
        )
        connection.executemany("INSERT INTO fixture VALUES (?, ?, ?, ?, ?)", FIXTURE["rows"])
        connection.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(path)])
    return path


def execute(source, payload=None, **kwargs):
    return execute_plan(
        payload or plan(),
        parquet_path=source,
        dataset_version_id="fixture-v1",
        columns=kwargs.pop("columns", CATALOG),
        **kwargs,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_known_answers_through_subprocess(source, case):
    result = execute(source, case["plan"])
    assert result.status == "succeeded", result
    assert result.table.rows == case["expected_rows"]
    assert [column.name for column in result.table.columns] == case["expected_columns"]
    assert result.table.returned_rows == len(case["expected_rows"])
    assert result.table.truncated == (case["id"] == "top_region")
    assert result.metadata.dataset_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.metadata.dataset_version_id == "fixture-v1"
    assert result.metadata.compiler_version and result.metadata.executor_version
    assert result.metadata.engine_version == duckdb.__version__
    assert result.metadata.plan_sha256 and result.metadata.duration_ms >= 0
    assert result.metadata.executed_sql
    assert TypeAdapter(ExecutionResult).validate_json(result.model_dump_json()) == result
    assert {check.name: check.status for check in result.table.checks}[
        "question_meaning"
    ] == "not_checked"


def test_exact_limit_is_not_reported_as_truncated(source):
    result = execute(source, plan() | {"limit": 4})
    assert result.status == "succeeded"
    assert result.table.returned_rows == 4
    assert not result.table.truncated
    assert not result.table.warnings


def test_lookahead_row_is_removed(source):
    result = execute(source, plan() | {"limit": 2})
    assert result.status == "succeeded"
    assert result.table.rows == [["East", 20], ["North", 40]]
    assert result.table.truncated and result.table.warnings == ["RESULT_TRUNCATED"]
    assert "LIMIT 3" in result.metadata.executed_sql


def test_invalid_plan_does_not_start_process(source, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid plan must not reach subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)
    result = execute(source, plan() | {"raw_sql": "DROP TABLE dataset"})
    assert result.status == "failed" and result.error.code == "INVALID_PLAN"
    assert result.metadata.executed_sql is None
    assert "DROP TABLE" not in result.model_dump_json()


@pytest.mark.parametrize(
    "limits",
    [
        ExecutionLimits(max_source_bytes=1),
        ExecutionLimits(max_source_rows=1),
        ExecutionLimits(max_source_columns=1),
        ExecutionLimits(max_source_cells=1),
    ],
)
def test_source_bounds(source, limits):
    result = execute(source, limits=limits)
    assert result.status == "failed" and result.error.code == "SOURCE_LIMIT"


def test_schema_mismatch(source):
    result = execute(source, columns=CATALOG | {"revenue": "integer"})
    assert result.status == "failed" and result.error.code == "SCHEMA_MISMATCH"


def test_missing_and_corrupt_sources(tmp_path):
    path = tmp_path / "secret-source.parquet"
    result = execute(path)
    assert result.error.code == "SOURCE_UNAVAILABLE"
    path.write_text("not parquet")
    result = execute(path)
    assert result.error.code == "INVALID_SOURCE"
    assert str(path) not in result.model_dump_json()


def test_real_child_timeout(source):
    result = execute(source, limits=ExecutionLimits(timeout_seconds=0.001))
    assert result.status == "failed" and result.error.code == "EXECUTION_TIMEOUT"


def test_crashed_worker(source, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], -9))
    result = execute(source)
    assert result.status == "failed" and result.error.code == "WORKER_FAILED"


def test_child_does_not_inherit_credentials_or_modify_source(source, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-worker")
    before = source.read_bytes()
    actual_run = subprocess.run

    def checked_run(*args, **kwargs):
        assert "AWS_SECRET_ACCESS_KEY" not in kwargs["env"]
        assert "HOME" not in kwargs["env"]
        assert kwargs["timeout"] == 30.0
        return actual_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", checked_run)
    assert execute(source).status == "succeeded"
    assert source.read_bytes() == before


def write_query_fixture(tmp_path, query):
    path = tmp_path / "typed.parquet"
    with duckdb.connect() as connection:
        connection.execute(f"COPY ({query}) TO ? (FORMAT PARQUET)", [str(path)])
    return path


def test_precision_and_date_encoding(tmp_path):
    source = write_query_fixture(
        tmp_path,
        "SELECT 9007199254740993::BIGINT AS n, 0.10::DECIMAL(10,2) AS money, "
        "DATE '2025-01-01' AS day",
    )
    payload = plan() | {
        "dimensions": ["day"],
        "metrics": [
            {"op": "sum", "column": "n", "alias": "total_n"},
            {"op": "sum", "column": "money", "alias": "total_money"},
        ],
    }
    result = execute(source, payload, columns={"n": "integer", "money": "number", "day": "date"})
    assert result.status == "succeeded", result
    assert result.table.rows == [["2025-01-01", "9007199254740993", "0.10"]]
    assert [column.encoding for column in result.table.columns] == [
        "iso_date",
        "integer_string",
        "decimal_string",
    ]


def test_nonfinite_results_fail(tmp_path):
    source = write_query_fixture(tmp_path, "SELECT 1e308 AS revenue FROM range(2)")
    result = execute(source, plan() | {"dimensions": []}, columns={"revenue": "number"})
    assert result.status == "failed" and result.error.code == "NON_FINITE_RESULT"


def test_result_byte_limit(tmp_path):
    source = write_query_fixture(
        tmp_path, "SELECT repeat('x', 3000) AS region, 1.0::DOUBLE AS revenue"
    )
    result = execute(
        source,
        columns={"region": "text", "revenue": "number"},
        limits=ExecutionLimits(max_result_bytes=1024),
    )
    assert result.status == "failed" and result.error.code == "RESULT_LIMIT"


def test_string_literal_cannot_inject_query(source):
    payload = plan() | {
        "filters": [
            {"column": "region", "op": "eq", "value": "West'; COPY dataset TO '/tmp/leak'; --"}
        ]
    }
    result = execute(source, payload)
    assert result.status == "succeeded" and result.table.rows == []


def test_duckdb_restrictions_after_loading(source, tmp_path):
    with execution_connection(ExecutionLimits()) as connection:
        connection.execute(
            "CREATE TEMP TABLE dataset AS SELECT * FROM read_parquet(?)", [str(source)]
        )
        connection.execute("SET enable_external_access = false")
        connection.execute("SET lock_configuration = true")
        assert connection.execute("SELECT COUNT(*) FROM dataset").fetchone() == (8,)
        with pytest.raises(duckdb.PermissionException):
            connection.execute("SELECT * FROM read_parquet(?)", [str(source)])
        with pytest.raises(duckdb.PermissionException):
            connection.execute("COPY dataset TO ?", [str(tmp_path / "leak.csv")])
        with pytest.raises(duckdb.InvalidInputException):
            connection.execute("SET enable_external_access = true")


def test_profile_catalog_mapping():
    schema = {
        "version": 1,
        "columns": [
            {"name": name, "inferred_type": kind, "pandas_dtype": "unused"}
            for name, kind in [
                ("name", "string"),
                ("empty", "unknown"),
                ("n", "integer"),
                ("amount", "number"),
                ("yes", "boolean"),
            ]
        ],
    }
    assert catalog_from_profile(schema) == {
        "name": "text",
        "empty": "text",
        "n": "integer",
        "amount": "number",
        "yes": "boolean",
    }
    schema["columns"].append({"name": "bad", "inferred_type": "unsupported"})
    with pytest.raises(ValueError):
        catalog_from_profile(schema)


def test_result_schema_artifact():
    expected = json.loads((EXAMPLES / "execution-result.schema.json").read_text())
    assert expected == TypeAdapter(ExecutionResult).json_schema()


def test_unsupported_parquet_type(tmp_path):
    source = write_query_fixture(tmp_path, "SELECT [1, 2] AS revenue")
    result = execute(source, plan() | {"dimensions": []}, columns={"revenue": "number"})
    assert result.status == "failed" and result.error.code == "UNSUPPORTED_TYPE"
