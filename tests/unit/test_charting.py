"""Deterministic chart specifications for persisted result artifacts."""

from packages.charting.specs import ChartSpec, chart_spec_for
from packages.data_engine.result_types import ResultColumn, TableResult


def table(columns, rows):
    return TableResult(
        columns=columns,
        rows=rows,
        returned_rows=len(rows),
        requested_limit=100,
        truncated=False,
        warnings=[],
        checks=[],
    )


def column(name, kind, encoding="json"):
    return ResultColumn(
        name=name,
        logical_type=kind,
        database_type="TEST",
        encoding=encoding,
    )


def test_category_result_becomes_bar_chart():
    spec = chart_spec_for(
        table(
            [column("region", "text"), column("revenue", "number")],
            [["East", 10], ["West", 20]],
        ),
        "bar",
    )
    assert spec == ChartSpec(
        type="bar",
        x="region",
        series=[{"column": "revenue", "label": "revenue"}],
    )


def test_time_result_becomes_line_chart_without_inventing_gap_fill():
    spec = chart_spec_for(
        table(
            [column("month", "date", "iso_date"), column("revenue", "number")],
            [["2026-01-01", 10], ["2026-03-01", 30]],
        ),
        "line",
    )
    assert spec is not None
    assert spec.type == "line"
    assert spec.missing_periods == "none"


def test_legacy_iso_date_text_result_can_become_line_chart():
    spec = chart_spec_for(
        table(
            [column("date", "text"), column("revenue", "number")],
            [["2026-01-01", 10], ["2026-01-02", 20]],
        ),
        "line",
    )
    assert spec is not None
    assert spec.type == "line"


def test_unsafe_or_unhelpful_shapes_are_table_only():
    assert chart_spec_for(table([column("total", "number")], [[10]]), "bar") is None
    assert chart_spec_for(
        table([column("region", "text"), column("total", "number")], [["East", 10]]),
        "table",
    ) is None
    assert chart_spec_for(
        table([column("region", "text"), column("total", "number")], [["East", 10]]),
        "line",
    ) is None
    assert (
        chart_spec_for(
            table(
                [column("region", "text"), column("product", "text"), column("total", "number")],
                [["East", "A", 10]],
            ),
            "bar",
        )
        is None
    )
    assert (
        chart_spec_for(
            table(
                [column("region", "text"), column("huge", "integer", "integer_string")],
                [["East", "9007199254740993"]],
            ),
            "bar",
        )
        is None
    )
    assert (
        chart_spec_for(
            table(
                [column("region", "text"), column("total", "number")],
                [[str(index), index] for index in range(61)],
            ),
            "bar",
        )
        is None
    )
