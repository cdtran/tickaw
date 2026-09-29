"""Submit a persisted question and server-owned dataset metadata to the LLM gateway."""

from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import AnalysisRun, DatasetVersion, NotebookCell
from app.services.analysis_service import create_run
from packages.data_engine.execution import catalog_from_profile
from packages.data_engine.query_plan import PlanError, QueryPlan, validate_plan
from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import PlanRequest
from packages.llm_gateway.gateway import LLMGateway
from packages.llm_gateway.prompts import PROMPT_VERSION


def generate_draft(
    session: Session,
    notebook_id: UUID,
    cell_id: UUID,
    gateway: LLMGateway,
) -> AnalysisRun:
    cell = session.get(NotebookCell, cell_id)
    if cell is None or cell.notebook_id != notebook_id:
        raise HTTPException(404, "Notebook cell not found.")
    version = session.get(DatasetVersion, cell.dataset_version_id)
    if version is None or version.status != "READY":
        raise HTTPException(409, "The question's dataset version is not ready for analysis.")
    try:
        catalog = catalog_from_profile(version.schema_json or {})
    except ValueError as error:
        raise HTTPException(500, "The pinned dataset schema is invalid.") from error
    request = PlanRequest(
        question=cell.question,
        dataset_schema=version.schema_json or {},
        dataset_profile=version.profile_json or {},
        response_schema=QueryPlan.model_json_schema(),
        prompt_version=PROMPT_VERSION,
    )
    response = None
    plan = None
    for attempt in range(2):
        try:
            response = gateway.generate_plan(cell.stable_model_id, request)
            plan = validate_plan(response.payload, catalog)
            break
        except ModelProviderError as error:
            raise HTTPException(
                502, "The selected model could not generate a valid query plan."
            ) from error
        except (ValidationError, PlanError) as error:
            if attempt == 1:
                raise HTTPException(
                    502, "The selected model could not generate a valid query plan."
                ) from error
            request = request.model_copy(
                update={
                    "validation_feedback": (
                        f"The previous query plan was rejected: {error}. "
                        "Return a corrected complete query plan."
                    )
                }
            )
    if response is None or plan is None:  # Defensive; the loop returns or assigns both.
        raise HTTPException(
            502, "The selected model could not generate a valid query plan."
        )
    return create_run(
        session,
        cell.id,
        plan,
        stable_model_id=response.stable_model_id,
        prompt_version=response.prompt_version,
    )
