"""Dataset identity and immutable, independently addressable snapshots."""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy import UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset", passive_deletes="all"
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_number"),
        UniqueConstraint("storage_bucket", "original_object_key"),
        CheckConstraint("version_number > 0", name="positive_version"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("row_count >= 0", name="nonnegative_rows"),
        CheckConstraint("file_format IN ('csv', 'xlsx')", name="file_format"),
        CheckConstraint("status IN ('UPLOADING', 'UPLOADED', 'PROCESSING', 'READY', 'FAILED')", name="status"),
        CheckConstraint("status != 'UPLOADED' OR (size_bytes IS NOT NULL AND size_bytes > 0)", name="uploaded_size"),
        CheckConstraint(
            "status != 'READY' OR (normalized_object_key IS NOT NULL AND "
            "schema_json IS NOT NULL AND profile_json IS NOT NULL AND "
            "preview_json IS NOT NULL AND row_count IS NOT NULL AND completed_at IS NOT NULL)",
            name="ready_metadata",
        ),
        CheckConstraint(
            "status != 'FAILED' OR (error_code IS NOT NULL AND "
            "error_message IS NOT NULL AND completed_at IS NOT NULL)", name="failed_error",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"))
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default=text("'UPLOADING'"))
    original_filename: Mapped[str] = mapped_column(Text)
    file_format: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    storage_bucket: Mapped[str] = mapped_column(Text)
    original_object_key: Mapped[str] = mapped_column(Text)
    normalized_object_key: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    preview_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dataset: Mapped[Dataset] = relationship(back_populates="versions")
