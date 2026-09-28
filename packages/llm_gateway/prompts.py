"""Versioned analysis prompt templates."""

import json

from packages.llm_gateway.contracts import PlanRequest

PROMPT_VERSION = "query-plan-v2.1"


def system_prompt() -> str:
    return (
        "You translate a user's data question into query plan v2 JSON. "
        "Use only columns present in the trusted dataset schema. Never emit SQL, code, "
        "markdown, or explanatory prose. The response must match the supplied JSON Schema."
    )


def user_prompt(request: PlanRequest) -> str:
    trusted_context = {
        "question": request.question,
        "dataset_schema": request.dataset_schema,
        "dataset_profile": request.dataset_profile,
    }
    return json.dumps(trusted_context, ensure_ascii=False, separators=(",", ":"))
