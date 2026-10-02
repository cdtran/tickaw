"""Create and reopen notebooks and persist question cells."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Notebook
from app.schemas.analysis import AnalysisRunResponse
from app.schemas.notebook import (
    CellResponse,
    NotebookCreate,
    NotebookDetail,
    NotebookResponse,
    QuestionCreate,
)
from app.services import notebook_service
from app.services.analysis_service import create_run

from app.services.auth_service import current_user
from app.services.ownership import owned, owned_version

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


@router.get("", response_model=list[NotebookResponse])
def list_notebooks(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session: Session = Depends(get_db), user=Depends(current_user)):
    return session.scalars(select(Notebook).where(Notebook.owner_id == user.id).order_by(Notebook.updated_at.desc(), Notebook.id)
                           .offset(offset).limit(limit)).all()


@router.post("", response_model=NotebookResponse, status_code=201)
def create_notebook(request: NotebookCreate, session: Session = Depends(get_db), user=Depends(current_user)):
    notebook = Notebook(title=request.title, owner_id=user.id)
    session.add(notebook)
    session.commit()
    session.refresh(notebook)
    return notebook


@router.get("/{notebook_id}", response_model=NotebookDetail)
def get_notebook(notebook_id: UUID, session: Session = Depends(get_db), user=Depends(current_user)):
    owned(session, Notebook, notebook_id, user.id)
    return notebook_service.detail(session, notebook_id)


@router.post("/{notebook_id}/cells", response_model=CellResponse, status_code=201)
def add_question(
    notebook_id: UUID,
    request: QuestionCreate,
    session: Session = Depends(get_db),
    user=Depends(current_user),
    idempotency_key: UUID | None = Header(None, alias="Idempotency-Key"),
):
    owned(session, Notebook, notebook_id, user.id)
    owned_version(session, request.dataset_version_id, user.id)
    return notebook_service.add_question(session, notebook_id, request, idempotency_key)


@router.post(
    "/{notebook_id}/cells/{cell_id}/analysis-runs",
    response_model=AnalysisRunResponse,
    status_code=202,
)
def draft_plan(
    notebook_id: UUID,
    cell_id: UUID,
    session: Session = Depends(get_db),
    user=Depends(current_user),
):
    owned(session, Notebook, notebook_id, user.id)
    cell = notebook_service.get_cell(session, notebook_id, cell_id)
    owned_version(session, cell.dataset_version_id, user.id)
    return create_run(session, cell.id)
