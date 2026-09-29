"""Allow durable analysis runs to be queued before model planning."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP TRIGGER analysis_run_immutable ON analysis_runs")
    op.execute("DROP FUNCTION protect_analysis_run()")
    op.drop_constraint("plan_hash", "analysis_runs", type_="check")
    op.alter_column("analysis_runs", "plan_json", nullable=True)
    op.alter_column("analysis_runs", "plan_sha256", nullable=True)
    op.add_column(
        "analysis_runs",
        sa.Column(
            "processing_stage",
            sa.Text(),
            server_default="QUEUED",
            nullable=False,
            comment="Current worker stage for progress reporting and crash recovery.",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Number of times a worker claimed this run.",
        ),
    )
    op.create_check_constraint(
        "plan_hash",
        "analysis_runs",
        "plan_sha256 IS NULL OR length(plan_sha256) = 64",
    )
    op.create_check_constraint(
        "plan_pair",
        "analysis_runs",
        "(plan_json IS NULL) = (plan_sha256 IS NULL)",
    )
    op.execute("""
        CREATE FUNCTION protect_analysis_run() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('SUCCEEDED', 'FAILED') AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal analysis runs are immutable';
            END IF;
            IF ROW(NEW.id, NEW.notebook_cell_id, NEW.dataset_version_id, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.notebook_cell_id, OLD.dataset_version_id, OLD.created_at)
            THEN
                RAISE EXCEPTION 'analysis run identity is immutable';
            END IF;
            IF OLD.plan_json IS NOT NULL AND
               ROW(NEW.plan_json, NEW.plan_sha256) IS DISTINCT FROM
               ROW(OLD.plan_json, OLD.plan_sha256)
            THEN
                RAISE EXCEPTION 'analysis run plan is immutable once assigned';
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
    op.execute("DROP TRIGGER analysis_run_immutable ON analysis_runs")
    op.execute("DROP FUNCTION protect_analysis_run()")
    op.drop_constraint("plan_pair", "analysis_runs", type_="check")
    op.drop_constraint("plan_hash", "analysis_runs", type_="check")
    op.drop_column("analysis_runs", "attempt_count")
    op.drop_column("analysis_runs", "processing_stage")
    op.execute("DELETE FROM analysis_runs WHERE plan_json IS NULL OR plan_sha256 IS NULL")
    op.alter_column("analysis_runs", "plan_sha256", nullable=False)
    op.alter_column("analysis_runs", "plan_json", nullable=False)
    op.create_check_constraint("plan_hash", "analysis_runs", "length(plan_sha256) = 64")
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
