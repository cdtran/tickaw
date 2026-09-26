"""Short transactions for notebook persistence; no analysis is scheduled yet."""
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models import Notebook, NotebookCell, DatasetVersion
from app.schemas.notebook import NotebookDetail, CellResponse, QuestionCreate


def get_notebook(session: Session, notebook_id: UUID) -> Notebook:
    notebook = session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(404, "Notebook not found.")
    return notebook


def detail(session: Session, notebook_id: UUID) -> NotebookDetail:
    notebook = get_notebook(session, notebook_id)
    cells = session.scalars(select(NotebookCell).where(NotebookCell.notebook_id == notebook_id)
                            .order_by(NotebookCell.created_at, NotebookCell.id)).all()
    return NotebookDetail(id=notebook.id, title=notebook.title, created_at=notebook.created_at,
                          updated_at=notebook.updated_at,
                          cells=[CellResponse.model_validate(cell) for cell in cells])


def add_question(session: Session, notebook_id: UUID, request: QuestionCreate) -> NotebookCell:
    notebook = get_notebook(session, notebook_id)
    version = session.get(DatasetVersion, request.dataset_version_id)
    if version is None:
        raise HTTPException(404, "Dataset version not found.")
    if version.status != "READY":
        raise HTTPException(409, "Choose a dataset version that has finished profiling (READY).")
    cell = NotebookCell(notebook_id=notebook.id, dataset_version_id=version.id, question=request.question)
    session.add(cell)
    notebook.updated_at = func.now()
    session.commit()
    session.refresh(cell)
    return cell
