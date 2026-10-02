"""Resource ownership is checked before data or worker actions are exposed."""

from fastapi import HTTPException

from app.models import AnalysisRun, Dataset, DatasetVersion, Notebook, NotebookCell


def owned(session, model, identity, user_id):
    resource = session.get(model, identity)
    if resource is None or resource.owner_id != user_id:
        raise HTTPException(404, "Resource not found.")
    return resource


def owned_version(session, identity, user_id):
    version = session.get(DatasetVersion, identity)
    if version is None:
        raise HTTPException(404, "Resource not found.")
    owned(session, Dataset, version.dataset_id, user_id)
    return version


def owned_run(session, identity, user_id):
    run = session.get(AnalysisRun, identity)
    cell = session.get(NotebookCell, run.notebook_cell_id) if run else None
    if cell is None:
        raise HTTPException(404, "Resource not found.")
    owned(session, Notebook, cell.notebook_id, user_id)
    owned_version(session, cell.dataset_version_id, user_id)
    owned_version(session, run.dataset_version_id, user_id)
    return run
