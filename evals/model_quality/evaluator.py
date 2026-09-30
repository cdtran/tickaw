"""Provider-neutral scoring for model-quality evaluation cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from packages.data_engine.execution import catalog_from_profile
from packages.data_engine.query_plan import PlanError, validate_plan

SUITE_DIR = Path(__file__).resolve().parent
OUTCOMES = {
    "valid_plan",
    "needs_clarification",
    "invalid_model_output",
    "unanswerable_with_available_data",
    "semantically_misleading_substitution",
}


@dataclass(frozen=True)
class EvaluationResult:
    outcome: str
    reasons: tuple[str, ...] = ()


def load_suite(path: Path = SUITE_DIR / "cases.json") -> tuple[dict[str, Any], dict[str, Any]]:
    suite = json.loads(path.read_text())
    dataset = json.loads((path.parent / suite["dataset"]).read_text())
    validate_suite(suite, dataset)
    return suite, dataset


def validate_suite(suite: dict[str, Any], dataset: dict[str, Any]) -> None:
    if suite.get("suite_version") != 1:
        raise ValueError("Unsupported model-quality suite version")
    catalog_from_profile(dataset["schema"])
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("The model-quality suite must contain cases")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ValueError("Every model-quality case must have an id")
    if len(ids) != len(set(ids)):
        raise ValueError("Model-quality case ids must be unique")
    for case in cases:
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError(f"Case {case['id']} must have a question")
        if case.get("expected_outcome") not in OUTCOMES:
            raise ValueError(f"Case {case['id']} has an unsupported expected outcome")
    for fixture in suite.get("classification_fixtures", []):
        if fixture.get("expected_outcome") not in OUTCOMES:
            raise ValueError(f"Fixture {fixture.get('id')} has an unsupported expected outcome")
        if fixture.get("case_id") and fixture["case_id"] not in set(ids):
            raise ValueError(f"Fixture {fixture.get('id')} references an unknown case")


def _contains(items: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    return any(all(item.get(key) == value for key, value in expected.items()) for item in items)


def score_payload(case: dict[str, Any], payload: dict[str, Any], catalog: dict[str, str]) -> EvaluationResult:
    """Validate a plan, then score its meaning against an explicit case contract."""
    try:
        plan = validate_plan(payload, catalog)
    except (ValidationError, PlanError) as error:
        return EvaluationResult("invalid_model_output", (str(error),))

    serialized = plan.model_dump(mode="json")
    reasons: list[str] = []
    if "required_dimensions" in case and sorted(serialized["dimensions"]) != sorted(
        case["required_dimensions"]
    ):
        reasons.append(
            f"dimensions were {serialized['dimensions']!r}, expected {case['required_dimensions']!r}"
        )
    for expected in case.get("required_metrics", []):
        if not _contains(serialized["metrics"], expected):
            reasons.append(f"missing required metric {expected!r}")
    for expected in case.get("required_filters", []):
        if not _contains(serialized["filters"], expected):
            reasons.append(f"missing required filter {expected!r}")
    for expected in case.get("required_order_by", []):
        if not _contains(serialized["order_by"], expected):
            reasons.append(f"missing required ordering {expected!r}")
    if "required_limit" in case and serialized["limit"] != case["required_limit"]:
        reasons.append(f"limit was {serialized['limit']!r}, expected {case['required_limit']!r}")
    if (
        "required_presentation" in case
        and serialized["presentation"]["type"] != case["required_presentation"]
    ):
        reasons.append(
            f"presentation was {serialized['presentation']['type']!r}, "
            f"expected {case['required_presentation']!r}"
        )
    for forbidden in case.get("forbidden_metrics", []):
        if _contains(serialized["metrics"], forbidden):
            reasons.append(f"used misleading substitute metric {forbidden!r}")

    if reasons:
        return EvaluationResult("semantically_misleading_substitution", tuple(reasons))
    if case["expected_outcome"] == "valid_plan":
        return EvaluationResult("valid_plan")
    return EvaluationResult(
        "semantically_misleading_substitution",
        ("returned an executable plan for a question that requires clarification or unavailable data",),
    )


def catalog_for(dataset: dict[str, Any]) -> dict[str, str]:
    return catalog_from_profile(dataset["schema"])


def case_by_id(suite: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(case for case in suite["cases"] if case["id"] == case_id)
