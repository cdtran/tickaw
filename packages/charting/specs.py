"""Deterministic, provider-neutral chart specifications for structured results."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.data_engine.result_types import TableResult
from packages.data_engine.temporal import parse_temporal

CHART_ROW_LIMIT = 60


class ChartModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ChartSeries(ChartModel):
    column: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=128)


class ChartSpec(ChartModel):
    spec_version: Literal[1] = 1
    type: Literal["bar", "line"]
    x: str = Field(min_length=1, max_length=128)
    series: list[ChartSeries] = Field(min_length=1, max_length=4)
    missing_periods: Literal["none", "zero"] = "none"


def chart_spec_for(table: TableResult, chart_type: Literal["table", "bar", "line"]) -> ChartSpec | None:
    """Build the requested chart only when the executed result remains compatible.

    Exact large integers are excluded because converting them to browser numbers
    would lose precision. Missing-period behavior reflects the executed result;
    the query planner will set zero once temporal gap filling is implemented.
    """
    if chart_type == "table" or not table.rows or len(table.rows) > CHART_ROW_LIMIT:
        return None
    metrics = [
        column
        for column in table.columns
        if column.logical_type in {"integer", "number"} and column.encoding != "integer_string"
    ]
    metric_names = {column.name for column in metrics}
    dimensions = [column for column in table.columns if column.name not in metric_names]
    if len(dimensions) != 1 or not 1 <= len(metrics) <= 4:
        return None
    dimension = dimensions[0]
    if dimension.logical_type not in {
        "text",
        "boolean",
        "date",
        "timestamp",
        "timestamp_tz",
    }:
        return None
    if chart_type == "line" and dimension.logical_type not in {"date", "timestamp", "timestamp_tz"}:
        if dimension.logical_type != "text":
            return None
        values = [row[0] for row in table.rows if row[0] is not None]
        if not values or any(not isinstance(value, str) for value in values):
            return None
        try:
            kinds = {parse_temporal(value)[0] for value in values}
        except (ValueError, OverflowError):
            return None
        if len(kinds) != 1 or len(kinds) == 0:
            return None
    return ChartSpec(
        type=chart_type,
        x=dimension.name,
        series=[ChartSeries(column=column.name, label=column.name) for column in metrics],
    )
