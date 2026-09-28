"""Application-facing LLM gateway boundary."""

from packages.llm_gateway.contracts import PlanRequest, PlanResponse
from packages.llm_gateway.provider import ProviderAdapter
from packages.llm_gateway.registry import ModelRegistry


class LLMGateway:
    def __init__(self, registry: ModelRegistry, adapters: dict[str, ProviderAdapter]):
        self.registry = registry
        self.adapters = adapters

    def generate_plan(self, stable_model_id: str, request: PlanRequest) -> PlanResponse:
        route = self.registry.resolve(stable_model_id)
        try:
            adapter = self.adapters[route.provider]
        except KeyError as error:
            raise RuntimeError(f"No adapter configured for provider: {route.provider}") from error
        return adapter.generate_plan(route, request)
