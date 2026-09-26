"""Only user input is writable; IDs, status and timestamps are server-owned."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class NotebookCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class QuestionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    dataset_version_id: UUID


class NotebookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class CellResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    notebook_id: UUID
    dataset_version_id: UUID
    question: str
    status: str
    created_at: datetime
    updated_at: datetime


class NotebookDetail(NotebookResponse):
    cells: list[CellResponse]
