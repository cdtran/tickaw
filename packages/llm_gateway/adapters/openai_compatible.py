"""Adapter for local or hosted OpenAI-compatible chat-completions servers."""

import json

import httpx

from packages.llm_gateway.contracts import ModelRoute, ModelUsage, PlanRequest, PlanResponse
from packages.llm_gateway.prompts import system_prompt, user_prompt


class ModelProviderError(RuntimeError):
    """A provider returned an unavailable, malformed, or unsuccessful response."""


class OpenAICompatibleAdapter:
    def __init__(self, timeout_seconds: float = 60.0):
        self.timeout_seconds = timeout_seconds

    def generate_plan(self, route: ModelRoute, request: PlanRequest) -> PlanResponse:
        headers = {"Content-Type": "application/json"}
        if route.api_key:
            headers["Authorization"] = f"Bearer {route.api_key}"
        body = {
            "model": route.provider_model,
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(request)},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "query_plan_v2",
                    "strict": True,
                    "schema": request.response_schema,
                },
            },
        }
        try:
            response = httpx.post(
                f"{route.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            document = response.json()
            content = document["choices"][0]["message"]["content"]
            payload = content if isinstance(content, dict) else json.loads(content)
            usage = document.get("usage") or {}
            if not isinstance(payload, dict):
                raise TypeError("structured response was not an object")
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ModelProviderError("The selected model did not return a valid query plan.") from error
        return PlanResponse(
            payload=payload,
            stable_model_id=route.stable_id,
            provider=route.provider,
            provider_model=route.provider_model,
            prompt_version=request.prompt_version,
            usage=ModelUsage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            ),
        )
