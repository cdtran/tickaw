"""Known-answer compiler tests; questions are seeds for future live-model evals."""

import json
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError
from sqlglot import exp

from packages.data_engine.query_compiler import build_ast, compile_sql
from packages.data_engine.query_plan import PlanError, QueryPlan, validate_plan

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "query_plans"
FIXTURE = json.loads((EXAMPLES / "sales.fixture.json").read_text())
CASES = [json.loads(path.read_text()) for path in sorted(EXAMPLES.glob("*.case.json"))]
COLUMNS = FIXTURE["columns"]


def basic():
    return {
        "plan_version": 2,
        "dimensions": ["region"],
        "metrics": [{"op": "sum", "column": "revenue", "alias": "total_revenue"}],
        "filters": [],
        "order_by": [],
        "limit": 100,
        "presentation": {"type": "bar"},
    }


@pytest.fixture
def db():
    with duckdb.connect(":memory:") as connection:
        connection.execute("""CREATE TABLE dataset (
            region VARCHAR, product VARCHAR, revenue DOUBLE, sold_on DATE, refunded BOOLEAN
        )""")
        connection.executemany("INSERT INTO dataset VALUES (?, ?, ?, ?, ?)", FIXTURE["rows"])
        yield connection


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_known_answers(case, db):
    tree = build_ast(case["plan"], COLUMNS)
    assert isinstance(tree, exp.Select)
    assert [table.name for table in tree.find_all(exp.Table)] == ["dataset"]
    result = db.execute(compile_sql(case["plan"], COLUMNS))
    assert [item[0] for item in result.description] == case["expected_columns"]
    assert [list(row) for row in result.fetchall()] == case["expected_rows"]


@pytest.mark.parametrize(
    "patch",
    [
        {"sql": "SELECT 1"},
        {"source": "/etc/passwd"},
        {"plan_version": 1},
        {"plan_version": True},
        {"plan_version": 2.0},
        {"presentation": {"type": "pie"}},
        {"presentation": {"type": "bar", "x": "region"}},
        {"limit": True},
        {"limit": "10"},
        {"limit": 0},
        {"limit": 1001},
        {"metrics": []},
        {"dimensions": ["region"] * 9},
        {"metrics": [{"op": "median", "column": "revenue", "alias": "x"}]},
        {"metrics": [{"op": "count_rows", "column": "revenue", "alias": "x"}]},
        {"metrics": [{"op": "sum", "column": "revenue", "alias": "x; DROP TABLE dataset"}]},
        {"filters": [{"column": "region", "op": "eq", "value": None}]},
        {"filters": [{"column": "region", "op": "is_null", "value": "x"}]},
        {"filters": [{"column": "revenue", "op": "eq", "value": float("nan")}]},
        {"filters": [{"column": "revenue", "op": "eq", "value": float("inf")}]},
    ],
)
def test_rejects_bad_structure(patch):
    with pytest.raises(ValidationError):
        compile_sql(basic() | patch, COLUMNS)


@pytest.mark.parametrize("field", list(basic()))
def test_every_field_is_required(field):
    payload = basic()
    del payload[field]
    with pytest.raises(ValidationError):
        validate_plan(payload, COLUMNS)


@pytest.mark.parametrize(
    "patch",
    [
        {"dimensions": ["unknown"]},
        {"dimensions": ["region", "region"]},
        {"metrics": [{"op": "sum", "column": "region", "alias": "x"}]},
        {"metrics": [{"op": "avg", "column": "unknown", "alias": "x"}]},
        {"metrics": [{"op": "min", "column": "refunded", "alias": "x"}]},
        {"metrics": [{"op": "count_rows", "alias": "region"}]},
        {"metrics": [{"op": "count_rows", "alias": "x"}] * 2},
        {"filters": [{"column": "unknown", "op": "is_null"}]},
        {"filters": [{"column": "revenue", "op": "eq", "value": "10"}]},
        {"filters": [{"column": "revenue", "op": "eq", "value": True}]},
        {"filters": [{"column": "region", "op": "eq", "value": 10}]},
        {"filters": [{"column": "refunded", "op": "gt", "value": False}]},
        {"filters": [{"column": "sold_on", "op": "eq", "value": "2025-02-30"}]},
        {"filters": [{"column": "sold_on", "op": "eq", "value": "20250101"}]},
        {"order_by": [{"field": "revenue", "direction": "desc"}]},
        {"order_by": [{"field": "region", "direction": "asc"}] * 2},
        {"dimensions": [], "presentation": {"type": "bar"}},
        {
            "metrics": [{"op": "min", "column": "region", "alias": "first_region"}],
            "presentation": {"type": "bar"},
        },
    ],
)
def test_rejects_invalid_meaning(patch):
    with pytest.raises(PlanError):
        compile_sql(basic() | patch, COLUMNS)


def test_catalog_and_alias_case_collisions():
    with pytest.raises(PlanError, match="collisions"):
        validate_plan(basic(), COLUMNS | {"Region": "text"})
    with pytest.raises(PlanError, match="collide"):
        validate_plan(basic(), COLUMNS | {"TOTAL_REVENUE": "number"})


def test_text_dimension_can_reach_runtime_line_chart_validation():
    plan = basic() | {"dimensions": ["date_text"], "presentation": {"type": "line"}}
    validated = validate_plan(plan, COLUMNS | {"date_text": "text"})
    assert validated.presentation.type == "line"


def test_unsupported_dialect():
    with pytest.raises(ValueError, match="Untested"):
        compile_sql(basic(), COLUMNS, dialect="postgres")


@pytest.mark.parametrize(
    "op,expected",
    [
        ("eq", 1),
        ("ne", 6),
        ("gt", 4),
        ("gte", 5),
        ("lt", 2),
        ("lte", 3),
    ],
)
def test_comparison_operators(op, expected, db):
    payload = basic() | {
        "dimensions": [],
        "metrics": [{"op": "count_rows", "alias": "n"}],
        "filters": [{"column": "revenue", "op": op, "value": 10}],
        "presentation": {"type": "table"},
    }
    assert db.execute(compile_sql(payload, COLUMNS)).fetchone() == (expected,)


@pytest.mark.parametrize(
    "condition,expected",
    [
        ({"column": "revenue", "op": "is_not_null"}, 7),
        ({"column": "refunded", "op": "eq", "value": True}, 1),
        ({"column": "refunded", "op": "ne", "value": True}, 7),
        ({"column": "region", "op": "eq", "value": "West' OR TRUE --"}, 0),
    ],
)
def test_typed_and_quoted_values(condition, expected, db):
    payload = basic() | {
        "dimensions": [],
        "metrics": [{"op": "count_rows", "alias": "n"}],
        "filters": [condition],
        "presentation": {"type": "table"},
    }
    assert db.execute(compile_sql(payload, COLUMNS)).fetchone() == (expected,)


def test_sql_looking_column_is_one_identifier():
    header = 'a.b"; DROP TABLE dataset; --'
    payload = basic() | {"dimensions": [header], "metrics": [{"op": "count_rows", "alias": "n"}]}
    with duckdb.connect(":memory:") as connection:
        connection.execute('CREATE TABLE dataset ("' + header.replace('"', '""') + '" VARCHAR)')
        connection.execute("INSERT INTO dataset VALUES ('ok')")
        tree = build_ast(payload, {header: "text"})
        assert all(node.name == header for node in tree.find_all(exp.Column))
        assert connection.execute(compile_sql(payload, {header: "text"})).fetchall() == [("ok", 1)]


def test_min_max_multigroup_and_null_aggregate(db):
    payload = basic() | {
        "dimensions": ["region", "product"],
        "metrics": [
            {"op": "min", "column": "revenue", "alias": "low"},
            {"op": "max", "column": "revenue", "alias": "high"},
        ],
        "presentation": {"type": "table"},
    }
    assert db.execute(compile_sql(payload, COLUMNS)).fetchall() == [
        ("East", "A", 5, 15),
        ("East", "B", None, None),
        ("North", "A", 20, 20),
        ("North", "B", 20, 20),
        ("West", "A", 10, 10),
        ("West", "B", 30, 30),
        (None, "A", 7, 7),
    ]


def test_empty_grouped_result(db):
    payload = basic() | {"filters": [{"column": "region", "op": "eq", "value": "South"}]}
    assert db.execute(compile_sql(payload, COLUMNS)).fetchall() == []


def test_schema_artifact_matches_source():
    assert (
        json.loads((EXAMPLES / "query-plan.schema.json").read_text())
        == QueryPlan.model_json_schema()
    )


def test_integer_filters_are_not_coerced():
    payload = basic() | {
        "dimensions": [],
        "metrics": [{"op": "count_rows", "alias": "n"}],
        "filters": [{"column": "quantity", "op": "eq", "value": 2}],
        "presentation": {"type": "table"},
    }
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE dataset(quantity INTEGER)")
        connection.execute("INSERT INTO dataset VALUES (2), (3), (NULL)")
        assert connection.execute(compile_sql(payload, {"quantity": "integer"})).fetchone() == (1,)
    payload["filters"][0]["value"] = 2.0
    with pytest.raises(PlanError):
        compile_sql(payload, {"quantity": "integer"})


def test_fractional_and_negative_values():
    payload = basic() | {
        "dimensions": [],
        "filters": [{"column": "revenue", "op": "gte", "value": -0.5}],
        "presentation": {"type": "table"},
    }
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE dataset(revenue DOUBLE)")
        connection.execute("INSERT INTO dataset VALUES (-0.5), (0.1), (0.2), (NULL), (-10)")
        value = connection.execute(compile_sql(payload, {"revenue": "number"})).fetchone()[0]
        assert value == pytest.approx(-0.2, abs=1e-12)


def test_decimal_aggregation_preserves_precision():
    from decimal import Decimal

    payload = basic() | {"dimensions": [], "presentation": {"type": "table"}}
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE dataset(revenue DECIMAL(10, 2))")
        connection.execute("INSERT INTO dataset VALUES (0.10), (0.20), (NULL)")
        assert connection.execute(compile_sql(payload, {"revenue": "number"})).fetchone() == (
            Decimal("0.30"),
        )


def test_nulls_last_even_for_descending_order(db):
    payload = basic() | {"order_by": [{"field": "region", "direction": "desc"}]}
    assert [row[0] for row in db.execute(compile_sql(payload, COLUMNS)).fetchall()] == [
        "West",
        "North",
        "East",
        None,
    ]


def test_physical_empty_table(db):
    db.execute("DELETE FROM dataset")
    payload = basic() | {
        "dimensions": [],
        "metrics": [
            {"op": "sum", "column": "revenue", "alias": "total"},
            {"op": "count_rows", "alias": "n"},
        ],
        "presentation": {"type": "table"},
    }
    assert db.execute(compile_sql(payload, COLUMNS)).fetchall() == [(None, 0)]
