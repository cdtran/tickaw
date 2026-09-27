"""Dataset identity and immutable, independently addressable snapshots."""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, comment="Stable identifier for the dataset."
    )
    name: Mapped[str] = mapped_column(Text, comment="User-facing dataset name.")
    description: Mapped[str | None] = mapped_column(
        Text, comment="Optional user-facing description of the dataset."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="Time the dataset was created.",
    )
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

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, comment="Stable identifier for this dataset snapshot."
    )
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"),
        comment="Dataset that owns this immutable version.",
    )
    version_number: Mapped[int] = mapped_column(
        Integer, comment="Monotonic version number within the dataset."
    )
    status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'UPLOADING'"),
        comment="Current upload and profiling lifecycle state.",
    )
    original_filename: Mapped[str] = mapped_column(
        Text, comment="Filename supplied when this version was uploaded."
    )
    file_format: Mapped[str] = mapped_column(
        Text, comment="Validated source format, currently csv or xlsx."
    )
    size_bytes: Mapped[int | None] = mapped_column(
        BigInteger, comment="Size of the original uploaded object in bytes."
    )
    storage_bucket: Mapped[str] = mapped_column(
        Text, comment="S3 bucket containing this version's objects."
    )
    original_object_key: Mapped[str] = mapped_column(
        Text, comment="Immutable S3 key for the original uploaded file."
    )
    normalized_object_key: Mapped[str | None] = mapped_column(
        Text, comment="S3 key for the normalized Parquet snapshot."
    )
    row_count: Mapped[int | None] = mapped_column(
        BigInteger, comment="Number of rows in the normalized snapshot."
    )
    schema_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), comment="Versioned inferred column schema."
    )
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), comment="Versioned dataset profiling statistics."
    )
    preview_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB(none_as_null=True), comment="Small JSON-safe preview of normalized rows."
    )
    error_code: Mapped[str | None] = mapped_column(
        Text, comment="Stable machine-readable failure code."
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, comment="Safe human-readable failure description."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="Time this dataset version was created.",
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Time profiling most recently started."
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Time profiling reached a terminal state."
    )
    dataset: Mapped[Dataset] = relationship(back_populates="versions")
