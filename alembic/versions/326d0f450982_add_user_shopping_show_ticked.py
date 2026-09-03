"""add user shopping_show_ticked

The shopping list's "Show ticked" checkbox used to live only in React
state, so it reset on every reload. Storing it on the user record lets
it persist across reloads (and devices) via PATCH /auth/me.

Plain boolean, same reasoning as 35c714c83663/a3783b13f0ff:
server_default carries the NOT NULL through existing rows on both
dialects, no dual-dialect ALTER TYPE handling needed.

Revision ID: 326d0f450982
Revises: a70108caddc5
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '326d0f450982'
down_revision: Union[str, Sequence[str], None] = 'a70108caddc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user",
        sa.Column("shopping_show_ticked", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user", "shopping_show_ticked")
