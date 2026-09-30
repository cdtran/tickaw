"""Durable analysis-run state and bounded Postgres result persistence."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisRun, DatasetVersion, NotebookCell
from app.schemas.analysis import StoredAnalysisResult
from app.services.analysis_queue import enqueue_run
from packages.charting.specs import chart_spec_for
from packages.data_engine.query_plan import QueryPlan
from packages.data_engine.result_types import ExecutionSuccess

MAX_STORED_RESULT_BYTES = 2 * 1024**2
ANALYSIS_LEASE_SECONDS = 30
MAX_ANALYSIS_ATTEMPTS = 3


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
    plan: QueryPlan | None = None,
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
    normalized = plan.model_dump(mode="json") if plan is not None else None
    values = {
        "notebook_cell_id": cell.id,
        "dataset_version_id": cell.dataset_version_id,
        "status": "QUEUED",
        "processing_stage": "QUEUED",
        "stable_model_id": stable_model_id or cell.stable_model_id,
        "prompt_version": prompt_version,
    }
    if normalized is not None:
        values.update(plan_json=normalized, plan_sha256=sha256_json(normalized))
    run = AnalysisRun(**values)
    session.add(run)
    session.commit()
    enqueue_run(run.id)
    session.refresh(run)
    return run


def queued_run_for_cell(cell: NotebookCell) -> AnalysisRun:
    """Build a plan-less queue row for insertion with its question cell."""
    return AnalysisRun(
        notebook_cell_id=cell.id,
        dataset_version_id=cell.dataset_version_id,
        status="QUEUED",
        processing_stage="QUEUED",
        stable_model_id=cell.stable_model_id,
    )


def start_run(session: Session, run_id: UUID, worker_id: str = "manual") -> AnalysisRun:
    """Claim a ready or abandoned run with a renewable database lease."""
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    now = datetime.now(UTC)
    ready = run.status == "QUEUED" and (
        run.next_attempt_at is None or run.next_attempt_at <= now
    )
    abandoned = run.status == "PROCESSING" and (
        run.lease_expires_at is None or run.lease_expires_at <= now
    )
    if not (ready or abandoned):
        raise HTTPException(409, "This analysis run is not ready to be claimed.")
    if run.attempt_count >= MAX_ANALYSIS_ATTEMPTS:
        raise HTTPException(409, "This analysis run has exhausted its attempts.")
    run.status = "PROCESSING"
    run.processing_stage = "GENERATING_PLAN" if run.plan_json is None else "DOWNLOADING_DATA"
    run.attempt_count += 1
    run.started_at = run.started_at or now
    run.lease_owner = worker_id
    run.heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=ANALYSIS_LEASE_SECONDS)
    run.next_attempt_at = None
    run.error_code = None
    run.error_message = None
    session.commit()
    session.refresh(run)
    return run


def renew_lease(session: Session, run_id: UUID, worker_id: str) -> bool:
    """Extend a lease only while it is still owned by this active worker."""
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None or run.status != "PROCESSING" or run.lease_owner != worker_id:
        return False
    now = datetime.now(UTC)
    run.heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=ANALYSIS_LEASE_SECONDS)
    session.commit()
    return True


def schedule_retry(session: Session, run_id: UUID, code: str, message: str) -> AnalysisRun:
    """Release a failed attempt and schedule bounded exponential backoff."""
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status != "PROCESSING":
        raise HTTPException(409, "Only a processing analysis run can be retried.")
    if run.attempt_count >= MAX_ANALYSIS_ATTEMPTS:
        return fail_run(session, run_id, code, message)
    delay_seconds = 2 ** run.attempt_count
    run.status = "QUEUED"
    run.processing_stage = "RETRY_WAIT"
    run.error_code = code
    run.error_message = message
    run.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    run.lease_owner = None
    run.lease_expires_at = None
    session.commit()
    session.refresh(run)
    return run


def store_plan(
    session: Session,
    run_id: UUID,
    plan: QueryPlan,
    *,
    stable_model_id: str,
    prompt_version: str,
) -> AnalysisRun:
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status != "PROCESSING" or run.plan_json is not None:
        raise HTTPException(409, "This analysis run cannot accept a generated plan.")
    normalized = plan.model_dump(mode="json")
    run.plan_json = normalized
    run.plan_sha256 = sha256_json(normalized)
    run.stable_model_id = stable_model_id
    run.prompt_version = prompt_version
    run.processing_stage = "DOWNLOADING_DATA"
    session.commit()
    session.refresh(run)
    return run


def set_processing_stage(session: Session, run_id: UUID, stage: str) -> AnalysisRun:
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status != "PROCESSING":
        raise HTTPException(409, "Only a processing run has an active stage.")
    run.processing_stage = stage
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
        run.status = "FAILED"
        run.processing_stage = "FAILED"
        run.error_code = "RESULT_TOO_LARGE"
        run.error_message = (
            f"The structured analysis result is {len(encoded)} bytes; "
            f"the storage limit is {MAX_STORED_RESULT_BYTES} bytes."
        )
        run.completed_at = datetime.now(UTC)
        run.lease_owner = None
        run.lease_expires_at = None
        session.commit()
        raise HTTPException(413, "The structured analysis result exceeds the storage limit.")

    run.result_json = artifact_json
    run.result_sha256 = hashlib.sha256(encoded).hexdigest()
    run.result_size_bytes = len(encoded)
    run.result_version = artifact.artifact_version
    run.status = "SUCCEEDED"
    run.processing_stage = "COMPLETED"
    run.completed_at = datetime.now(UTC)
    run.lease_owner = None
    run.lease_expires_at = None
    session.commit()
    session.refresh(run)
    return run


def fail_run(
    session: Session,
    run_id: UUID,
    code: str,
    message: str,
    diagnostics: list[dict] | None = None,
) -> AnalysisRun:
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status not in {"QUEUED", "PROCESSING"}:
        raise HTTPException(409, "This analysis run is already terminal.")
    run.status = "FAILED"
    run.processing_stage = "FAILED"
    run.error_code = code
    run.error_message = message
    run.validation_diagnostics = diagnostics
    run.completed_at = datetime.now(UTC)
    run.lease_owner = None
    run.lease_expires_at = None
    session.commit()
    session.refresh(run)
    return run


def request_clarification(
    session: Session, run_id: UUID, question: str, diagnostics: list[dict]
) -> AnalysisRun:
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status != "PROCESSING":
        raise HTTPException(409, "Only a processing run can request clarification.")
    run.status = "NEEDS_CLARIFICATION"
    run.processing_stage = "NEEDS_CLARIFICATION"
    run.error_code = "UNANSWERABLE_WITH_DATA"
    run.error_message = question
    run.validation_diagnostics = diagnostics
    run.clarification_question = question
    run.completed_at = None
    run.lease_owner = None
    run.lease_expires_at = None
    session.commit()
    session.refresh(run)
    return run


def answer_clarification(session: Session, run_id: UUID, answer: str) -> AnalysisRun:
    run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    if run.status != "NEEDS_CLARIFICATION":
        raise HTTPException(409, "This analysis run is not waiting for clarification.")
    run.clarification_answer = answer
    run.status = "QUEUED"
    run.processing_stage = "QUEUED"
    run.error_code = None
    run.error_message = None
    session.commit()
    enqueue_run(run.id)
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
