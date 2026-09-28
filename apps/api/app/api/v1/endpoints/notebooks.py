"""Create and reopen notebooks and persist question cells."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Notebook
from app.schemas.model import PlanDraftResponse
from app.schemas.notebook import (
    CellResponse,
    NotebookCreate,
    NotebookDetail,
    NotebookResponse,
    QuestionCreate,
)
from app.services import notebook_service
from app.services.llm_service import get_llm_gateway
from app.services.plan_service import generate_draft
from packages.llm_gateway.gateway import LLMGateway

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


@router.get("", response_model=list[NotebookResponse])
def list_notebooks(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session: Session = Depends(get_db)):
    return session.scalars(select(Notebook).order_by(Notebook.updated_at.desc(), Notebook.id)
                           .offset(offset).limit(limit)).all()


@router.post("", response_model=NotebookResponse, status_code=201)
def create_notebook(request: NotebookCreate, session: Session = Depends(get_db)):
    notebook = Notebook(title=request.title)
    session.add(notebook)
    session.commit()
    session.refresh(notebook)
    return notebook


@router.get("/{notebook_id}", response_model=NotebookDetail)
def get_notebook(notebook_id: UUID, session: Session = Depends(get_db)):
    return notebook_service.detail(session, notebook_id)


@router.post("/{notebook_id}/cells", response_model=CellResponse, status_code=201)
def add_question(notebook_id: UUID, request: QuestionCreate, session: Session = Depends(get_db)):
    return notebook_service.add_question(session, notebook_id, request)


@router.post("/{notebook_id}/cells/{cell_id}/plan", response_model=PlanDraftResponse)
def draft_plan(
    notebook_id: UUID,
    cell_id: UUID,
    session: Session = Depends(get_db),
    gateway: LLMGateway = Depends(get_llm_gateway),
):
    return generate_draft(session, notebook_id, cell_id, gateway)
