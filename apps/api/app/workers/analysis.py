"""Durable analysis worker for normalized Parquet query execution."""

import logging
import tempfile
import time
from pathlib import Path
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models import AnalysisRun, DatasetVersion
from app.services.analysis_service import complete_run, fail_run, start_run
from app.services.object_storage import get_storage_client
from packages.data_engine.execution import ExecutionLimits, catalog_from_profile, execute_plan
from packages.data_engine.result_types import ExecutionFailure

logger = logging.getLogger(__name__)


class AnalysisProcessingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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
    if run.status == "QUEUED":
        run = start_run(session, run_id)
    elif run.status != "PROCESSING":
        return
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
        result = execute_plan(
            run.plan_json,
            parquet_path=parquet,
            dataset_version_id=str(version.id),
            columns=catalog,
        )
    if isinstance(result, ExecutionFailure):
        fail_run(session, run.id, result.error.code, result.error.message)
    else:
        complete_run(session, run.id, result)


def run_job(run_id: UUID) -> bool:
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
                    try:
                        process_run(session, run.id)
                    except AnalysisProcessingError as error:
                        fail_run(session, run.id, error.code, str(error))
                    except (BotoCoreError, ClientError):
                        logger.exception("Storage failure analysis_run=%s", run.id)
                        fail_run(
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


def run_once() -> bool:
    with get_session_factory()() as session:
        run_ids = session.scalars(
            select(AnalysisRun.id)
            .where(AnalysisRun.status.in_(["QUEUED", "PROCESSING"]))
            .order_by(AnalysisRun.created_at, AnalysisRun.id)
            .limit(50)
        ).all()
    for run_id in run_ids:
        if run_job(run_id):
            return True
    return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            if run_once():
                continue
        except Exception:
            logger.exception("Analysis worker iteration failed; queued runs remain durable")
        time.sleep(1)


if __name__ == "__main__":
    main()
