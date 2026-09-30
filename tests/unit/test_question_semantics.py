from packages.data_engine.query_plan import validate_plan
from packages.data_engine.question_semantics import check_question_meaning, requested_concepts

CATALOG = {
    "category": "text",
    "revenue": "number",
    "active": "boolean",
    "date": "date",
}


def plan(metric):
    return validate_plan(
        {
            "plan_version": 2,
            "dimensions": ["category"],
            "metrics": [metric],
            "filters": [],
            "order_by": [],
            "limit": 100,
            "presentation": {"type": "bar"},
        },
        CATALOG,
    )


def test_detects_explicit_missing_business_measures():
    assert requested_concepts("How many units were sold?") == {"quantity"}
    assert requested_concepts("What is profit margin by category?") == {"profit"}
    assert requested_concepts("What is total revenue?") == set()


def test_rejects_row_count_as_quantity():
    issue = check_question_meaning(
        "Which category sold the most products?",
        plan({"op": "count_rows", "alias": "products_sold"}),
        CATALOG,
    )
    assert issue is not None
    assert issue.code == "MISSING_MEASURE"
    assert issue.concept == "quantity"
    assert issue.plan_measure == "row_count"


def test_rejects_revenue_as_profit():
    issue = check_question_meaning(
        "What is profit by category?",
        plan({"op": "sum", "column": "revenue", "alias": "profit"}),
        CATALOG,
    )
    assert issue is not None and issue.concept == "profit"


def test_explicit_row_language_is_not_quantity_language():
    assert requested_concepts("Count the book transaction rows per day") == set()
    assert (
        check_question_meaning(
            "Count the book transaction rows per day",
            plan({"op": "count_rows", "alias": "row_count"}),
            CATALOG,
        )
        is None
    )


def test_uses_quantity_column_when_available():
    catalog = CATALOG | {"quantity": "integer"}
    quantity_plan = validate_plan(
        {
            "plan_version": 2,
            "dimensions": ["category"],
            "metrics": [{"op": "sum", "column": "quantity", "alias": "units_sold"}],
            "filters": [],
            "order_by": [],
            "limit": 100,
            "presentation": {"type": "bar"},
        },
        catalog,
    )
    assert check_question_meaning("How many units were sold?", quantity_plan, catalog) is None


def test_explicit_clarification_can_authorize_row_count_substitution():
    row_count_plan = plan({"op": "count_rows", "alias": "transaction_count"})
    assert (
        check_question_meaning(
            "How many units were sold by category?",
            row_count_plan,
            CATALOG,
            clarification="Use the count of transaction rows.",
        )
        is None
    )
