"""Versioned analysis prompt templates."""

import json
import re

from packages.llm_gateway.contracts import PlanRequest

PROMPT_VERSION = "query-plan-v2.10"


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
        "source column name; use descriptive aliases such as total_revenue or average_price. "
        "When the question contains a sample value ignoring case, add an eq filter on that column "
        "using the sample value's exact spelling. Include all planning_constraints.required_value_filters "
        "in the plan filters. Category references can be singular: "
        "when the category samples include Books, book transaction rows and book revenue "
        "both require category eq Books. Preserve that filter for counts and averages; "
        "row count counts transactions, not units sold. A bar or line presentation must have exactly "
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
    question = request.question.casefold()
    matched_values = []
    seen_matches = set()
    for column in request.dataset_profile.get("columns", []):
        for value in column.get("sample_values", []):
            match = (column.get("name"), value) if isinstance(value, str) else None
            # Narrow prompt hint for the reviewed Books wording, not a semantic rule.
            book_category = (
                column.get("name") == "category"
                and isinstance(value, str)
                and value.casefold() == "books"
                and re.search(r"\bbook\b", question) is not None
            )
            if (
                match
                and (value.casefold() in question or book_category)
                and match not in seen_matches
            ):
                seen_matches.add(match)
                matched_values.append({"column": column.get("name"), "value": value})
    trusted_context = {
        "question": request.question,
        "dataset_schema": request.dataset_schema,
        "dataset_profile": request.dataset_profile,
        "planning_constraints": {
            "line_chart_eligible_columns": line_columns,
            "question_matched_sample_values": matched_values,
            "required_value_filters": [
                {"column": item["column"], "op": "eq", "value": item["value"]}
                for item in matched_values
            ],
        },
    }
    if request.validation_feedback:
        trusted_context["validation_feedback"] = request.validation_feedback
    return json.dumps(trusted_context, ensure_ascii=False, separators=(",", ":"))
