"""Pydantic contracts for selectable model metadata."""

from pydantic import BaseModel, ConfigDict


class SelectableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    provider: str
    description: str
    requires_api_key: bool
