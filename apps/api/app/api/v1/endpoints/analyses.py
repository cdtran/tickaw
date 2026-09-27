"""Read durable analysis-run metadata and reconstructable result artifacts."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AnalysisRun
from app.schemas.analysis import AnalysisRunResponse, StoredAnalysisResult
from app.services.analysis_service import load_result

router = APIRouter(prefix="/analysis-runs", tags=["analysis"])


def get_run(session: Session, run_id: UUID) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    return run


@router.get("/{run_id}", response_model=AnalysisRunResponse)
def analysis_run(run_id: UUID, session: Annotated[Session, Depends(get_db)]):
    return get_run(session, run_id)


@router.get("/{run_id}/result", response_model=StoredAnalysisResult)
def analysis_result(run_id: UUID, session: Annotated[Session, Depends(get_db)]):
    return load_result(get_run(session, run_id))
