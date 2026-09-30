"""Durable analysis worker for normalized Parquet query execution."""

import logging
import os
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import redis
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import and_, create_engine, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models import AnalysisRun, DatasetVersion
from app.services.analysis_queue import GROUP, STREAM, get_queue
from app.services.analysis_service import (
    complete_run,
    fail_run,
    renew_lease,
    request_clarification,
    schedule_retry,
    set_processing_stage,
    start_run,
    store_plan,
)
from app.services.llm_service import get_llm_gateway
from app.services.object_storage import get_storage_client
from app.services.plan_service import PlanGenerationError, generate_plan
from packages.data_engine.execution import ExecutionLimits, catalog_from_profile, execute_plan
from packages.data_engine.result_types import ExecutionFailure

logger = logging.getLogger(__name__)
RECOVERY_SCAN_SECONDS = 30.0
PENDING_IDLE_MS = 5 * 60 * 1000
HEARTBEAT_SECONDS = 10


class AnalysisProcessingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def transient_storage_error(error: BotoCoreError | ClientError) -> bool:
    if not isinstance(error, ClientError):
        return True
    metadata = error.response.get("ResponseMetadata", {})
    status = metadata.get("HTTPStatusCode")
    code = str(error.response.get("Error", {}).get("Code", ""))
    return status in {408, 429} or (isinstance(status, int) and status >= 500) or code in {
        "RequestTimeout",
        "SlowDown",
        "Throttling",
        "ServiceUnavailable",
        "InternalError",
    }


@contextmanager
def lease_heartbeat(run_id: UUID, worker_id: str):
    """Renew the durable lease while blocking provider/storage/query work runs."""
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.wait(HEARTBEAT_SECONDS):
            try:
                with get_session_factory()() as heartbeat_session:
                    if not renew_lease(heartbeat_session, run_id, worker_id):
                        return
            except Exception:
                logger.exception("Could not renew analysis lease run=%s", run_id)

    thread = threading.Thread(target=beat, name=f"analysis-heartbeat-{run_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


def download_snapshot(version: DatasetVersion, destination: Path) -> None:
    settings = get_settings()
    prefix = f"datasets/{version.dataset_id}/versions/{version.id}/normalized/"
    key = version.normalized_object_key
    if (
        version.storage_bucket != settings.object_storage_bucket
        or not key
        or not key.startswith(prefix)
        or not key.endswith(".parquet")
    ):
        raise AnalysisProcessingError(
            "INVALID_SOURCE", "The normalized dataset storage location is invalid."
        )
    limit = ExecutionLimits().max_source_bytes
    response = get_storage_client().get_object(Bucket=version.storage_bucket, Key=key)
    stream = response["Body"]
    try:
        if response["ContentLength"] > limit:
            raise AnalysisProcessingError(
                "SOURCE_LIMIT", "The normalized dataset exceeds its size limit."
            )
        total = 0
        with destination.open("wb") as output:
            while chunk := stream.read(64 * 1024):
                total += len(chunk)
                if total > limit:
                    raise AnalysisProcessingError(
                        "SOURCE_LIMIT", "The normalized dataset exceeds its size limit."
                    )
                output.write(chunk)
        if total != response["ContentLength"]:
            raise AnalysisProcessingError(
                "SOURCE_SIZE_MISMATCH", "The normalized dataset download was incomplete."
            )
    finally:
        stream.close()


def process_run(session: Session, run_id: UUID) -> None:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise AnalysisProcessingError("RUN_NOT_FOUND", "The analysis run no longer exists.")
    if run.status != "PROCESSING":
        return
    if run.plan_json is None:
        plan, response = generate_plan(session, run, get_llm_gateway())
        run = store_plan(
            session,
            run.id,
            plan,
            stable_model_id=response.stable_model_id,
            prompt_version=response.prompt_version,
        )
    version = session.get(DatasetVersion, run.dataset_version_id)
    if version is None or version.status != "READY":
        raise AnalysisProcessingError(
            "SOURCE_UNAVAILABLE", "The pinned dataset version is not analysis-ready."
        )
    try:
        catalog = catalog_from_profile(version.schema_json or {})
    except ValueError as error:
        raise AnalysisProcessingError(
            "INVALID_SCHEMA", "The pinned dataset schema is invalid."
        ) from error
    with tempfile.TemporaryDirectory(prefix="tickaw-analysis-") as directory:
        parquet = Path(directory) / "dataset.parquet"
        download_snapshot(version, parquet)
        set_processing_stage(session, run.id, "EXECUTING")
        result = execute_plan(
            run.plan_json,
            parquet_path=parquet,
            dataset_version_id=str(version.id),
            columns=catalog,
            question_meaning_checked=True,
        )
    if isinstance(result, ExecutionFailure):
        fail_run(session, run.id, result.error.code, result.error.message)
    else:
        complete_run(session, run.id, result)


def run_job(run_id: UUID, worker_id: str = "recovery") -> bool:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass=NullPool)
    lock_id = int.from_bytes(run_id.bytes[:8], "big", signed=True)
    try:
        with engine.connect() as connection:
            locked = connection.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id})
            connection.commit()
            if not locked:
                return False
            try:
                with Session(bind=connection, expire_on_commit=False) as session:
                    run = session.get(AnalysisRun, run_id)
                    if run is None or run.status not in {"QUEUED", "PROCESSING"}:
                        return False
                    now = datetime.now(UTC)
                    if run.status == "QUEUED" and (
                        run.next_attempt_at is not None and run.next_attempt_at > now
                    ):
                        return False
                    if run.status == "PROCESSING" and (
                        run.lease_expires_at is not None and run.lease_expires_at > now
                    ):
                        return False
                    if run.attempt_count >= 3:
                        fail_run(
                            session,
                            run.id,
                            "ATTEMPTS_EXHAUSTED",
                            "The analysis could not be completed after three attempts.",
                        )
                        return True
                    try:
                        start_run(session, run.id, worker_id)
                        with lease_heartbeat(run.id, worker_id):
                            process_run(session, run.id)
                    except AnalysisProcessingError as error:
                        fail_run(session, run.id, error.code, str(error))
                    except PlanGenerationError as error:
                        if error.code == "UNANSWERABLE_WITH_DATA":
                            request_clarification(session, run.id, str(error), error.diagnostics)
                        elif error.code == "MODEL_UNAVAILABLE":
                            schedule_retry(session, run.id, error.code, str(error))
                        else:
                            fail_run(
                                session, run.id, error.code, str(error), error.diagnostics
                            )
                    except (BotoCoreError, ClientError) as error:
                        logger.exception("Storage failure analysis_run=%s", run.id)
                        action = schedule_retry if transient_storage_error(error) else fail_run
                        action(
                            session,
                            run.id,
                            "STORAGE_ERROR",
                            "The normalized dataset could not be downloaded.",
                        )
                    except Exception:
                        logger.exception("Unexpected analysis failure run=%s", run.id)
                        session.rollback()
                        current = session.get(AnalysisRun, run.id)
                        if current is not None and current.status in {"QUEUED", "PROCESSING"}:
                            fail_run(
                                session,
                                run.id,
                                "ANALYSIS_ERROR",
                                "An internal analysis error occurred.",
                            )
                    return True
            finally:
                if not connection.invalidated:
                    connection.rollback()
                    connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id})
                    connection.commit()
    finally:
        engine.dispose()


def run_once(worker_id: str = "recovery") -> bool:
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        run_ids = session.scalars(
            select(AnalysisRun.id)
            .where(
                or_(
                    and_(
                        AnalysisRun.status == "QUEUED",
                        or_(
                            AnalysisRun.next_attempt_at.is_(None),
                            AnalysisRun.next_attempt_at <= now,
                        ),
                    ),
                    and_(
                        AnalysisRun.status == "PROCESSING",
                        or_(
                            AnalysisRun.lease_expires_at.is_(None),
                            AnalysisRun.lease_expires_at <= now,
                        ),
                    ),
                )
            )
            .order_by(AnalysisRun.created_at, AnalysisRun.id)
            .limit(50)
        ).all()
    for run_id in run_ids:
        if run_job(run_id, worker_id):
            return True
    return False


def ensure_group(queue: redis.Redis) -> None:
    try:
        queue.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.ResponseError as error:
        if "BUSYGROUP" not in str(error):
            raise


def acknowledge(queue: redis.Redis, message_id: str) -> None:
    queue.xack(STREAM, GROUP, message_id)
    queue.xdel(STREAM, message_id)


def process_message(queue: redis.Redis, message_id: str, values: dict, worker_id: str) -> None:
    try:
        run_id = UUID(values["run_id"])
    except (KeyError, TypeError, ValueError):
        logger.error("Discarding invalid analysis queue message=%s", message_id)
        acknowledge(queue, message_id)
        return
    # The advisory lock protects the long-running job against duplicate delivery.
    run_job(run_id, worker_id)
    with get_session_factory()() as session:
        run = session.get(AnalysisRun, run_id)
        settled = (
            run is None
            or run.status in {"NEEDS_CLARIFICATION", "SUCCEEDED", "FAILED"}
            or (run.status == "QUEUED" and run.next_attempt_at is not None)
        )
    if settled:
        acknowledge(queue, message_id)


def recover_pending(queue: redis.Redis, consumer: str) -> None:
    # Redis pending-entry cleanup is secondary to the faster database lease scan.
    cursor = "0-0"
    while True:
        cursor, messages, _ = queue.xautoclaim(
            STREAM, GROUP, consumer, PENDING_IDLE_MS, start_id=cursor, count=25
        )
        for message_id, values in messages:
            process_message(queue, message_id, values, consumer)
        if cursor == "0-0":
            return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    last_recovery = 0.0
    while True:
        try:
            queue = get_queue()
            ensure_group(queue)
            now = time.monotonic()
            if now - last_recovery >= RECOVERY_SCAN_SECONDS:
                while run_once(consumer):
                    pass
                recover_pending(queue, consumer)
                last_recovery = time.monotonic()
            deliveries = queue.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=1, block=5000)
            for _, messages in deliveries:
                for message_id, values in messages:
                    process_message(queue, message_id, values, consumer)
        except redis.RedisError:
            logger.exception("Analysis queue unavailable; scanning durable database")
            try:
                run_once(consumer)
            except Exception:
                logger.exception("Analysis database recovery scan failed")
            time.sleep(1)
        except Exception:
            logger.exception("Analysis worker iteration failed; queued runs remain durable")
            time.sleep(1)


if __name__ == "__main__":
    main()
