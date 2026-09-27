"""Durable local work records, independent of future queue transport."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProfilingJob(Base):
    __tablename__ = "profiling_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED')", name="status"),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 3", name="attempt_count"),
    )
    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, comment="Stable identifier for the profiling job."
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        unique=True,
        comment="Dataset version profiled by this job.",
    )
    status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'QUEUED'"),
        index=True,
        comment="Current profiling job lifecycle state.",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), comment="Number of processing attempts started."
    )
    error_code: Mapped[str | None] = mapped_column(
        Text, comment="Stable machine-readable failure code."
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, comment="Safe human-readable failure description."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Time the job was created."
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Time the current processing attempt started."
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Time the job reached a terminal state."
    )
