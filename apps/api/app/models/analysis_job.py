"""Durable analysis runs with bounded structured results stored in Postgres."""

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'NEEDS_CLARIFICATION', 'SUCCEEDED', 'FAILED')",
            name="status",
        ),
        CheckConstraint("plan_sha256 IS NULL OR length(plan_sha256) = 64", name="plan_hash"),
        CheckConstraint("(plan_json IS NULL) = (plan_sha256 IS NULL)", name="plan_pair"),
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

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, comment="Stable identifier for the analysis run."
    )
    notebook_cell_id: Mapped[UUID] = mapped_column(
        ForeignKey("notebook_cells.id", ondelete="RESTRICT"),
        index=True,
        comment="Question cell that requested this analysis.",
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        index=True,
        comment="Exact immutable dataset version used for execution.",
    )
    status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'QUEUED'"),
        index=True,
        comment="Current analysis execution lifecycle state.",
    )
    processing_stage: Mapped[str] = mapped_column(
        Text,
        server_default=text("'QUEUED'"),
        comment="Current worker stage for progress reporting and crash recovery.",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), comment="Number of times a worker claimed this run."
    )
    stable_model_id: Mapped[str | None] = mapped_column(
        Text, comment="Stable identifier for the model configuration that produced the plan."
    )
    prompt_version: Mapped[str | None] = mapped_column(
        Text, comment="Version of the prompt used to produce the plan."
    )
    plan_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="Normalized, validated model-generated query plan."
    )
    plan_sha256: Mapped[str | None] = mapped_column(
        Text, comment="SHA-256 of the canonical normalized query plan."
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), comment="Bounded execution result and reconstructable chart spec."
    )
    result_sha256: Mapped[str | None] = mapped_column(
        Text, comment="SHA-256 of the canonical persisted result artifact."
    )
    result_size_bytes: Mapped[int | None] = mapped_column(
        BigInteger, comment="Canonical result artifact size in UTF-8 bytes."
    )
    result_version: Mapped[int | None] = mapped_column(
        Integer, comment="Schema version of the persisted result artifact."
    )
    error_code: Mapped[str | None] = mapped_column(
        Text, comment="Stable machine-readable failure code."
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, comment="Safe human-readable failure description."
    )
    validation_diagnostics: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, comment="Safe structured reasons why generated plans were rejected."
    )
    clarification_question: Mapped[str | None] = mapped_column(
        Text, comment="Specific question that must be answered before planning can resume."
    )
    clarification_answer: Mapped[str | None] = mapped_column(
        Text, comment="User answer supplied to resume this same analysis run."
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="Time the run was created."
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Time execution started."
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Time the run reached a terminal state."
    )
