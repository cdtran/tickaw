"""Stable model-ID registry and availability policy."""

from collections.abc import Iterable

from packages.llm_gateway.contracts import ModelInfo, ModelRoute


class UnknownModelError(ValueError):
    pass


class ModelRegistry:
    def __init__(self, routes: Iterable[ModelRoute]):
        self._routes = {route.stable_id: route for route in routes}
        if not self._routes:
            raise ValueError("At least one analysis model must be configured")

    def resolve(self, stable_id: str) -> ModelRoute:
        try:
            return self._routes[stable_id]
        except KeyError as error:
            raise UnknownModelError(f"Unknown or disabled analysis model: {stable_id}") from error

    def available(self) -> list[ModelInfo]:
        return [route.public_info() for route in self._routes.values()]
