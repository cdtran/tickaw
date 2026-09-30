"""Add analysis worker leases, heartbeats, and bounded retry scheduling."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "analysis_runs",
        sa.Column(
            "lease_owner",
            sa.Text(),
            nullable=True,
            comment="Opaque identity of the worker currently processing this run.",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Time after which another worker may reclaim this run.",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Most recent lease renewal by the active worker.",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Earliest time a transiently failed run may be retried.",
        ),
    )
    op.create_check_constraint(
        "attempt_count", "analysis_runs", "attempt_count >= 0 AND attempt_count <= 3"
    )
    op.create_check_constraint(
        "lease_pair",
        "analysis_runs",
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
    )
    op.create_index("ix_analysis_runs_next_attempt_at", "analysis_runs", ["next_attempt_at"])
    op.create_index("ix_analysis_runs_lease_expires_at", "analysis_runs", ["lease_expires_at"])


def downgrade():
    op.drop_index("ix_analysis_runs_lease_expires_at", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_next_attempt_at", table_name="analysis_runs")
    op.drop_constraint("lease_pair", "analysis_runs", type_="check")
    op.drop_constraint("attempt_count", "analysis_runs", type_="check")
    op.drop_column("analysis_runs", "next_attempt_at")
    op.drop_column("analysis_runs", "heartbeat_at")
    op.drop_column("analysis_runs", "lease_expires_at")
    op.drop_column("analysis_runs", "lease_owner")
