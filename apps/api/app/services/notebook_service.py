"""Persist notebook questions and their queued analysis runs atomically."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnalysisRun, DatasetVersion, Notebook, NotebookCell
from app.schemas.analysis import AnalysisRunSummary
from app.schemas.notebook import CellResponse, NotebookDetail, QuestionCreate
from app.services.analysis_queue import enqueue_run
from app.services.analysis_service import queued_run_for_cell
from app.services.llm_service import get_model_registry
from packages.llm_gateway.registry import UnknownModelError


def get_notebook(session: Session, notebook_id: UUID) -> Notebook:
    notebook = session.get(Notebook, notebook_id)
    if notebook is None:
        raise HTTPException(404, "Notebook not found.")
    return notebook


def get_cell(session: Session, notebook_id: UUID, cell_id: UUID) -> NotebookCell:
    cell = session.get(NotebookCell, cell_id)
    if cell is None or cell.notebook_id != notebook_id:
        raise HTTPException(404, "Notebook cell not found.")
    return cell


def detail(session: Session, notebook_id: UUID) -> NotebookDetail:
    notebook = get_notebook(session, notebook_id)
    cells = session.scalars(
        select(NotebookCell)
        .where(NotebookCell.notebook_id == notebook_id)
        .order_by(NotebookCell.created_at, NotebookCell.id)
    ).all()
    latest = {}
    if cells:
        runs = session.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.notebook_cell_id.in_([cell.id for cell in cells]))
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        ).all()
        for run in runs:
            latest.setdefault(run.notebook_cell_id, run)
    return NotebookDetail(
        id=notebook.id,
        title=notebook.title,
        created_at=notebook.created_at,
        updated_at=notebook.updated_at,
        cells=[
            CellResponse.model_validate(cell).model_copy(
                update={
                    "latest_analysis": AnalysisRunSummary.model_validate(latest[cell.id])
                    if cell.id in latest
                    else None
                }
            )
            for cell in cells
        ],
    )


def add_question(session: Session, notebook_id: UUID, request: QuestionCreate) -> CellResponse:
    notebook = get_notebook(session, notebook_id)
    version = session.get(DatasetVersion, request.dataset_version_id)
    if version is None:
        raise HTTPException(404, "Dataset version not found.")
    if version.status != "READY":
        raise HTTPException(409, "Choose a dataset version that has finished profiling (READY).")
    try:
        get_model_registry().resolve(request.stable_model_id)
    except UnknownModelError as error:
        raise HTTPException(422, str(error)) from error
    cell = NotebookCell(
        notebook_id=notebook.id,
        dataset_version_id=version.id,
        question=request.question,
        stable_model_id=request.stable_model_id,
    )
    session.add(cell)
    session.flush()
    run = queued_run_for_cell(cell)
    session.add(run)
    notebook.updated_at = func.now()
    session.commit()
    enqueue_run(run.id)
    session.refresh(cell)
    session.refresh(run)
    return CellResponse.model_validate(cell).model_copy(
        update={"latest_analysis": AnalysisRunSummary.model_validate(run)}
    )
