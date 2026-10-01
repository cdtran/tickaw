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


def test_active_count_guard_rejects_observed_non_null_substitution():
    issue = check_question_meaning(
        "How many active records are in each category?",
        plan({"op": "count_non_null", "column": "active", "alias": "active_count"}),
        CATALOG,
    )
    assert issue.code == "SEMANTIC_SUBSTITUTION"
    assert issue.concept == "active_record_count"


def test_active_count_requires_true_filter_and_accepts_equivalent_boolean_filter():
    from packages.data_engine.query_plan import Comparison

    count = plan({"op": "count_rows", "alias": "record_count"})
    question = "How many active records are in each category?"
    assert check_question_meaning(question, count, CATALOG).code == "MISSING_REQUIRED_FILTER"
    for op, value in [("eq", True), ("ne", False)]:
        filtered = count.model_copy(
            update={"filters": [Comparison(column="active", op=op, value=value)]}
        )
        assert check_question_meaning(question, filtered, CATALOG) is None
    wrong = count.model_copy(
        update={"filters": [Comparison(column="active", op="eq", value=False)]}
    )
    assert check_question_meaning(question, wrong, CATALOG).code == "MISSING_REQUIRED_FILTER"


def test_active_guard_abstains_on_ambiguous_wording_schema_and_clarification():
    count = plan({"op": "count_rows", "alias": "record_count"})
    for question in [
        "Count inactive records by category.",
        "Count active and inactive records.",
        "Count non-null active values by category.",
        "Show active records by category.",
        "How many active records were there before activation?",
    ]:
        assert check_question_meaning(question, count, CATALOG) is None
    assert (
        check_question_meaning("Count active records.", count, CATALOG | {"active": "text"}) is None
    )
    assert (
        check_question_meaning(
            "Count active records.", count, CATALOG, clarification="Include inactive records too."
        )
        is None
    )
