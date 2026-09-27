"""Persist analysis plans and bounded reconstructable result artifacts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "notebook_cell_id",
            sa.Uuid(),
            sa.ForeignKey("notebook_cells.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "dataset_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'QUEUED'"), nullable=False),
        sa.Column("stable_model_id", sa.Text()),
        sa.Column("prompt_version", sa.Text()),
        sa.Column("plan_json", postgresql.JSONB(), nullable=False),
        sa.Column("plan_sha256", sa.Text(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(none_as_null=True)),
        sa.Column("result_sha256", sa.Text()),
        sa.Column("result_size_bytes", sa.BigInteger()),
        sa.Column("result_version", sa.Integer()),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED')", name="status"
        ),
        sa.CheckConstraint("length(plan_sha256) = 64", name="plan_hash"),
        sa.CheckConstraint(
            "result_sha256 IS NULL OR length(result_sha256) = 64", name="result_hash"
        ),
        sa.CheckConstraint(
            "result_size_bytes IS NULL OR result_size_bytes >= 0", name="result_size"
        ),
        sa.CheckConstraint(
            "status != 'SUCCEEDED' OR (result_json IS NOT NULL AND result_sha256 IS NOT NULL "
            "AND result_size_bytes IS NOT NULL AND result_version IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="succeeded_result",
        ),
        sa.CheckConstraint(
            "status != 'FAILED' OR (error_code IS NOT NULL AND error_message IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="failed_error",
        ),
    )
    op.create_index("ix_analysis_runs_notebook_cell_id", "analysis_runs", ["notebook_cell_id"])
    op.create_index("ix_analysis_runs_dataset_version_id", "analysis_runs", ["dataset_version_id"])
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])
    op.execute("""
        CREATE FUNCTION protect_analysis_run() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('SUCCEEDED', 'FAILED') AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal analysis runs are immutable';
            END IF;
            IF ROW(NEW.id, NEW.notebook_cell_id, NEW.dataset_version_id,
                   NEW.plan_json, NEW.plan_sha256, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.notebook_cell_id, OLD.dataset_version_id,
                   OLD.plan_json, OLD.plan_sha256, OLD.created_at)
            THEN
                RAISE EXCEPTION 'analysis run identity and plan are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER analysis_run_immutable BEFORE UPDATE ON analysis_runs
        FOR EACH ROW EXECUTE FUNCTION protect_analysis_run()
    """)


def downgrade():
    op.drop_table("analysis_runs")
    op.execute("DROP FUNCTION protect_analysis_run()")
