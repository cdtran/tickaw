"""Pydantic contracts for durable analysis runs and reconstructable results."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from packages.charting.specs import ChartSpec
from packages.data_engine.result_types import ExecutionSuccess


class StoredAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    artifact_version: Literal[1] = 1
    execution: ExecutionSuccess
    chart: ChartSpec | None


class AnalysisRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    plan_sha256: str
    result_sha256: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class AnalysisRunResponse(AnalysisRunSummary):
    notebook_cell_id: UUID
    dataset_version_id: UUID
    stable_model_id: str | None
    prompt_version: str | None
    result_size_bytes: int | None
    result_version: int | None
    started_at: datetime | None
