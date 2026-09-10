"""S3 original-object writes; no overwrite or delete operation in the upload path."""
from functools import lru_cache

import boto3
from botocore.config import Config

from app.core.config import get_settings


@lru_cache
def get_storage_client():
    settings = get_settings()
    credentials = {}
    if settings.s3_endpoint_url:
        # Local MinIO only. AWS deployments use the task's IAM role instead.
        credentials = {
            "aws_access_key_id": settings.minio_root_user,
            "aws_secret_access_key": settings.minio_root_password.get_secret_value(),
        }
    return boto3.client(
        "s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.aws_region,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2},
                      s3={"addressing_style": "path"}),
        **credentials,
    )


def store_original(bucket: str, key: str, data: bytes) -> None:
    get_storage_client().put_object(
        Bucket=bucket, Key=key, Body=data, ContentType="text/csv",
        IfNoneMatch="*",  # S3/MinIO rejects writes if this key already exists.
    )
