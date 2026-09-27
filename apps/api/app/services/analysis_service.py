"""Durable analysis-run state and bounded Postgres result persistence."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisRun, DatasetVersion, NotebookCell
from app.schemas.analysis import StoredAnalysisResult
from packages.charting.specs import chart_spec_for
from packages.data_engine.query_plan import QueryPlan
from packages.data_engine.result_types import ExecutionSuccess

MAX_STORED_RESULT_BYTES = 2 * 1024**2


def canonical_json(value: dict) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def sha256_json(value: dict) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stored_result(execution: ExecutionSuccess, plan: QueryPlan) -> StoredAnalysisResult:
    return StoredAnalysisResult(
        execution=execution,
        chart=chart_spec_for(execution.table, plan.presentation.type),
    )


def create_run(
    session: Session,
    cell_id: UUID,
    plan: QueryPlan,
    *,
    stable_model_id: str | None = None,
    prompt_version: str | None = None,
) -> AnalysisRun:
    """Create the audit row before execution so failures remain attributable."""
    cell = session.get(NotebookCell, cell_id)
    if cell is None:
        raise HTTPException(404, "Notebook cell not found.")
    version = session.get(DatasetVersion, cell.dataset_version_id)
    if version is None:
        raise HTTPException(404, "Dataset version not found.")
    if version.status != "READY":
        raise HTTPException(409, "The pinned dataset version is not analysis-ready.")
    normalized = plan.model_dump(mode="json")
    run = AnalysisRun(
        notebook_cell_id=cell.id,
        dataset_version_id=cell.dataset_version_id,
        status="PROCESSING",
        stable_model_id=stable_model_id,
        prompt_version=prompt_version,
        plan_json=normalized,
        plan_sha256=sha256_json(normalized),
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def complete_run(
    session: Session,
    run_id: UUID,
    execution: ExecutionSuccess,
) -> AnalysisRun:
    """Persist one immutable result envelope in the same database transaction."""
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status != "PROCESSING":
        raise HTTPException(409, "Only a processing analysis run can be completed.")
    metadata = execution.metadata
    if metadata.dataset_version_id != str(run.dataset_version_id):
        raise HTTPException(409, "Execution dataset does not match the analysis run.")
    if metadata.plan_sha256 != run.plan_sha256:
        raise HTTPException(409, "Execution plan does not match the analysis run.")

    try:
        plan = QueryPlan.model_validate(run.plan_json)
    except ValidationError as error:
        raise HTTPException(500, "The stored query plan is invalid.") from error
    artifact = stored_result(execution, plan)
    artifact_json = artifact.model_dump(mode="json")
    encoded = canonical_json(artifact_json)
    if len(encoded) > MAX_STORED_RESULT_BYTES:
        raise HTTPException(413, "The structured analysis result exceeds the storage limit.")

    run.result_json = artifact_json
    run.result_sha256 = hashlib.sha256(encoded).hexdigest()
    run.result_size_bytes = len(encoded)
    run.result_version = artifact.artifact_version
    run.status = "SUCCEEDED"
    run.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(run)
    return run


def fail_run(session: Session, run_id: UUID, code: str, message: str) -> AnalysisRun:
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status not in {"QUEUED", "PROCESSING"}:
        raise HTTPException(409, "This analysis run is already terminal.")
    run.status = "FAILED"
    run.error_code = code
    run.error_message = message
    run.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(run)
    return run


def load_result(run: AnalysisRun) -> StoredAnalysisResult:
    """Validate the database JSON and its fingerprint before returning it."""
    if run.status != "SUCCEEDED" or run.result_json is None:
        raise HTTPException(409, "This analysis run does not have a completed result.")
    try:
        artifact = StoredAnalysisResult.model_validate(run.result_json)
    except ValidationError as error:
        raise HTTPException(500, "The stored analysis result is invalid.") from error
    encoded = canonical_json(artifact.model_dump(mode="json"))
    if (
        len(encoded) != run.result_size_bytes
        or hashlib.sha256(encoded).hexdigest() != run.result_sha256
    ):
        raise HTTPException(500, "The stored analysis result failed its integrity check.")
    return artifact
