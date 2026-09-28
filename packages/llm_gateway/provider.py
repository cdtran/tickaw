"""Provider adapter protocol; provider SDK types never cross this boundary."""

from typing import Protocol

from packages.llm_gateway.contracts import ModelRoute, PlanRequest, PlanResponse


class ProviderAdapter(Protocol):
    def generate_plan(self, route: ModelRoute, request: PlanRequest) -> PlanResponse: ...
