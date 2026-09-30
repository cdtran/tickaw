"""Bind question submissions to durable idempotency keys."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notebook_cells",
        sa.Column(
            "idempotency_key",
            sa.Uuid(),
            nullable=True,
            comment="Client request identity used to safely replay question submission.",
        ),
    )
    op.add_column(
        "notebook_cells",
        sa.Column(
            "idempotency_request_sha256",
            sa.Text(),
            nullable=True,
            comment="Fingerprint of the request bound to the idempotency key.",
        ),
    )
    op.create_check_constraint(
        "idempotency_hash",
        "notebook_cells",
        "idempotency_request_sha256 IS NULL OR length(idempotency_request_sha256) = 64",
    )
    op.create_unique_constraint(
        "notebook_idempotency_key", "notebook_cells", ["notebook_id", "idempotency_key"]
    )


def downgrade():
    op.drop_constraint("notebook_idempotency_key", "notebook_cells", type_="unique")
    op.drop_constraint("idempotency_hash", "notebook_cells", type_="check")
    op.drop_column("notebook_cells", "idempotency_request_sha256")
    op.drop_column("notebook_cells", "idempotency_key")
