"""Versioned, JSON-safe execution results. No generated narrative or HTML."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ResultColumn(ResultModel):
    name: str
    logical_type: Literal["text", "integer", "number", "boolean", "date"]
    database_type: str
    encoding: Literal["json", "decimal_string", "integer_string", "iso_date"]


class ResultCheck(ResultModel):
    name: str
    status: Literal["passed", "not_checked"]


class TableResult(ResultModel):
    columns: list[ResultColumn]
    rows: list[list[str | int | float | bool | None]]
    returned_rows: int
    requested_limit: int
    truncated: bool
    warnings: list[str]
    checks: list[ResultCheck]


class ExecutionMetadata(ResultModel):
    execution_id: str
    dataset_version_id: str
    dataset_sha256: str | None = None
    plan_sha256: str | None = None
    plan_version: int | None = None
    compiler_version: str
    executor_version: str
    sqlglot_version: str
    engine: Literal["duckdb"] = "duckdb"
    engine_version: str
    started_at: str
    duration_ms: int
    executed_sql: str | None = None


class ExecutionError(ResultModel):
    code: str
    message: str


class ExecutionSuccess(ResultModel):
    result_version: Literal[1] = 1
    status: Literal["succeeded"] = "succeeded"
    table: TableResult
    metadata: ExecutionMetadata


class ExecutionFailure(ResultModel):
    result_version: Literal[1] = 1
    status: Literal["failed"] = "failed"
    error: ExecutionError
    metadata: ExecutionMetadata


ExecutionResult = Annotated[ExecutionSuccess | ExecutionFailure, Field(discriminator="status")]
