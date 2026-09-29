"""Build the configured model registry and provider-neutral LLM gateway."""

from functools import lru_cache

from app.core.config import get_settings
from packages.llm_gateway.adapters import OllamaAdapter, OpenAICompatibleAdapter
from packages.llm_gateway.contracts import ModelRoute
from packages.llm_gateway.gateway import LLMGateway
from packages.llm_gateway.registry import ModelRegistry


@lru_cache
def get_model_registry() -> ModelRegistry:
    settings = get_settings()
    known = {
        "qwen-local": ModelRoute(
            stable_id="qwen-local",
            label="Qwen Local",
            provider="ollama",
            provider_model=settings.qwen_model,
            base_url=settings.qwen_base_url.removesuffix("/v1"),
            description="Open-source Qwen running on your local model server.",
        )
    }
    enabled_ids = [item.strip() for item in settings.llm_enabled_models.split(",") if item.strip()]
    unknown = [item for item in enabled_ids if item not in known]
    if unknown:
        raise ValueError(f"Unknown models in LLM_ENABLED_MODELS: {', '.join(unknown)}")
    return ModelRegistry(known[item] for item in enabled_ids)


@lru_cache
def get_llm_gateway() -> LLMGateway:
    return LLMGateway(
        get_model_registry(),
        {
            "ollama": OllamaAdapter(timeout_seconds=get_settings().qwen_timeout_seconds),
            "openai-compatible": OpenAICompatibleAdapter(
                timeout_seconds=get_settings().qwen_timeout_seconds
            )
        },
    )
