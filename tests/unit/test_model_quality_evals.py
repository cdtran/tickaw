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
        assert score_payload(case, fixture["payload"], catalog).outcome == fixture["expected_outcome"]


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
