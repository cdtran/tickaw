"""Provider-neutral contracts consumed by the API and analysis workers."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelInfo(StrictContract):
    id: str
    label: str
    provider: str
    description: str
    requires_api_key: bool = False


class ModelRoute(StrictContract):
    stable_id: str
    label: str
    provider: Literal["openai-compatible"]
    provider_model: str
    base_url: str
    description: str
    api_key: str | None = Field(default=None, repr=False)

    def public_info(self) -> ModelInfo:
        return ModelInfo(
            id=self.stable_id,
            label=self.label,
            provider=self.provider,
            description=self.description,
            requires_api_key=self.api_key is not None,
        )


class PlanRequest(StrictContract):
    question: str
    dataset_schema: dict[str, Any]
    dataset_profile: dict[str, Any]
    response_schema: dict[str, Any]
    prompt_version: str
    validation_feedback: str | None = None


class ModelUsage(StrictContract):
    input_tokens: int | None = None
    output_tokens: int | None = None


class PlanResponse(StrictContract):
    payload: dict[str, Any]
    stable_model_id: str
    provider: str
    provider_model: str
    prompt_version: str
    usage: ModelUsage
