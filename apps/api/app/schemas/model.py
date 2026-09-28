"""Pydantic contracts for selectable model metadata."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class SelectableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    provider: str
    description: str
    requires_api_key: bool


class PlanDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: dict[str, Any]
    stable_model_id: str
    provider: str
    provider_model: str
    prompt_version: str
