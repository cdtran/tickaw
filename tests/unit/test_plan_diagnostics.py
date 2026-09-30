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
