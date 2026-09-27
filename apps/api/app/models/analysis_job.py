"""Durable analysis runs with bounded structured results stored in Postgres."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED')", name="status"),
        CheckConstraint("length(plan_sha256) = 64", name="plan_hash"),
        CheckConstraint("result_sha256 IS NULL OR length(result_sha256) = 64", name="result_hash"),
        CheckConstraint("result_size_bytes IS NULL OR result_size_bytes >= 0", name="result_size"),
        CheckConstraint(
            "status != 'SUCCEEDED' OR (result_json IS NOT NULL AND result_sha256 IS NOT NULL "
            "AND result_size_bytes IS NOT NULL AND result_version IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="succeeded_result",
        ),
        CheckConstraint(
            "status != 'FAILED' OR (error_code IS NOT NULL AND error_message IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="failed_error",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    notebook_cell_id: Mapped[UUID] = mapped_column(
        ForeignKey("notebook_cells.id", ondelete="RESTRICT"), index=True
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'QUEUED'"), index=True)
    stable_model_id: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    plan_sha256: Mapped[str] = mapped_column(Text)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    result_sha256: Mapped[str | None] = mapped_column(Text)
    result_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    result_version: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
