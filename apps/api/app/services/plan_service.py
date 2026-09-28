"""Submit a persisted question and server-owned dataset metadata to the LLM gateway."""

from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import DatasetVersion, NotebookCell
from app.schemas.model import PlanDraftResponse
from packages.data_engine.query_plan import QueryPlan
from packages.llm_gateway.adapters.openai_compatible import ModelProviderError
from packages.llm_gateway.contracts import PlanRequest
from packages.llm_gateway.gateway import LLMGateway
from packages.llm_gateway.prompts import PROMPT_VERSION


def generate_draft(
    session: Session,
    notebook_id: UUID,
    cell_id: UUID,
    gateway: LLMGateway,
) -> PlanDraftResponse:
    cell = session.get(NotebookCell, cell_id)
    if cell is None or cell.notebook_id != notebook_id:
        raise HTTPException(404, "Notebook cell not found.")
    version = session.get(DatasetVersion, cell.dataset_version_id)
    if version is None or version.status != "READY":
        raise HTTPException(409, "The question's dataset version is not ready for analysis.")
    try:
        response = gateway.generate_plan(
            cell.stable_model_id,
            PlanRequest(
                question=cell.question,
                dataset_schema=version.schema_json or {},
                dataset_profile=version.profile_json or {},
                response_schema=QueryPlan.model_json_schema(),
                prompt_version=PROMPT_VERSION,
            ),
        )
        # This is structural validation only. Dataset-catalog semantic validation remains
        # the next orchestration boundary and no draft is persisted or executed here.
        plan = QueryPlan.model_validate(response.payload)
    except (ModelProviderError, ValidationError) as error:
        raise HTTPException(
            502, "The selected model could not generate a valid query plan."
        ) from error
    return PlanDraftResponse(
        plan=plan.model_dump(mode="json"),
        stable_model_id=response.stable_model_id,
        provider=response.provider,
        provider_model=response.provider_model,
        prompt_version=response.prompt_version,
    )
