import json

from packages.llm_gateway.adapters.ollama import OllamaAdapter
from packages.llm_gateway.adapters.openai_compatible import OpenAICompatibleAdapter
from packages.llm_gateway.contracts import ModelRoute, PlanRequest


class FakeHTTPResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": json.dumps({"plan_version": 2})}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }


def test_openai_compatible_adapter_sends_schema_and_normalizes_response(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeHTTPResponse()

    monkeypatch.setattr("packages.llm_gateway.adapters.openai_compatible.httpx.post", fake_post)
    route = ModelRoute(
        stable_id="qwen-local",
        label="Qwen Local",
        provider="openai-compatible",
        provider_model="qwen3:8b",
        base_url="http://localhost:11434/v1/",
        description="Local model",
    )
    request = PlanRequest(
        question="How many rows?",
        dataset_schema={"columns": [{"name": "region", "inferred_type": "string"}]},
        dataset_profile={"row_count": 3},
        response_schema={"type": "object"},
        prompt_version="test-v1",
    )

    result = OpenAICompatibleAdapter().generate_plan(route, request)

    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["json"]["model"] == "qwen3:8b"
    assert captured["json"]["max_tokens"] == 1024
    assert captured["json"]["response_format"]["json_schema"]["schema"] == {"type": "object"}
    prompt_context = json.loads(captured["json"]["messages"][1]["content"])
    assert prompt_context["question"] == "How many rows?"
    assert prompt_context["dataset_schema"] == request.dataset_schema
    assert prompt_context["planning_constraints"]["line_chart_eligible_columns"] == []
    assert result.payload == {"plan_version": 2}
    assert result.usage.input_tokens == 12


def test_ollama_adapter_disables_thinking_natively(monkeypatch):
    captured = {}

    class OllamaResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {"content": json.dumps({"plan_version": 2})},
                "prompt_eval_count": 8,
                "eval_count": 3,
            }

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return OllamaResponse()

    monkeypatch.setattr("packages.llm_gateway.adapters.ollama.httpx.post", fake_post)
    route = ModelRoute(
        stable_id="qwen-local",
        label="Qwen Local",
        provider="ollama",
        provider_model="qwen3:8b",
        base_url="http://localhost:11434",
        description="Local model",
    )
    request = PlanRequest(
        question="How many rows?",
        dataset_schema={"columns": []},
        dataset_profile={},
        response_schema={"type": "object"},
        prompt_version="test-v1",
    )

    result = OllamaAdapter().generate_plan(route, request)

    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["think"] is False
    assert captured["json"]["format"] == request.response_schema
    assert captured["json"]["options"]["num_predict"] == 1024
    assert result.payload == {"plan_version": 2}
