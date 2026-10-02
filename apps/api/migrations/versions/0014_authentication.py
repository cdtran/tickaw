"""Add identities, sessions, and ownership; quarantine ownerless legacy records."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_table(
        "browser_sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_browser_sessions_user_id", "browser_sessions", ["user_id"])
    op.create_index("ix_browser_sessions_expires_at", "browser_sessions", ["expires_at"])
    op.create_table(
        "login_transactions",
        sa.Column("state_hash", sa.Text(), primary_key=True),
        sa.Column("browser_hash", sa.Text(), nullable=False),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_transactions_expires_at", "login_transactions", ["expires_at"])
    for table in ("datasets", "notebooks"):
        op.add_column(table, sa.Column("owner_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(None, table, "users", ["owner_id"], ["id"], ondelete="RESTRICT")
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])


def downgrade():
    for table in ("notebooks", "datasets"):
        op.drop_index(f"ix_{table}_owner_id", table_name=table)
        op.drop_constraint(f"fk_{table}_owner_id_users", table, type_="foreignkey")
        op.drop_column(table, "owner_id")
    op.drop_table("login_transactions")
    op.drop_table("browser_sessions")
    op.drop_table("users")
