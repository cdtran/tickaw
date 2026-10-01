import json
from types import SimpleNamespace

import httpx
import pytest

from packages.data_engine.query_plan import QueryPlan
from packages.llm_gateway.adapters.openai import OpenAIAdapter, PaidRunBlocked, response_schema
from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import ModelRoute, PlanRequest


def route():
    return ModelRoute(
        stable_id="openai-analysis",
        label="OpenAI",
        provider="openai",
        provider_model="explicit-model",
        base_url="https://api.openai.com/v1",
        description="Paid",
        api_key="test-secret",
    )


def request():
    return PlanRequest(
        question="Total revenue?",
        dataset_schema={},
        dataset_profile={},
        response_schema=QueryPlan.model_json_schema(),
        prompt_version="test",
    )


def adapter(**overrides):
    return OpenAIAdapter(
        **(
            {
                "allow_paid": True,
                "max_cost_usd": 1,
                "max_requests": 2,
                "input_rate": 1,
                "output_rate": 2,
            }
            | overrides
        )
    )


def mock_http(monkeypatch, document=None):
    calls = []
    document = document or {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps({"plan_version": 2})}],
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        result = {"input_tokens": 100} if url.endswith("input_tokens") else document
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: result)

    monkeypatch.setattr("packages.llm_gateway.adapters.openai.httpx.post", post)
    return calls


@pytest.mark.parametrize(
    "options",
    [
        {"allow_paid": False},
        {"max_cost_usd": None},
        {"max_requests": None},
        {"input_rate": None},
        {"output_rate": None},
        {"max_output_tokens": 0},
    ],
)
def test_missing_policy_blocks_all_network(monkeypatch, options):
    calls = mock_http(monkeypatch)
    with pytest.raises(PaidRunBlocked):
        adapter(**options).generate_plan(route(), request())
    assert calls == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_nonfinite_or_nonpositive_prices_rejected(value):
    with pytest.raises(ValueError):
        adapter(input_rate=value)


def test_responses_contract_and_shared_reservations(monkeypatch):
    calls = mock_http(monkeypatch)
    provider = adapter(max_requests=1)
    result = provider.generate_plan(route(), request())
    assert result.usage.input_tokens == 100
    assert result.payload == {"plan_version": 2}
    count_body = calls[0][1]["json"]
    body = calls[1][1]["json"]
    assert body == count_body | {"store": False, "max_output_tokens": 1024}
    assert body["text"]["format"]["strict"] is True
    assert "oneOf" not in json.dumps(body["text"]["format"]["schema"])
    assert calls[1][1]["headers"]["Authorization"] == "Bearer test-secret"
    assert float(provider.reserved_cost) == pytest.approx(0.002148)
    with pytest.raises(PaidRunBlocked):
        provider.generate_plan(route(), request().model_copy(update={"validation_feedback": "fix"}))
    assert len(calls) == 2


def test_budget_checked_before_generation(monkeypatch):
    calls = mock_http(monkeypatch)
    provider = adapter(max_cost_usd=0.001)
    with pytest.raises(PaidRunBlocked):
        provider.generate_plan(route(), request())
    assert len(calls) == 1
    assert provider.requests == 0


@pytest.mark.parametrize(
    "document",
    [
        {"status": "incomplete"},
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}],
        },
        {"status": "completed", "output": []},
    ],
)
def test_bad_responses_keep_reservations(monkeypatch, document):
    calls = mock_http(monkeypatch, document)
    provider = adapter()
    with pytest.raises(ModelProviderError):
        provider.generate_plan(route(), request())
    assert provider.requests == 1
    assert provider.reserved_cost > 0
    assert len(calls) == 2


def test_count_failure_never_generates(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        raise httpx.ReadTimeout("secret error")

    monkeypatch.setattr("packages.llm_gateway.adapters.openai.httpx.post", post)
    provider = adapter()
    with pytest.raises(ModelProviderError, match="valid query plan"):
        provider.generate_plan(route(), request())
    assert len(calls) == 1
    assert provider.requests == 0


def test_schema_conversion_preserves_local_schema():
    schema = QueryPlan.model_json_schema()
    converted = response_schema(schema)
    assert "oneOf" in json.dumps(schema)
    assert "oneOf" not in json.dumps(converted)
    assert converted["required"] == schema["required"]


def test_cache_reuse_needs_no_paid_optin(tmp_path, monkeypatch):
    from evals.model_quality.recording import RecordingGateway
    from packages.llm_gateway.gateway import LLMGateway
    from packages.llm_gateway.registry import ModelRegistry

    calls = mock_http(monkeypatch)
    registry = ModelRegistry([route()])

    def recording(provider):
        return RecordingGateway(
            LLMGateway(registry, {"openai": provider}), {"id": "test"}, {}, tmp_path
        )

    recording(adapter()).generate_plan("openai-analysis", request())
    cached = recording(adapter(allow_paid=False))
    cached.generate_plan("openai-analysis", request())
    assert cached.cache_hits == 1
    assert len(calls) == 2
    with pytest.raises(PaidRunBlocked):
        cached.generate_plan("openai-analysis", request().model_copy(update={"question": "New?"}))


def test_registry_keeps_local_default_and_exposes_enabled_openai(monkeypatch):
    from app.core.config import Settings
    from app.services import llm_service

    settings = Settings(
        database_url="postgresql://test",
        llm_enabled_models="qwen-local,openai-analysis",
        openai_model="explicit-model",
        openai_api_key="test-secret",
    )
    monkeypatch.setattr(llm_service, "get_settings", lambda: settings)
    llm_service.get_model_registry.cache_clear()
    try:
        registry = llm_service.get_model_registry()
        assert registry.available()[0].id == "qwen-local"
        info = registry.available()[1]
        assert info.requires_api_key
        assert "test-secret" not in info.model_dump_json()
        assert registry.resolve("openai-analysis").provider_model == "explicit-model"
    finally:
        llm_service.get_model_registry.cache_clear()


def test_eval_requires_its_own_optin_and_reports_policy_block(tmp_path, monkeypatch):
    from evals.model_quality import run as runner
    from packages.llm_gateway.gateway import LLMGateway
    from packages.llm_gateway.registry import ModelRegistry

    calls = mock_http(monkeypatch)
    gateway = LLMGateway(ModelRegistry([route()]), {"openai": adapter()})
    monkeypatch.setattr(runner, "get_llm_gateway", lambda: gateway)
    report = tmp_path / "report.json"
    assert (
        runner.run(
            "openai-analysis",
            runner.Path(runner.__file__).with_name("cases.json"),
            {"total-revenue"},
            cache_dir=None,
            report_path=report,
        )
        == 1
    )
    document = json.loads(report.read_text())
    assert document["cases"][0]["failure_category"] == "paid_run_blocked"
    assert document["summary"]["paid_run"]["generation_requests"] == 0
    assert calls == []


def test_generation_timeout_retains_budget_and_does_not_retry(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if url.endswith("input_tokens"):
            return SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {"input_tokens": 100}
            )
        raise httpx.ReadTimeout("secret")

    monkeypatch.setattr("packages.llm_gateway.adapters.openai.httpx.post", post)
    provider = adapter(max_requests=1)
    with pytest.raises(ModelProviderError):
        provider.generate_plan(route(), request())
    with pytest.raises(PaidRunBlocked):
        provider.generate_plan(route(), request())
    assert provider.requests == 1
    assert float(provider.reserved_cost) == pytest.approx(0.002148)
    assert len(calls) == 2


def test_dollar_limit_shared_across_success_and_correction(monkeypatch):
    calls = mock_http(monkeypatch)
    provider = adapter(max_cost_usd=0.003)
    provider.generate_plan(route(), request())
    with pytest.raises(PaidRunBlocked):
        provider.generate_plan(route(), request().model_copy(update={"validation_feedback": "fix"}))
    assert len(calls) == 3
    assert provider.requests == 1
