"""Generate a validated query plan for a durable analysis run."""

from decimal import Decimal
from time import perf_counter

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import event
from app.models import AnalysisRun, DatasetVersion, NotebookCell
from packages.data_engine.execution import catalog_from_profile
from packages.data_engine.query_plan import PlanError, QueryPlan, validate_plan
from packages.data_engine.question_semantics import (
    check_question_meaning,
    concept_columns,
    requested_concepts,
)
from packages.data_engine.temporal import parse_temporal
from packages.llm_gateway.adapters.openai import PaidRunBlocked
from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import PlanRequest, PlanResponse
from packages.llm_gateway.gateway import LLMGateway
from packages.llm_gateway.prompts import PROMPT_VERSION


class PlanGenerationError(Exception):
    def __init__(self, code: str, message: str, diagnostics: list[dict] | None = None):
        self.code = code
        self.diagnostics = diagnostics or []
        super().__init__(message)


def safe_validation_diagnostic(error: ValidationError | PlanError) -> dict:
    """Return bounded, display-safe facts without retaining model-authored plan JSON."""
    if isinstance(error, PlanError):
        diagnostic = {"code": error.code}
        for key, value in list(error.details.items())[:8]:
            if isinstance(value, str):
                diagnostic[key] = value[:128]
            elif type(value) in {int, bool}:
                diagnostic[key] = value
            elif isinstance(value, list):
                diagnostic[key] = [str(item)[:64] for item in value[:8]]
        if not error.details:
            diagnostic["message"] = str(error)[:300]
        return diagnostic
    issues = []
    for item in error.errors(include_url=False, include_context=False)[:8]:
        issues.append(
            {
                "path": ".".join(str(part) for part in item["loc"])[:200],
                "type": str(item["type"])[:100],
                "message": str(item["msg"])[:300],
            }
        )
    return {"code": "MALFORMED_PLAN", "issues": issues}


def missing_data_clarification(
    diagnostics: list[dict], question: str = "", catalog: dict[str, str] | None = None
) -> str | None:
    missing = sorted({item["column"] for item in diagnostics if item["code"] == "UNKNOWN_COLUMN"})
    if missing:
        names = ", ".join(f"“{name}”" for name in missing[:4])
        return (
            f"This dataset does not contain the field {names}. Which available field should be "
            "used instead, or how should it be calculated from the available fields?"
        )
    concepts = requested_concepts(question)
    if concepts and catalog is not None:
        unavailable = sorted(
            concept for concept in concepts if not concept_columns(concept, catalog)
        )
        if unavailable and any(
            item["code"] in {"METRIC_TYPE_MISMATCH", "MISSING_MEASURE", "SEMANTIC_SUBSTITUTION"}
            for item in diagnostics
        ):
            concept = unavailable[0]
            return (
                f"This dataset does not contain a recognized {concept} field. Which available "
                "field should be used instead, or how should it be calculated?"
            )
    return None


def temporal_text_columns(profile: dict, catalog: dict[str, str]) -> set[str]:
    """Recognize legacy profiled text columns whose samples are unambiguous ISO temporal values."""
    eligible = set()
    for column in profile.get("columns", []):
        name = column.get("name")
        values = column.get("sample_values", [])
        if catalog.get(name) != "text" or not values:
            continue
        try:
            kinds = {parse_temporal(value)[0] for value in values}
        except (TypeError, ValueError, OverflowError):
            continue
        if len(kinds) == 1:
            eligible.add(name)
    return eligible


def normalize_presentation(
    payload: dict, catalog: dict[str, str], line_eligible_text_columns: set[str]
) -> dict:
    """Correct only a chart-kind mismatch; never change query semantics."""
    dimensions = payload.get("dimensions")
    presentation = payload.get("presentation")
    if (
        isinstance(dimensions, list)
        and len(dimensions) == 1
        and isinstance(presentation, dict)
        and presentation.get("type") == "line"
        and catalog.get(dimensions[0]) not in {"date", "timestamp", "timestamp_tz"}
        and dimensions[0] not in line_eligible_text_columns
    ):
        return {**payload, "presentation": {**presentation, "type": "bar"}}
    return payload


def estimated_response_cost(response: PlanResponse) -> float | None:
    usage = response.usage
    if response.provider != "openai" or any(
        type(value) is not int or value < 0 for value in (usage.input_tokens, usage.output_tokens)
    ):
        return None
    settings = get_settings()
    if settings.openai_input_rate is None or settings.openai_output_rate is None:
        return None
    return float(
        (
            Decimal(usage.input_tokens) * Decimal(str(settings.openai_input_rate))
            + Decimal(usage.output_tokens) * Decimal(str(settings.openai_output_rate))
        )
        / Decimal(1_000_000)
    )


def generate_plan(
    session: Session,
    run: AnalysisRun,
    gateway: LLMGateway,
) -> tuple[QueryPlan, PlanResponse]:
    cell = session.get(NotebookCell, run.notebook_cell_id)
    version = session.get(DatasetVersion, run.dataset_version_id)
    if cell is None or version is None or version.status != "READY":
        raise PlanGenerationError(
            "SOURCE_UNAVAILABLE", "The question's dataset version is not ready for analysis."
        )
    try:
        catalog = catalog_from_profile(version.schema_json or {})
    except ValueError as error:
        raise PlanGenerationError(
            "INVALID_SCHEMA", "The pinned dataset schema is invalid."
        ) from error
    line_eligible = temporal_text_columns(version.profile_json or {}, catalog)
    request = PlanRequest(
        question=(
            cell.question
            if not run.clarification_answer
            else f"{cell.question}\n\nUser clarification: {run.clarification_answer}"
        ),
        dataset_schema=version.schema_json or {},
        dataset_profile=version.profile_json or {},
        response_schema=QueryPlan.model_json_schema(),
        prompt_version=PROMPT_VERSION,
    )
    diagnostics: list[dict] = []
    for attempt in range(2):
        started = perf_counter()
        try:
            response = gateway.generate_plan(cell.stable_model_id, request)
            event(
                "model.completed",
                run_id=run.id,
                model_id=cell.stable_model_id,
                provider=response.provider,
                prompt_version=PROMPT_VERSION,
                generation_attempt=attempt + 1,
                duration_ms=(perf_counter() - started) * 1000,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                estimated_response_cost_usd=estimated_response_cost(response),
            )
            normalized = normalize_presentation(response.payload, catalog, line_eligible)
            plan = validate_plan(normalized, catalog)
            meaning_issue = check_question_meaning(
                cell.question,
                plan,
                catalog,
                clarification=run.clarification_answer,
            )
            if meaning_issue:
                raise PlanError(
                    meaning_issue.message,
                    code=meaning_issue.code,
                    details=meaning_issue.diagnostic() | {"message": meaning_issue.message},
                )
            event(
                "plan.accepted",
                run_id=run.id,
                generation_attempt=attempt + 1,
                correction=attempt > 0,
            )
            return plan, response
        except ModelProviderError as error:
            event(
                "model.failed",
                run_id=run.id,
                model_id=cell.stable_model_id,
                generation_attempt=attempt + 1,
                duration_ms=(perf_counter() - started) * 1000,
                error_code="POLICY_BLOCKED"
                if isinstance(error, PaidRunBlocked)
                else "MODEL_UNAVAILABLE",
            )
            raise PlanGenerationError(
                "MODEL_UNAVAILABLE", "The selected model could not generate a query plan."
            ) from error
        except (ValidationError, PlanError) as error:
            diagnostic = safe_validation_diagnostic(error)
            event(
                "plan.rejected",
                run_id=run.id,
                generation_attempt=attempt + 1,
                error_code=diagnostic["code"],
            )
            diagnostics.append(diagnostic)
            if attempt == 1:
                clarification = missing_data_clarification(diagnostics, cell.question, catalog)
                if clarification:
                    raise PlanGenerationError(
                        "UNANSWERABLE_WITH_DATA",
                        clarification,
                        diagnostics,
                    ) from error
                raise PlanGenerationError(
                    "INVALID_PLAN",
                    "The selected model returned malformed or unsupported query instructions.",
                    diagnostics,
                ) from error
            request = request.model_copy(
                update={
                    "validation_feedback": (
                        f"The previous query plan was rejected: {error}. "
                        "Return a corrected complete query plan."
                    )
                }
            )
    raise PlanGenerationError("INVALID_PLAN", "No query plan was generated.")
