"""Create dataset identities and immutable versions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'UPLOADING'"), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("file_format", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("storage_bucket", sa.Text(), nullable=False),
        sa.Column("original_object_key", sa.Text(), nullable=False),
        sa.Column("normalized_object_key", sa.Text()),
        sa.Column("row_count", sa.BigInteger()),
        sa.Column("schema_json", postgresql.JSONB(none_as_null=True)),
        sa.Column("profile_json", postgresql.JSONB(none_as_null=True)),
        sa.Column("preview_json", postgresql.JSONB(none_as_null=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_versions"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="RESTRICT",
                                name="fk_dataset_versions_dataset_id_datasets"),
        sa.UniqueConstraint("dataset_id", "version_number", name="uq_dataset_versions_dataset_id"),
        sa.UniqueConstraint("storage_bucket", "original_object_key",
                            name="uq_dataset_versions_storage_bucket"),
        sa.CheckConstraint("version_number > 0", name="positive_version"),
        sa.CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        sa.CheckConstraint("row_count >= 0", name="nonnegative_rows"),
        sa.CheckConstraint("file_format IN ('csv', 'xlsx')", name="file_format"),
        sa.CheckConstraint("status IN ('UPLOADING', 'PROCESSING', 'READY', 'FAILED')", name="status"),
        sa.CheckConstraint(
            "status != 'READY' OR (normalized_object_key IS NOT NULL AND "
            "schema_json IS NOT NULL AND profile_json IS NOT NULL AND "
            "preview_json IS NOT NULL AND row_count IS NOT NULL AND completed_at IS NOT NULL)",
            name="ready_metadata",
        ),
        sa.CheckConstraint(
            "status != 'FAILED' OR (error_code IS NOT NULL AND "
            "error_message IS NOT NULL AND completed_at IS NOT NULL)", name="failed_error",
        ),
    )
    # Database enforcement also covers workers and scripts that bypass the ORM.
    op.execute("""
        CREATE FUNCTION protect_dataset_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'READY' AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'READY dataset versions are immutable';
            END IF;
            IF ROW(NEW.id, NEW.dataset_id, NEW.version_number, NEW.storage_bucket,
                   NEW.original_object_key, NEW.original_filename, NEW.file_format, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.dataset_id, OLD.version_number, OLD.storage_bucket,
                   OLD.original_object_key, OLD.original_filename, OLD.file_format, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Dataset version identity and source are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER dataset_version_immutable BEFORE UPDATE ON dataset_versions
        FOR EACH ROW EXECUTE FUNCTION protect_dataset_version()
    """)


def downgrade():
    op.drop_table("dataset_versions")
    op.execute("DROP FUNCTION protect_dataset_version()")
    op.drop_table("datasets")
