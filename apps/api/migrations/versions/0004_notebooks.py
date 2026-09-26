"""Persist notebooks and questions pinned to dataset versions."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
            for name in ("created_at", "updated_at")]


def upgrade():
    op.create_table("notebooks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False), *timestamps(),
        sa.CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="title_length"))
    op.create_table("notebook_cells",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("notebook_id", sa.Uuid(), sa.ForeignKey("notebooks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), sa.ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'SAVED'"), nullable=False), *timestamps(),
        sa.CheckConstraint("length(btrim(question)) BETWEEN 1 AND 4000", name="question_length"),
        sa.CheckConstraint("status IN ('SAVED')", name="status"))
    for column in ("notebook_id", "dataset_version_id"):
        op.create_index(f"ix_notebook_cells_{column}", "notebook_cells", [column])


def downgrade():
    op.drop_table("notebook_cells")
    op.drop_table("notebooks")
