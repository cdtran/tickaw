"""Public metadata contracts; storage credentials and internal keys stay server-side."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_number: int
    status: str
    original_filename: str
    size_bytes: int | None
    created_at: datetime
    error_message: str | None


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime
    versions: list[VersionResponse]
