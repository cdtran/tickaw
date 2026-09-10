"""Environment-backed settings; Compose supplies DATABASE_URL through .env."""
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: SecretStr
    object_storage_bucket: str = "data-notebook-dev"
    aws_region: str = "us-east-1"
    s3_endpoint_url: str | None = None
    minio_root_user: str = "minioadmin"
    minio_root_password: SecretStr = SecretStr("minioadmin")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=100 * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()

