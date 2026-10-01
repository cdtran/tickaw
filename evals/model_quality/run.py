"""Run the model-quality corpus against the configured live model.

Invoke from the repository root with:
    docker compose run --rm api python -m evals.model_quality.run
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.services.llm_service import get_llm_gateway, get_model_registry
from app.services.plan_service import missing_data_clarification, safe_validation_diagnostic
from pydantic import ValidationError

from evals.model_quality.evaluator import EvaluationResult, catalog_for, load_suite, score_payload
from evals.model_quality.recording import RecordingGateway
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
        except ModelProviderError:
            return EvaluationResult("provider_runtime_failure", ("PROVIDER_ERROR",))
        try:
            plan = validate_plan(response.payload, catalog)
        except (ValidationError, PlanError) as error:
            diagnostics.append(safe_validation_diagnostic(error))
            if attempt == 0:
                request = request.model_copy(
                    update={
                        "validation_feedback": (
                            f"The previous query plan was rejected: {error}. "
                            "Return a corrected complete query plan."
                        )
                    }
                )
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


def run(
    model_id: str,
    suite_path: Path,
    case_ids: set[str] | None = None,
    *,
    tier="full",
    report_path: Path | None = None,
    cache_dir: Path | None = Path("artifacts/model-quality/cache"),
    refresh=False,
    input_rate: float | None = None,
    output_rate: float | None = None,
) -> int:
    suite, dataset = load_suite(suite_path)
    gateway = get_llm_gateway()
    catalog = catalog_for(dataset)
    route = gateway.registry.resolve(model_id)
    unknown = (case_ids or set()) - {case["id"] for case in suite["cases"]}
    if unknown:
        raise ValueError(f"Unknown evaluation case ids: {', '.join(sorted(unknown))}")
    cases = [
        case
        for case in suite["cases"]
        if (case["id"] in case_ids if case_ids else tier in case["tags"])
    ]
    if not cases:
        raise ValueError("No evaluation cases selected")
    records = []
    failures = 0
    for case in cases:
        recorder = RecordingGateway(gateway, case, dataset, cache_dir, refresh)
        result = evaluate_case(recorder, model_id, case, dataset, catalog)
        passed = result.outcome == case["expected_outcome"]
        failures += not passed
        input_tokens = recorder.tokens(recorder.input_tokens)
        output_tokens = recorder.tokens(recorder.output_tokens)
        cost = None
        if (
            input_rate is not None
            and output_rate is not None
            and input_tokens is not None
            and output_tokens is not None
        ):
            cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
        record = {
            "id": case["id"],
            "passed": passed,
            "expected": case["expected_outcome"],
            "actual": result.outcome,
            "reasons": result.reasons,
            "failure_category": None
            if passed
            else (
                "provider_runtime_failure"
                if result.outcome == "provider_runtime_failure"
                else "model_failure"
            ),
            "model_id": model_id,
            "provider": route.provider,
            "provider_model": route.provider_model,
            "prompt_version": PROMPT_VERSION,
            "suite_version": suite["suite_version"],
            "suite_revision": suite.get("revision"),
            "attempt_count": recorder.attempts,
            "cache_hits": recorder.cache_hits,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_seconds": round(recorder.duration_seconds, 4),
            "estimated_response_cost_usd": cost,
            "cost_rates_usd_per_million": {"input": input_rate, "output": output_rate},
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    summary = {
        "model": model_id,
        "cases": len(cases),
        "failures": failures,
        "created_at": datetime.now(UTC).isoformat(),
        "tier": tier,
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"summary": summary, "cases": records}, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live model-quality evaluations")
    parser.add_argument(
        "--model", default=None, help="Stable model id (defaults to configured first model)"
    )
    parser.add_argument("--suite", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument(
        "--case", action="append", dest="case_ids", help="Run one case id; repeatable"
    )
    parser.add_argument("--tier", choices=["smoke", "full", "release"], default="full")
    parser.add_argument("--report", type=Path, default=Path("artifacts/model-quality/latest.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("artifacts/model-quality/cache"))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--input-rate", type=float, help="USD per million input tokens")
    parser.add_argument("--output-rate", type=float, help="USD per million output tokens")
    args = parser.parse_args()
    if any(rate is not None and rate < 0 for rate in [args.input_rate, args.output_rate]):
        parser.error("Token prices cannot be negative")
    model_id = args.model or get_model_registry().available()[0].id
    raise SystemExit(
        run(
            model_id,
            args.suite,
            set(args.case_ids) if args.case_ids else None,
            tier=args.tier,
            report_path=args.report,
            cache_dir=None if args.no_cache else args.cache_dir,
            refresh=args.refresh,
            input_rate=args.input_rate,
            output_rate=args.output_rate,
        )
    )


if __name__ == "__main__":
    main()
