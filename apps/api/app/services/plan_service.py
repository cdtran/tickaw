"""Generate a validated query plan for a durable analysis run."""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import AnalysisRun, DatasetVersion, NotebookCell
from packages.data_engine.execution import catalog_from_profile
from packages.data_engine.query_plan import PlanError, QueryPlan, validate_plan
from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import PlanRequest, PlanResponse
from packages.llm_gateway.gateway import LLMGateway
from packages.llm_gateway.prompts import PROMPT_VERSION


class PlanGenerationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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
    request = PlanRequest(
        question=cell.question,
        dataset_schema=version.schema_json or {},
        dataset_profile=version.profile_json or {},
        response_schema=QueryPlan.model_json_schema(),
        prompt_version=PROMPT_VERSION,
    )
    for attempt in range(2):
        try:
            response = gateway.generate_plan(cell.stable_model_id, request)
            return validate_plan(response.payload, catalog), response
        except ModelProviderError as error:
            raise PlanGenerationError(
                "MODEL_UNAVAILABLE", "The selected model could not generate a query plan."
            ) from error
        except (ValidationError, PlanError) as error:
            if attempt == 1:
                raise PlanGenerationError(
                    "INVALID_PLAN", "The selected model could not generate a valid query plan."
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
