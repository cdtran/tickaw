"""Version 1 of the model-facing aggregate query language.

This module validates structure and meaning against a server-owned column catalog.
It has no LLM, database, or storage dependencies.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Name = Annotated[str, Field(min_length=1, max_length=128)]
Alias = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")]
Scalar = Annotated[str, Field(max_length=4096)] | int | float | bool
ColumnType = Literal["text", "integer", "number", "boolean", "date"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ColumnMetric(StrictModel):
    op: Literal["sum", "avg", "min", "max", "count_non_null"]
    column: Name
    alias: Alias


class RowCount(StrictModel):
    op: Literal["count_rows"]
    alias: Alias


Metric = Annotated[ColumnMetric | RowCount, Field(discriminator="op")]


class Comparison(StrictModel):
    column: Name
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    value: Scalar


class NullCheck(StrictModel):
    column: Name
    op: Literal["is_null", "is_not_null"]


Filter = Annotated[Comparison | NullCheck, Field(discriminator="op")]


class Ordering(StrictModel):
    field: Name
    direction: Literal["asc", "desc"]


class QueryPlan(StrictModel):
    plan_version: Literal[1]
    dimensions: Annotated[list[Name], Field(max_length=8)]
    metrics: Annotated[list[Metric], Field(min_length=1, max_length=16)]
    filters: Annotated[list[Filter], Field(max_length=20)]
    order_by: Annotated[list[Ordering], Field(max_length=8)]
    limit: Annotated[int, Field(ge=1, le=1000)]

    @field_validator("plan_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("plan_version must be the integer 1")
        return value


class PlanError(ValueError):
    """A structurally valid plan has unsupported or ambiguous semantics."""


def validate_plan(payload: dict, columns: dict[str, ColumnType]) -> QueryPlan:
    """Validate an untrusted plan against the pinned dataset's trusted catalog.

    Column names must be unambiguous under case-insensitive SQL resolution.
    Catalog normalization from profiler types is the caller's responsibility.
    """
    plan = QueryPlan.model_validate(payload)
    if not columns or any(
        t not in {"text", "integer", "number", "boolean", "date"} for t in columns.values()
    ):
        raise PlanError("Catalog must contain supported logical column types")
    if len({name.casefold() for name in columns}) != len(columns):
        raise PlanError("Catalog has case-insensitive column name collisions")

    def column_type(name):
        if name not in columns:
            raise PlanError(f"Unknown column: {name}")
        return columns[name]

    if len(set(plan.dimensions)) != len(plan.dimensions):
        raise PlanError("Duplicate grouping columns")
    for name in plan.dimensions:
        column_type(name)

    aliases = [metric.alias for metric in plan.metrics]
    if len(set(aliases)) != len(aliases):
        raise PlanError("Duplicate metric aliases")
    # Avoid engine-dependent resolution between source columns and output aliases.
    if any(alias.casefold() in {name.casefold() for name in columns} for alias in aliases):
        raise PlanError("Metric aliases must not collide with source columns")
    for metric in plan.metrics:
        if isinstance(metric, RowCount):
            continue
        kind = column_type(metric.column)
        if metric.op in {"sum", "avg"} and kind not in {"integer", "number"}:
            raise PlanError(f"{metric.op} requires a numeric column")
        if metric.op in {"min", "max"} and kind == "boolean":
            raise PlanError("min/max on booleans is not supported in v1")

    for condition in plan.filters:
        kind = column_type(condition.column)
        if isinstance(condition, NullCheck):
            continue
        value = condition.value
        valid = {
            "text": type(value) is str,
            "integer": type(value) is int,
            "number": type(value) in {int, float},
            "boolean": type(value) is bool,
            "date": type(value) is str,
        }[kind]
        if not valid:
            raise PlanError(f"Filter value does not match {condition.column}'s {kind} type")
        if kind == "date":
            try:
                parsed = date.fromisoformat(value)
            except ValueError as error:
                raise PlanError("Date values must be real ISO YYYY-MM-DD dates") from error
            if parsed.isoformat() != value:
                raise PlanError("Date values must use YYYY-MM-DD")
        if kind == "boolean" and condition.op not in {"eq", "ne"}:
            raise PlanError("Boolean comparisons support only eq/ne")

    outputs = set(plan.dimensions) | set(aliases)
    ordered = [item.field for item in plan.order_by]
    if len(set(ordered)) != len(ordered):
        raise PlanError("Duplicate ordering fields")
    if not set(ordered) <= outputs:
        raise PlanError("Ordering must reference a grouping column or metric alias")
    return plan
