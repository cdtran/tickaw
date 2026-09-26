"""Execute only application-compiled plans in a bounded child process.

The caller resolves a READY dataset version to a local normalized Parquet file.
Never populate the path, catalog, or dataset version from model output.
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlglot import ErrorLevel, exp

from packages.data_engine.query_compiler import COMPILER_VERSION, build_ast
from packages.data_engine.query_plan import ColumnType, PlanError, validate_plan
from packages.data_engine.result_types import (
    ExecutionError,
    ExecutionFailure,
    ExecutionMetadata,
    ExecutionResult,
    ExecutionSuccess,
    TableResult,
)

EXECUTOR_VERSION = "1"


class ExecutionLimits(BaseModel):
    """Server policy; never part of the LLM plan."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    memory_mb: int = Field(default=256, ge=128, le=1024)
    max_source_bytes: int = Field(default=64 * 1024**2, ge=1, le=64 * 1024**2)
    max_source_rows: int = Field(default=100_000, ge=1, le=100_000)
    max_source_columns: int = Field(default=100, ge=1, le=100)
    max_source_cells: int = Field(default=500_000, ge=1, le=500_000)
    max_result_bytes: int = Field(default=2 * 1024**2, ge=1024, le=2 * 1024**2)


class ExecutionProblem(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def catalog_from_profile(schema: dict) -> dict[str, ColumnType]:
    """Map the existing profiler's schema v1 without guessing date conversions."""
    mapping = {
        "string": "text",
        "unknown": "text",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
    }
    if (
        not isinstance(schema, dict)
        or type(schema.get("version")) is not int
        or schema["version"] != 1
    ):
        raise ValueError("Unsupported profile schema version")
    columns = schema.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError("Profile must contain columns")
    catalog = {}
    for item in columns:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"]
            or item.get("inferred_type") not in mapping
        ):
            raise ValueError("Unsupported profile column")
        if item["name"] in catalog:
            raise ValueError("Duplicate profile column")
        catalog[item["name"]] = mapping[item["inferred_type"]]
    return catalog


def execute_plan(
    payload: dict,
    *,
    parquet_path: Path,
    dataset_version_id: str,
    columns: dict[str, ColumnType],
    limits: ExecutionLimits | None = None,
) -> ExecutionResult:
    """Return success with a table, or a structured failure with safe diagnostics.

    The data source is snapshotted and hashed before launching the child. The
    metadata SQL includes one extra row to detect truncation; that row is not returned.
    This function does not perform API authorization, S3 downloads, or persistence.
    """
    policy = limits or ExecutionLimits()
    start = time.monotonic()
    metadata = ExecutionMetadata(
        execution_id=str(uuid4()),
        dataset_version_id=dataset_version_id,
        compiler_version=COMPILER_VERSION,
        executor_version=EXECUTOR_VERSION,
        sqlglot_version=version("sqlglot"),
        engine_version=version("duckdb"),
        started_at=datetime.now(UTC).isoformat(),
        duration_ms=0,
    )

    def failed(code, message):
        metadata.duration_ms = int((time.monotonic() - start) * 1000)
        return ExecutionFailure(error=ExecutionError(code=code, message=message), metadata=metadata)

    try:
        plan = validate_plan(payload, columns)
        normalized = plan.model_dump()
        metadata.plan_version = plan.plan_version
        metadata.plan_sha256 = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        # AST remains application-owned. One lookahead row detects a real truncation.
        tree = build_ast(normalized, columns).limit(exp.Literal.number(plan.limit + 1))
        metadata.executed_sql = tree.sql(dialect="duckdb", unsupported_level=ErrorLevel.RAISE)
    except (ValidationError, PlanError, ValueError):
        return failed("INVALID_PLAN", "The plan is invalid for this dataset's supported schema.")

    try:
        source = Path(parquet_path)
        if not source.is_file():
            return failed("SOURCE_UNAVAILABLE", "The normalized dataset file is unavailable.")
        with tempfile.TemporaryDirectory(prefix="tickaw-query-") as directory:
            root = Path(directory)
            snapshot = root / "dataset.parquet"
            total = 0
            digest = hashlib.sha256()
            with source.open("rb") as original, snapshot.open("wb") as target:
                while chunk := original.read(64 * 1024):
                    total += len(chunk)
                    if total > policy.max_source_bytes:
                        return failed(
                            "SOURCE_LIMIT", "The normalized dataset exceeds its size limit."
                        )
                    digest.update(chunk)
                    target.write(chunk)
            metadata.dataset_sha256 = digest.hexdigest()
            snapshot.chmod(0o400)
            request = {
                "plan": normalized,
                "columns": columns,
                "limits": policy.model_dump(),
            }
            (root / "request.json").write_text(json.dumps(request, allow_nan=False))
            # No inherited API keys, database URLs, home directory, or cloud credentials.
            environment = {
                "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
                "PYTHONDONTWRITEBYTECODE": "1",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
            }
            try:
                process = subprocess.run(
                    [sys.executable, "-m", "packages.data_engine.execution_child"],
                    cwd=root,
                    env=environment,
                    timeout=policy.timeout_seconds,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired:
                return failed("EXECUTION_TIMEOUT", "Query execution exceeded its time limit.")
            output = root / "result.json"
            if process.returncode != 0 or not output.is_file():
                return failed("WORKER_FAILED", "Execution failed or exceeded its process limits.")
            if output.stat().st_size > policy.max_result_bytes:
                return failed("RESULT_LIMIT", "The query result exceeds its serialized size limit.")
            try:
                result = json.loads(output.read_text())
                if "error" in result:
                    error = ExecutionError.model_validate(result["error"])
                    return failed(error.code, error.message)
                table = TableResult.model_validate(result)
            except (ValueError, TypeError):
                return failed("INVALID_RESULT", "The executor returned an invalid result.")
    except OSError:
        return failed("SOURCE_UNAVAILABLE", "The execution files could not be read or written.")
    metadata.duration_ms = int((time.monotonic() - start) * 1000)
    return ExecutionSuccess(table=table, metadata=metadata)
