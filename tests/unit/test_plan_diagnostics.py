from app.services.plan_service import missing_data_clarification, safe_validation_diagnostic
from pydantic import ValidationError

from packages.data_engine.query_plan import PlanError, QueryPlan


def test_safe_diagnostic_preserves_metric_type_context():
    error = PlanError(
        "avg requires a numeric column",
        code="METRIC_TYPE_MISMATCH",
        details={
            "operation": "avg",
            "column": "category",
            "actual_type": "text",
            "expected_types": ["integer", "number"],
        },
    )
    assert safe_validation_diagnostic(error) == {
        "code": "METRIC_TYPE_MISMATCH",
        "operation": "avg",
        "column": "category",
        "actual_type": "text",
        "expected_types": ["integer", "number"],
    }


def test_quantity_type_mismatch_becomes_missing_measure_clarification():
    message = missing_data_clarification(
        [{"code": "METRIC_TYPE_MISMATCH", "column": "category"}],
        "What is the average number of books sold per day?",
        {"category": "text", "revenue": "number", "date": "date"},
    )
    assert message == (
        "This dataset does not contain a recognized quantity field. Which available field "
        "should be used instead, or how should it be calculated?"
    )


def test_malformed_plan_diagnostic_remains_bounded():
    try:
        QueryPlan.model_validate({"plan_version": 2})
    except ValidationError as error:
        diagnostic = safe_validation_diagnostic(error)
    assert diagnostic["code"] == "MALFORMED_PLAN"
    assert len(diagnostic["issues"]) <= 8


def test_validator_semantic_diagnostics_are_specific_and_do_not_store_filter_values():
    import copy

    import pytest

    from packages.data_engine.query_plan import validate_plan

    catalog = {
        "category": "text",
        "revenue": "number",
        "active": "boolean",
        "date": "date",
        "timestamp": "timestamp",
        "zoned": "timestamp_tz",
    }
    base = {
        "plan_version": 2,
        "dimensions": ["category"],
        "metrics": [{"op": "sum", "column": "revenue", "alias": "total"}],
        "filters": [],
        "order_by": [],
        "limit": 100,
        "presentation": {"type": "table"},
    }
    variants = [
        ({"dimensions": ["category", "category"]}, "DUPLICATE_DIMENSION"),
        ({"metrics": base["metrics"] * 2}, "DUPLICATE_METRIC_ALIAS"),
        (
            {"metrics": [{"op": "sum", "column": "revenue", "alias": "category"}]},
            "METRIC_ALIAS_COLLISION",
        ),
        (
            {"filters": [{"column": "active", "op": "eq", "value": "private-value"}]},
            "FILTER_TYPE_MISMATCH",
        ),
        (
            {"filters": [{"column": "active", "op": "gt", "value": True}]},
            "FILTER_OPERATION_MISMATCH",
        ),
        (
            {"filters": [{"column": "date", "op": "eq", "value": "private-value"}]},
            "INVALID_TEMPORAL_FILTER",
        ),
        (
            {"filters": [{"column": "date", "op": "eq", "value": "2026-01-01T00:00:00"}]},
            "TEMPORAL_FILTER_TYPE_MISMATCH",
        ),
        (
            {"filters": [{"column": "zoned", "op": "eq", "value": "2026-01-01T00:00:00"}]},
            "TEMPORAL_FILTER_TYPE_MISMATCH",
        ),
        ({"order_by": [{"field": "total", "direction": "desc"}] * 2}, "DUPLICATE_ORDERING_FIELD"),
        ({"order_by": [{"field": "revenue", "direction": "desc"}]}, "UNKNOWN_ORDERING_FIELD"),
        ({"dimensions": [], "presentation": {"type": "bar"}}, "CHART_DIMENSION_COUNT"),
        (
            {
                "metrics": [
                    {"op": "sum", "column": "revenue", "alias": f"total_{i}"} for i in range(5)
                ],
                "presentation": {"type": "bar"},
            },
            "CHART_METRIC_COUNT",
        ),
        (
            {
                "metrics": [{"op": "min", "column": "date", "alias": "first_date"}],
                "presentation": {"type": "bar"},
            },
            "CHART_METRIC_TYPE_MISMATCH",
        ),
        (
            {"dimensions": ["active"], "presentation": {"type": "line"}},
            "LINE_DIMENSION_TYPE_MISMATCH",
        ),
        (
            {"metrics": [{"op": "min", "column": "active", "alias": "first_active"}]},
            "METRIC_TYPE_MISMATCH",
        ),
    ]
    for changes, code in variants:
        with pytest.raises(PlanError) as caught:
            validate_plan(copy.deepcopy(base) | changes, catalog)
        diagnostic = safe_validation_diagnostic(caught.value)
        assert diagnostic["code"] == code
        assert len(diagnostic) > 1
        assert "private-value" not in str(diagnostic)
    with pytest.raises(PlanError) as caught:
        validate_plan(base, {})
    assert caught.value.code == "INVALID_CATALOG"
    with pytest.raises(PlanError) as caught:
        validate_plan(base, catalog | {"Category": "text"})
    assert caught.value.code == "CATALOG_COLUMN_COLLISION"


def test_chart_diagnostics_preserve_counts_and_bound_fields():
    diagnostic = safe_validation_diagnostic(
        PlanError(
            "chart failure",
            code="CHART_DIMENSION_COUNT",
            details={
                "actual_count": 8,
                "expected_count": 1,
                "column": "x" * 1000,
                "fields": ["y" * 1000] * 20,
            },
        )
    )
    assert diagnostic["actual_count"] == 8
    assert diagnostic["expected_count"] == 1
    assert len(diagnostic["column"]) == 128
    assert len(diagnostic["fields"]) == 8
    assert all(len(field) == 64 for field in diagnostic["fields"])
