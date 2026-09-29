"""Wake analysis workers when a durable run is committed."""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION notify_analysis_run_queued() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_notify('analysis_run_queued', NEW.id::text);
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER analysis_run_queue_notify
        AFTER INSERT ON analysis_runs
        FOR EACH ROW
        WHEN (NEW.status = 'QUEUED')
        EXECUTE FUNCTION notify_analysis_run_queued()
    """)


def downgrade():
    op.execute("DROP TRIGGER analysis_run_queue_notify ON analysis_runs")
    op.execute("DROP FUNCTION notify_analysis_run_queued()")
