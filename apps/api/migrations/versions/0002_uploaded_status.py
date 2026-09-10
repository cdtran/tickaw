"""Distinguish a stored original from a profiled, analysis-ready version."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_dataset_versions_status"), "dataset_versions", type_="check")
    op.create_check_constraint(
        "status", "dataset_versions",
        "status IN ('UPLOADING', 'UPLOADED', 'PROCESSING', 'READY', 'FAILED')",
    )
    op.create_check_constraint(
        "uploaded_size", "dataset_versions", "status != 'UPLOADED' OR (size_bytes IS NOT NULL AND size_bytes > 0)",
    )


def downgrade():
    # Refuse downgrade when stored originals would lose their lifecycle meaning.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM dataset_versions WHERE status = 'UPLOADED') THEN
            RAISE EXCEPTION 'Cannot downgrade while UPLOADED versions exist';
        END IF;
    END $$""")
    op.drop_constraint(op.f("ck_dataset_versions_uploaded_size"), "dataset_versions", type_="check")
    op.drop_constraint(op.f("ck_dataset_versions_status"), "dataset_versions", type_="check")
    op.create_check_constraint(
        "status", "dataset_versions", "status IN ('UPLOADING', 'PROCESSING', 'READY', 'FAILED')",
    )
