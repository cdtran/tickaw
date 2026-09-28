"""Pin each submitted question to a stable model selection."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notebook_cells",
        sa.Column(
            "stable_model_id",
            sa.Text(),
            nullable=False,
            server_default="qwen-local",
            comment="Stable model configuration selected when the question was submitted.",
        ),
    )
    op.alter_column("notebook_cells", "stable_model_id", server_default=None)


def downgrade():
    op.drop_column("notebook_cells", "stable_model_id")
