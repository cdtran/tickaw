"""Remove unnecessary email storage; identity remains issuer and subject."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("users", "email")


def downgrade():
    # Removed emails cannot be restored. Empty placeholders support the old schema.
    op.add_column("users", sa.Column("email", sa.Text(), nullable=False, server_default=""))
    op.alter_column("users", "email", server_default=None)
