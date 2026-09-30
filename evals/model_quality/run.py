"""Run the model-quality corpus against the configured live model.

Invoke from the repository root with:
    docker compose run --rm api python -m evals.model_quality.run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.llm_service import get_llm_gateway, get_model_registry
from app.services.plan_service import missing_data_clarification, safe_validation_diagnostic
from pydantic import ValidationError

from evals.model_quality.evaluator import EvaluationResult, catalog_for, load_suite, score_payload
from packages.data_engine.query_plan import PlanError, QueryPlan, validate_plan
from packages.data_engine.question_semantics import check_question_meaning
from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import PlanRequest
from packages.llm_gateway.prompts import PROMPT_VERSION


def evaluate_case(gateway, model_id, case, dataset, catalog) -> EvaluationResult:
    request = PlanRequest(
        question=case["question"],
        dataset_schema=dataset["schema"],
        dataset_profile=dataset["profile"],
        response_schema=QueryPlan.model_json_schema(),
        prompt_version=PROMPT_VERSION,
    )
    diagnostics = []
    for attempt in range(2):
        try:
            response = gateway.generate_plan(model_id, request)
        except ModelProviderError as error:
            return EvaluationResult("invalid_model_output", (f"provider error: {error}",))
        try:
            plan = validate_plan(response.payload, catalog)
        except (ValidationError, PlanError) as error:
            diagnostics.append(safe_validation_diagnostic(error))
            if attempt == 0:
                request = request.model_copy(update={
                    "validation_feedback": (
                        f"The previous query plan was rejected: {error}. "
                        "Return a corrected complete query plan."
                    )
                })
                continue
            if missing_data_clarification(diagnostics, case["question"], catalog):
                outcome = (
                    "unanswerable_with_available_data"
                    if case["expected_outcome"] == "unanswerable_with_available_data"
                    else "needs_clarification"
                )
                return EvaluationResult(outcome, tuple(item["code"] for item in diagnostics))
            return EvaluationResult(
                "invalid_model_output", tuple(item["code"] for item in diagnostics)
            )
        meaning_issue = check_question_meaning(case["question"], plan, catalog)
        if meaning_issue:
            outcome = (
                "unanswerable_with_available_data"
                if case["expected_outcome"] == "unanswerable_with_available_data"
                else "needs_clarification"
            )
            return EvaluationResult(outcome, (meaning_issue.code,))
        return score_payload(case, response.payload, catalog)
    raise AssertionError("evaluation attempts exhausted")


def run(model_id: str, suite_path: Path, case_ids: set[str] | None = None) -> int:
    suite, dataset = load_suite(suite_path)
    gateway = get_llm_gateway()
    catalog = catalog_for(dataset)
    cases = [case for case in suite["cases"] if not case_ids or case["id"] in case_ids]
    unknown = (case_ids or set()) - {case["id"] for case in cases}
    if unknown:
        raise ValueError(f"Unknown evaluation case ids: {', '.join(sorted(unknown))}")
    failures = 0
    for case in cases:
        result = evaluate_case(gateway, model_id, case, dataset, catalog)
        passed = result.outcome == case["expected_outcome"]
        failures += not passed
        print(json.dumps({
            "id": case["id"],
            "passed": passed,
            "expected": case["expected_outcome"],
            "actual": result.outcome,
            "reasons": result.reasons,
        }, ensure_ascii=False))
    print(json.dumps({"model": model_id, "cases": len(cases), "failures": failures}))
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live model-quality evaluations")
    parser.add_argument("--model", default=None, help="Stable model id (defaults to configured first model)")
    parser.add_argument("--suite", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--case", action="append", dest="case_ids", help="Run one case id; repeatable")
    args = parser.parse_args()
    model_id = args.model or get_model_registry().available()[0].id
    raise SystemExit(run(model_id, args.suite, set(args.case_ids) if args.case_ids else None))


if __name__ == "__main__":
    main()
