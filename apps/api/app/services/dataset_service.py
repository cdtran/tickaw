"""Allocate versions in Postgres, then durably store their original bytes."""
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import Dataset, DatasetVersion
from app.schemas.dataset import DatasetResponse
from app.services.object_storage import store_original
from app.services.profiling_service import enqueue_profile

logger = logging.getLogger(__name__)


def list_datasets(session: Session, offset: int, limit: int) -> list[DatasetResponse]:
    datasets = session.scalars(
        select(Dataset).options(selectinload(Dataset.versions))
        .order_by(Dataset.created_at.desc(), Dataset.id).offset(offset).limit(limit)
    ).all()
    return [describe_dataset(dataset) for dataset in datasets]


def describe_dataset(dataset: Dataset) -> DatasetResponse:
    result = DatasetResponse.model_validate(dataset)
    result.versions.sort(key=lambda version: version.version_number, reverse=True)
    return result


def upload_csv(session: Session, filename: str, data: bytes,
               dataset_id: UUID | None) -> DatasetResponse:
    if dataset_id:
        # Serialize version allocation for this dataset only, not all uploads.
        dataset = session.scalar(select(Dataset).where(Dataset.id == dataset_id).with_for_update())
        if dataset is None:
            raise HTTPException(404, "Dataset not found.")
    else:
        dataset = Dataset(name=filename[:-4])
        session.add(dataset)
        session.flush()

    number = session.scalar(select(func.coalesce(func.max(DatasetVersion.version_number), 0))
                            .where(DatasetVersion.dataset_id == dataset.id)) + 1
    version_id = uuid4()
    version = DatasetVersion(
        id=version_id, dataset_id=dataset.id, version_number=number,
        original_filename=filename, file_format="csv", size_bytes=len(data),
        storage_bucket=get_settings().object_storage_bucket,
        original_object_key=f"datasets/{dataset.id}/versions/{version_id}/original.csv",
    )
    session.add(version)
    session.commit()  # Reserve identity before S3 I/O; release the row lock promptly.
    try:
        store_original(version.storage_bucket, version.original_object_key, data)
    except (BotoCoreError, ClientError):
        logger.exception("Original storage failed for dataset_version=%s", version.id)
        version.status = "FAILED"
        version.error_code = "STORAGE_WRITE_FAILED"
        version.error_message = "The original file could not be confirmed in storage."
        version.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise HTTPException(503, "Storage unavailable. This upload was marked failed.") from None

    version.status = "UPLOADED"
    enqueue_profile(session, version)
    session.commit()
    session.expire(dataset, ["versions"])
    return describe_dataset(dataset)
