"""Read durable analysis-run metadata and reconstructable result artifacts."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AnalysisRun
from app.schemas.analysis import AnalysisRunResponse, ClarificationAnswer, StoredAnalysisResult
from app.services.analysis_service import answer_clarification, load_result

from app.services.auth_service import current_user
from app.services.ownership import owned_run

router = APIRouter(prefix="/analysis-runs", tags=["analysis"])


def get_run(session: Session, run_id: UUID) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    return run


@router.get("/{run_id}", response_model=AnalysisRunResponse)
def analysis_run(run_id: UUID, session: Annotated[Session, Depends(get_db)], user=Depends(current_user)):
    return owned_run(session, run_id, user.id)


@router.get("/{run_id}/result", response_model=StoredAnalysisResult)
def analysis_result(run_id: UUID, session: Annotated[Session, Depends(get_db)], user=Depends(current_user)):
    return load_result(owned_run(session, run_id, user.id))


@router.post("/{run_id}/clarification", response_model=AnalysisRunResponse, status_code=202)
def clarify_analysis(
    run_id: UUID,
    payload: ClarificationAnswer,
    session: Annotated[Session, Depends(get_db)],
    user=Depends(current_user),
):
    owned_run(session, run_id, user.id)
    return answer_clarification(session, run_id, payload.answer)
