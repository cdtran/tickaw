from evals.model_quality.evaluator import case_by_id, catalog_for, load_suite, score_payload


def test_corpus_is_well_formed_and_covers_quality_outcomes():
    suite, _ = load_suite()
    represented = {case["expected_outcome"] for case in suite["cases"]}
    represented.update(item["expected_outcome"] for item in suite["classification_fixtures"])
    assert represented == {
        "valid_plan",
        "needs_clarification",
        "invalid_model_output",
        "unanswerable_with_available_data",
        "semantically_misleading_substitution",
    }


def test_named_regression_cases_are_present():
    suite, _ = load_suite()
    assert len(suite["cases"]) >= 20
    assert {
        "average-books-sold-per-day",
        "book-transaction-rows-per-day",
        "average-book-revenue-per-day",
        "revenue-by-category-and-date",
        "quantity-language-without-quantity",
    } <= {case["id"] for case in suite["cases"]}


def test_classification_fixtures_have_expected_outcomes():
    suite, dataset = load_suite()
    catalog = catalog_for(dataset)
    for fixture in suite["classification_fixtures"]:
        case = (
            case_by_id(suite, fixture["case_id"])
            if fixture.get("case_id")
            else {"expected_outcome": fixture["expected_outcome"]}
        )
        assert (
            score_payload(case, fixture["payload"], catalog).outcome == fixture["expected_outcome"]
        )


def test_answerable_plan_is_scored_by_meaning_not_alias_spelling():
    suite, dataset = load_suite()
    case = case_by_id(suite, "average-book-revenue-per-day")
    result = score_payload(
        case,
        {
            "plan_version": 2,
            "dimensions": ["date"],
            "metrics": [{"op": "avg", "column": "revenue", "alias": "mean_book_revenue"}],
            "filters": [{"column": "category", "op": "eq", "value": "Books"}],
            "order_by": [],
            "limit": 100,
            "presentation": {"type": "line"},
        },
        catalog_for(dataset),
    )
    assert result.outcome == "valid_plan"


def test_ranked_case_checks_order_and_limit_without_fixing_alias_spelling():
    suite, dataset = load_suite()
    case = case_by_id(suite, "highest-revenue-category")
    payload = {
        "plan_version": 2,
        "dimensions": ["category"],
        "metrics": [{"op": "sum", "column": "revenue", "alias": "revenue_total"}],
        "filters": [],
        "order_by": [{"field": "revenue_total", "direction": "desc"}],
        "limit": 1,
        "presentation": {"type": "bar"},
    }
    assert score_payload(case, payload, catalog_for(dataset)).outcome == "valid_plan"

    payload["limit"] = 100
    result = score_payload(case, payload, catalog_for(dataset))
    assert result.outcome == "semantically_misleading_substitution"
    assert result.reasons == ("limit was 100, expected 1",)


def test_smoke_tier_is_small_and_part_of_full():
    suite, _ = load_suite()
    smoke = [case for case in suite["cases"] if "smoke" in case["tags"]]
    assert 5 <= len(smoke) <= 8
    assert all("full" in case["tags"] for case in suite["cases"])


def test_cache_reuses_responses_and_invalidates_inputs(tmp_path):
    from types import SimpleNamespace

    from evals.model_quality.recording import RecordingGateway
    from packages.llm_gateway.contracts import ModelUsage, PlanRequest, PlanResponse

    route = SimpleNamespace(provider_model="test", provider="ollama", base_url="http://local")
    calls = []

    def generate(model, request):
        calls.append(request)
        return PlanResponse(
            payload={},
            stable_model_id=model,
            provider="ollama",
            provider_model="test",
            prompt_version=request.prompt_version,
            usage=ModelUsage(input_tokens=10, output_tokens=5),
        )

    gateway = SimpleNamespace(
        registry=SimpleNamespace(resolve=lambda _: route), generate_plan=generate
    )
    request = PlanRequest(
        question="synthetic",
        dataset_schema={},
        dataset_profile={},
        response_schema={},
        prompt_version="test",
    )
    recorder = RecordingGateway(gateway, {"id": "test"}, {}, tmp_path)
    recorder.generate_plan("test", request)
    recorder.generate_plan("test", request)
    assert len(calls) == 1
    assert recorder.cache_hits == 1
    recorder.generate_plan("test", request.model_copy(update={"validation_feedback": "retry"}))
    assert len(calls) == 2
    route.provider_model = "new-model"
    recorder.generate_plan("test", request)
    assert len(calls) == 3
    refreshed = RecordingGateway(gateway, {"id": "test"}, {}, tmp_path, refresh=True)
    refreshed.generate_plan("test", request)
    assert len(calls) == 4
    assert refreshed.cache_hits == 0


def test_provider_errors_are_distinct_and_not_cached(tmp_path):
    from types import SimpleNamespace

    from evals.model_quality.recording import RecordingGateway
    from evals.model_quality.run import evaluate_case
    from packages.llm_gateway.adapters.openai_compatible import ModelProviderError

    def fail(*args):
        raise ModelProviderError("sensitive provider error")

    route = SimpleNamespace(provider_model="test", provider="ollama", base_url="http://local")
    gateway = SimpleNamespace(registry=SimpleNamespace(resolve=lambda _: route), generate_plan=fail)
    suite, dataset = load_suite()
    case = suite["cases"][0]
    recorder = RecordingGateway(gateway, case, dataset, tmp_path)
    result = evaluate_case(recorder, "test", case, dataset, catalog_for(dataset))
    assert result.outcome == "provider_runtime_failure"
    assert result.reasons == ("PROVIDER_ERROR",)
    assert recorder.attempts == 1
    assert list(tmp_path.iterdir()) == []


def test_report_metadata_and_cached_run(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from evals.model_quality import run as runner
    from packages.llm_gateway.contracts import ModelUsage, PlanResponse

    calls = []
    route = SimpleNamespace(provider_model="test", provider="ollama", base_url="http://local")

    def generate(model, request):
        calls.append(request)
        return PlanResponse(
            payload={
                "plan_version": 2,
                "dimensions": [],
                "metrics": [{"op": "sum", "column": "revenue", "alias": "total"}],
                "filters": [],
                "order_by": [],
                "limit": 100,
                "presentation": {"type": "table"},
            },
            stable_model_id=model,
            provider="ollama",
            provider_model="test",
            prompt_version=request.prompt_version,
            usage=ModelUsage(input_tokens=10, output_tokens=5),
        )

    monkeypatch.setattr(
        runner,
        "get_llm_gateway",
        lambda: SimpleNamespace(
            registry=SimpleNamespace(resolve=lambda _: route), generate_plan=generate
        ),
    )
    report = tmp_path / "report.json"
    kwargs = {
        "report_path": report,
        "cache_dir": tmp_path / "cache",
        "input_rate": 1.0,
        "output_rate": 2.0,
    }
    suite_path = runner.Path(runner.__file__).with_name("cases.json")
    assert runner.run("test", suite_path, {"total-revenue"}, **kwargs) == 0
    record = json.loads(report.read_text())["cases"][0]
    assert record["attempt_count"] == 1
    assert record["input_tokens"] == 10
    assert record["estimated_response_cost_usd"] == 0.00002
    assert "question" not in record and "payload" not in record
    assert runner.run("test", suite_path, {"total-revenue"}, **kwargs) == 0
    assert len(calls) == 1
    assert json.loads(report.read_text())["cases"][0]["cache_hits"] == 1
