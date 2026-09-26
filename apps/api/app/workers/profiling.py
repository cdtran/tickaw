"""Local durable-job worker. Queue transport can later be replaced by SQS."""
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models import DatasetVersion, ProfilingJob
from app.services.object_storage import get_storage_client

logger = logging.getLogger(__name__)


class ProcessingError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def execute_profile(version: DatasetVersion, job: ProfilingJob) -> tuple[dict, str]:
    settings = get_settings()
    expected_key = f"datasets/{version.dataset_id}/versions/{version.id}/original.csv"
    if (version.storage_bucket != settings.object_storage_bucket
            or version.original_object_key != expected_key or version.file_format != "csv"):
        raise ProcessingError("INVALID_SOURCE", "The original file's storage location or format is invalid.")
    storage = get_storage_client()
    with tempfile.TemporaryDirectory(prefix="profile-") as directory:
        root = Path(directory)
        original, parquet, metadata = root / "input.csv", root / "data.parquet", root / "profile.json"
        response = storage.get_object(Bucket=version.storage_bucket, Key=expected_key)
        stream = response["Body"]
        try:
            if response["ContentLength"] > settings.max_upload_bytes:
                raise ProcessingError("FILE_TOO_LARGE", "Stored CSV exceeds the upload size limit.")
            total = 0
            with original.open("wb") as output:
                while chunk := stream.read(64 * 1024):
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise ProcessingError("FILE_TOO_LARGE", "Stored CSV exceeds the upload size limit.")
                    output.write(chunk)
        finally:
            stream.close()
        if total != version.size_bytes:
            raise ProcessingError("SOURCE_SIZE_MISMATCH", "Stored original size does not match upload metadata.")
        # The child receives no AWS/database credentials. It executes only trusted code.
        environment = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin"),
                       "PYTHONPATH": os.environ.get("PYTHONPATH", "/app:/opt"),
                       "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                       "ARROW_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "app.workers.profile_child", str(original),
                 str(parquet), str(metadata), str(settings.max_upload_bytes)],
                env=environment, timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as error:
            raise ProcessingError("PROFILE_TIMEOUT", "CSV profiling exceeded the 45-second time limit.") from error
        if completed.returncode != 0 or not metadata.exists():
            raise ProcessingError("PARSER_FAILED", "CSV profiling failed or exceeded its resource limits.")
        if metadata.stat().st_size > 2 * 1024**2:
            raise ProcessingError("METADATA_LIMIT", "Profile metadata exceeds its size limit.")
        try:
            result = json.loads(metadata.read_text())
        except (ValueError, OSError) as error:
            raise ProcessingError("INVALID_PROFILE", "The profiler did not produce readable metadata.") from error
        if "error_code" in result:
            raise ProcessingError(result["error_code"], result["error_message"])
        key = (f"datasets/{version.dataset_id}/versions/{version.id}/"
               f"normalized/{result['profile_json']['profiler_version']}/{job.id}/attempt-{job.attempt_count}.parquet")
        with parquet.open("rb") as body:
            storage.put_object(Bucket=version.storage_bucket, Key=key, Body=body,
                               ContentType="application/vnd.apache.parquet", IfNoneMatch="*")
        return result, key


def fail(session, version, job, code, message, retry=False):
    job.error_code, job.error_message = code, message
    version.error_code, version.error_message = code, message
    if retry and job.attempt_count < 3:
        job.status = "QUEUED"
    else:
        job.status = version.status = "FAILED"
        job.completed_at = version.completed_at = datetime.now(timezone.utc)
    session.commit()


def run_job(job_id: UUID) -> bool:
    # A dedicated connection owns a session-level advisory lock across short commits.
    # Closing/crashing releases it; a replacement worker can recover PROCESSING jobs.
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass=NullPool)
    lock_id = int.from_bytes(job_id.bytes[:8], "big", signed=True)
    try:
        with engine.connect() as connection:
            locked = connection.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id})
            connection.commit()
            if not locked:
                return False
            try:
                with Session(bind=connection, expire_on_commit=False) as session:
                    job = session.get(ProfilingJob, job_id)
                    if job is None or job.status not in {"QUEUED", "PROCESSING"}:
                        return False
                    version = session.get(DatasetVersion, job.dataset_version_id)
                    if version.status == "READY":
                        job.status = "SUCCEEDED"
                        job.completed_at = datetime.now(timezone.utc)
                        session.commit()
                        return True
                    if job.attempt_count >= 3:
                        fail(session, version, job, "ATTEMPTS_EXHAUSTED", "Profiling was interrupted too many times.")
                        return True
                    job.attempt_count += 1
                    job.status = version.status = "PROCESSING"
                    job.started_at = datetime.now(timezone.utc)
                    version.processing_started_at = job.started_at
                    job.error_code = job.error_message = None
                    version.error_code = version.error_message = None
                    session.commit()
                    logger.info("Profiling job=%s version=%s attempt=%s", job.id, version.id, job.attempt_count)
                    try:
                        result, key = execute_profile(version, job)
                    except ProcessingError as error:
                        fail(session, version, job, error.code, str(error))
                    except (BotoCoreError, ClientError):
                        logger.exception("Storage failure job=%s", job.id)
                        fail(session, version, job, "STORAGE_ERROR", "Storage could not be read or written.", retry=True)
                    except Exception:
                        logger.exception("Unexpected profiler failure job=%s", job.id)
                        fail(session, version, job, "PROCESSING_ERROR",
                             "An internal profiling error occurred. Check the worker logs before trying again.")
                    else:
                        version.schema_json = result["schema_json"]
                        version.profile_json = result["profile_json"]
                        version.preview_json = result["preview_json"]
                        version.row_count = result["row_count"]
                        version.normalized_object_key = key
                        version.status, job.status = "READY", "SUCCEEDED"
                        version.completed_at = job.completed_at = datetime.now(timezone.utc)
                        session.commit()
                        logger.info("Completed job=%s rows=%s", job.id, version.row_count)
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
        jobs = session.scalars(select(ProfilingJob.id)
                               .where(ProfilingJob.status.in_(["QUEUED", "PROCESSING"]))
                               .order_by(ProfilingJob.created_at).limit(50)).all()
    for job_id in jobs:
        if run_job(job_id):
            return True
    return False


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            if run_once():
                continue
        except Exception:
            logger.exception("Worker iteration failed; durable jobs remain recoverable")
        time.sleep(3)


if __name__ == "__main__":
    main()
