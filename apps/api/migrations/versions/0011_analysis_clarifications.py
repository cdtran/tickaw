"""Persist safe plan diagnostics and resumable clarification state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("status", "analysis_runs", type_="check")
    op.create_check_constraint(
        "status",
        "analysis_runs",
        "status IN ('QUEUED', 'PROCESSING', 'NEEDS_CLARIFICATION', 'SUCCEEDED', 'FAILED')",
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "validation_diagnostics",
            postgresql.JSONB(),
            nullable=True,
            comment="Safe structured reasons why generated plans were rejected.",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "clarification_question",
            sa.Text(),
            nullable=True,
            comment="Specific question that must be answered before planning can resume.",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "clarification_answer",
            sa.Text(),
            nullable=True,
            comment="User answer supplied to resume this same analysis run.",
        ),
    )
    op.create_check_constraint(
        "clarification_state",
        "analysis_runs",
        "status != 'NEEDS_CLARIFICATION' OR clarification_question IS NOT NULL",
    )


def downgrade():
    op.execute("UPDATE analysis_runs SET status = 'FAILED', processing_stage = 'FAILED', "
               "error_code = 'UNANSWERABLE_WITH_DATA', "
               "error_message = COALESCE(clarification_question, 'Clarification was required'), "
               "completed_at = COALESCE(completed_at, now()) "
               "WHERE status = 'NEEDS_CLARIFICATION'")
    op.drop_constraint("clarification_state", "analysis_runs", type_="check")
    op.drop_column("analysis_runs", "clarification_answer")
    op.drop_column("analysis_runs", "clarification_question")
    op.drop_column("analysis_runs", "validation_diagnostics")
    op.drop_constraint("status", "analysis_runs", type_="check")
    op.create_check_constraint(
        "status", "analysis_runs", "status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED')"
    )
