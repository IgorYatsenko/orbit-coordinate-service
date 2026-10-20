"""remove unused token version

Revision ID: 799211bd6412
Revises: b5aa8a165a05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "799211bd6412"
down_revision: str | Sequence[str] | None = "b5aa8a165a05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply schema changes."""
    op.drop_constraint(op.f("ck_users_token_version_nonnegative"), "users", type_="check")
    op.drop_column("users", "token_version")


def downgrade() -> None:
    """Revert schema changes."""
    op.add_column(
        "users",
        sa.Column("token_version", sa.INTEGER(), server_default=sa.text("0"), autoincrement=False, nullable=False),
    )
    op.create_check_constraint(op.f("ck_users_token_version_nonnegative"), "users", "token_version >= 0")
