"""Generate a validated query plan for a durable analysis run."""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import AnalysisRun, DatasetVersion, NotebookCell
from packages.data_engine.execution import catalog_from_profile
from packages.data_engine.query_plan import PlanError, QueryPlan, validate_plan
from packages.data_engine.question_semantics import (
    check_question_meaning,
    concept_columns,
    requested_concepts,
)
from packages.data_engine.temporal import parse_temporal
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
        issues.append({
            "path": ".".join(str(part) for part in item["loc"])[:200],
            "type": str(item["type"])[:100],
            "message": str(item["msg"])[:300],
        })
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
            concept
            for concept in concepts
            if not concept_columns(concept, catalog)
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
        try:
            response = gateway.generate_plan(cell.stable_model_id, request)
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
            return plan, response
        except ModelProviderError as error:
            raise PlanGenerationError(
                "MODEL_UNAVAILABLE", "The selected model could not generate a query plan."
            ) from error
        except (ValidationError, PlanError) as error:
            diagnostics.append(safe_validation_diagnostic(error))
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
