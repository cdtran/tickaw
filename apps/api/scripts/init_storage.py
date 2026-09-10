"""Explicit, repeatable local bucket setup: python -m scripts.init_storage."""
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.services.object_storage import get_storage_client


def main():
    settings = get_settings()
    if not settings.s3_endpoint_url:
        raise RuntimeError("This initializer is for local MinIO; provision AWS buckets with Terraform.")
    client = get_storage_client()
    try:
        client.head_bucket(Bucket=settings.object_storage_bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
            raise
        try:
            client.create_bucket(Bucket=settings.object_storage_bucket)
        except ClientError as creation_error:
            if creation_error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
    print("Local upload bucket is ready.")


if __name__ == "__main__":
    main()
