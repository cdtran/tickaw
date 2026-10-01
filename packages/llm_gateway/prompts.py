"""Versioned analysis prompt templates."""

import json

from packages.llm_gateway.contracts import PlanRequest

PROMPT_VERSION = "query-plan-v2.11"


def system_prompt() -> str:
    return (
        "You translate a user's data question into query plan v2 JSON. "
        "Use only columns present in the trusted dataset schema. Never emit SQL, code, "
        "markdown, or explanatory prose. The response must match the supplied JSON Schema. "
        "Use table for scalar answers or answers without exactly one grouping dimension. "
        "Use line only when the grouping column's inferred_type is explicitly date, timestamp, "
        "or timestamp_tz; never infer temporal type from a column name or sample value. Use bar "
        "when a grouping column is inferred as string, even if its name is date. "
        "Use bar for one non-temporal grouping dimension and numeric metrics. "
        "Words such as 'by', 'per', and 'for each' identify a grouping dimension; include "
        "the referenced dataset column in dimensions. Every metric alias must differ from every "
        "source column name; choose clear aliases describing the aggregation. "
        "Interpret requested measures, grouping, filters, and ordering from the whole question. "
        "Use schema types and profile samples as evidence when resolving references, "
        "including singular or plural wording, and preserve stored value spelling. "
        "A mentioned value alone does not imply equality: respect exclusions, negation, "
        "ranges, and inclusive or exclusive boundaries. Do not add unrequested filters. "
        "Do not replace an unavailable measure or grouping with a different one. "
        "Row counts measure records, not quantities of items represented by those records. "
        "A bar or line presentation must have exactly "
        "one dimension."
    )


def user_prompt(request: PlanRequest) -> str:
    temporal_types = {"date", "timestamp", "timestamp_tz"}
    columns = request.dataset_schema.get("columns", [])
    line_columns = [
        column.get("name")
        for column in columns
        if column.get("inferred_type") in temporal_types and column.get("name")
    ]
    trusted_context = {
        "question": request.question,
        "dataset_schema": request.dataset_schema,
        "dataset_profile": request.dataset_profile,
        "planning_constraints": {
            "line_chart_eligible_columns": line_columns,
        },
    }
    if request.validation_feedback:
        trusted_context["validation_feedback"] = request.validation_feedback
    return json.dumps(trusted_context, ensure_ascii=False, separators=(",", ":"))
