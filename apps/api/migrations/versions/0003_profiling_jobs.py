"""Durable profiling jobs; version UUID is the idempotency key."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "profiling_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'QUEUED'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("dataset_version_id"),
        sa.CheckConstraint("status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED')", name="status"),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 3", name="attempt_count"),
    )
    op.create_index("ix_profiling_jobs_status", "profiling_jobs", ["status"])


def downgrade():
    op.drop_index("ix_profiling_jobs_status", table_name="profiling_jobs")
    op.drop_table("profiling_jobs")
