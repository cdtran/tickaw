"""Native Ollama adapter with explicit control of thinking-model behavior."""

import json

import httpx

from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import ModelRoute, ModelUsage, PlanRequest, PlanResponse
from packages.llm_gateway.prompts import system_prompt, user_prompt


class OllamaAdapter:
    def __init__(self, timeout_seconds: float = 60.0):
        self.timeout_seconds = timeout_seconds

    def generate_plan(self, route: ModelRoute, request: PlanRequest) -> PlanResponse:
        body = {
            "model": route.provider_model,
            "messages": [
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(request)},
            ],
            "stream": False,
            "think": False,
            "format": request.response_schema,
            "options": {"temperature": 0, "num_predict": 1024},
        }
        try:
            response = httpx.post(
                f"{route.base_url.rstrip('/')}/api/chat",
                headers={"Content-Type": "application/json"},
                json=body,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            document = response.json()
            content = document["message"]["content"]
            payload = content if isinstance(content, dict) else json.loads(content)
            if not isinstance(payload, dict):
                raise TypeError("structured response was not an object")
        except (httpx.HTTPError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ModelProviderError("The selected model did not return a valid query plan.") from error
        return PlanResponse(
            payload=payload,
            stable_model_id=route.stable_id,
            provider=route.provider,
            provider_model=route.provider_model,
            prompt_version=request.prompt_version,
            usage=ModelUsage(
                input_tokens=document.get("prompt_eval_count"),
                output_tokens=document.get("eval_count"),
            ),
        )
