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
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_version_id: Mapped[UUID] = mapped_column(ForeignKey("dataset_versions.id", ondelete="RESTRICT"), unique=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'QUEUED'"), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
