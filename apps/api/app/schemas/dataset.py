"""Public metadata contracts; storage credentials and internal keys stay server-side."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_number: int
    status: str
    original_filename: str
    size_bytes: int | None
    created_at: datetime
    error_message: str | None
    error_code: str | None


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime
    versions: list[VersionResponse]


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class VersionDetail(VersionResponse):
    row_count: int | None
    dataset_schema: dict | None = Field(alias="schema_json")
    profile_json: dict | None
    preview_json: list[dict] | None
    job: JobResponse | None = None
