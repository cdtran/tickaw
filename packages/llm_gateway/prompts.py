"""Versioned analysis prompt templates."""

import json

from packages.llm_gateway.contracts import PlanRequest

PROMPT_VERSION = "query-plan-v2.3"


def system_prompt() -> str:
    return (
        "You translate a user's data question into query plan v2 JSON. "
        "Use only columns present in the trusted dataset schema. Never emit SQL, code, "
        "markdown, or explanatory prose. The response must match the supplied JSON Schema. "
        "Use table for scalar answers or answers without exactly one grouping dimension. "
        "Use line for one temporal grouping dimension and numeric metrics. "
        "Use bar for one non-temporal grouping dimension and numeric metrics. "
        "Words such as 'by', 'per', and 'for each' identify a grouping dimension; include "
        "the referenced dataset column in dimensions."
    )


def user_prompt(request: PlanRequest) -> str:
    trusted_context = {
        "question": request.question,
        "dataset_schema": request.dataset_schema,
        "dataset_profile": request.dataset_profile,
    }
    if request.validation_feedback:
        trusted_context["validation_feedback"] = request.validation_feedback
    return json.dumps(trusted_context, ensure_ascii=False, separators=(",", ":"))
