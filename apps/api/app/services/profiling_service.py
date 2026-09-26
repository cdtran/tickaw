"""Schedule profiling with one durable job per immutable version."""
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import DatasetVersion, ProfilingJob


def enqueue_profile(session: Session, version: DatasetVersion) -> None:
    session.execute(insert(ProfilingJob).values(id=uuid4(), dataset_version_id=version.id)
                    .on_conflict_do_nothing(index_elements=["dataset_version_id"]))


def request_profile(session: Session, version_id: UUID) -> None:
    version = session.get(DatasetVersion, version_id)
    if version is None:
        raise HTTPException(404, "Dataset version not found.")
    if version.status == "READY":
        return
    if version.status not in {"UPLOADED", "PROCESSING"}:
        raise HTTPException(409, "Only stored CSV versions can be profiled. Upload a corrected version after a failure.")
    if version.file_format != "csv":
        raise HTTPException(422, "Only CSV profiling is supported.")
    enqueue_profile(session, version)
    session.commit()


def job_for_version(session: Session, version_id: UUID):
    return session.scalar(select(ProfilingJob).where(ProfilingJob.dataset_version_id == version_id))
