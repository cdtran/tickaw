"""Opt-in Responses API adapter with process-local, conservative spend reservations."""

import json
from decimal import Decimal
from threading import Lock

import httpx

from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import ModelRoute, ModelUsage, PlanRequest, PlanResponse
from packages.llm_gateway.prompts import system_prompt, user_prompt


class PaidRunBlocked(ModelProviderError):
    """Local policy blocked a generation before it reached the provider."""


def response_schema(schema):
    """Convert Pydantic discriminated unions to OpenAI's supported anyOf form."""
    if isinstance(schema, list):
        return [response_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        ("anyOf" if key == "oneOf" else "enum" if key == "const" else key): (
            [value] if key == "const" else response_schema(value)
        )
        for key, value in schema.items()
        if key != "discriminator"
    }


class OpenAIAdapter:
    def __init__(
        self,
        *,
        allow_paid=False,
        max_cost_usd=None,
        max_requests=None,
        input_rate=None,
        output_rate=None,
        max_output_tokens=1024,
        timeout_seconds=120.0,
    ):
        self.allow_paid = allow_paid
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.requests = 0
        self.reserved_cost = Decimal(0)
        self._lock = Lock()
        self.max_requests = max_requests
        self.max_cost = self._decimal(max_cost_usd)
        self.input_rate = self._decimal(input_rate)
        self.output_rate = self._decimal(output_rate)

    @staticmethod
    def _decimal(value):
        if value is None:
            return None
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0:
            raise ValueError("Paid-run budget and token rates must be finite and positive")
        return result

    def _check_policy(self, route):
        if not self.allow_paid:
            raise PaidRunBlocked("OpenAI generation requires explicit paid-run opt-in")
        if not route.api_key or not route.provider_model.strip():
            raise PaidRunBlocked("OpenAI requires a key and an explicit provider model")
        if self.max_cost is None or self.input_rate is None or self.output_rate is None:
            raise PaidRunBlocked("OpenAI requires a budget and both token prices")
        if type(self.max_requests) is not int or self.max_requests <= 0:
            raise PaidRunBlocked("OpenAI requires a positive request limit")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 16:
            raise PaidRunBlocked("OpenAI requires an output limit of at least 16 tokens")
        if self.requests >= self.max_requests:
            raise PaidRunBlocked("OpenAI request limit exhausted")

    def generate_plan(self, route: ModelRoute, request: PlanRequest) -> PlanResponse:
        # Fixed official endpoint: credentials cannot be sent to a configured proxy.
        with self._lock:
            self._check_policy(route)
            body = {
                "model": route.provider_model,
                "instructions": system_prompt(),
                "input": user_prompt(request),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "query_plan_v2",
                        "strict": True,
                        "schema": response_schema(request.response_schema),
                    }
                },
            }
            headers = {"Authorization": f"Bearer {route.api_key}"}
            try:
                counted = httpx.post(
                    "https://api.openai.com/v1/responses/input_tokens",
                    headers=headers,
                    json=body,
                    timeout=self.timeout_seconds,
                )
                counted.raise_for_status()
                count = counted.json()["input_tokens"]
                if type(count) is not int or count < 0:
                    raise ValueError("Invalid input token count")
                reservation = (
                    count * self.input_rate + self.max_output_tokens * self.output_rate
                ) / Decimal(1_000_000)
                if self.reserved_cost + reservation > self.max_cost:
                    raise PaidRunBlocked("OpenAI spend reservation exceeds budget")
                self.reserved_cost += reservation
                self.requests += 1
                # Never release a reservation: failures may still have been billed.
                response = httpx.post(
                    "https://api.openai.com/v1/responses",
                    headers=headers,
                    json=body | {"max_output_tokens": self.max_output_tokens, "store": False},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                document = response.json()
                if document["status"] != "completed":
                    raise ValueError("Incomplete response")
                content = [
                    part
                    for item in document["output"]
                    if item["type"] == "message"
                    for part in item["content"]
                ]
                if any(part["type"] == "refusal" for part in content):
                    raise ValueError("Provider refusal")
                payload = json.loads(
                    "".join(part["text"] for part in content if part["type"] == "output_text")
                )
                if not isinstance(payload, dict):
                    raise TypeError("Plan must be an object")
                usage = ModelUsage(
                    input_tokens=document["usage"]["input_tokens"],
                    output_tokens=document["usage"]["output_tokens"],
                )
            except PaidRunBlocked:
                raise
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
                raise ModelProviderError("OpenAI did not return a valid query plan") from error
        return PlanResponse(
            payload=payload,
            stable_model_id=route.stable_id,
            provider=route.provider,
            provider_model=route.provider_model,
            prompt_version=request.prompt_version,
            usage=usage,
        )
