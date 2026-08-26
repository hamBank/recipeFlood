"""add cook list recipe completed flag

Per-recipe version of 35c714c83663's list-level flag: tick a recipe off
a cooking list once it's been made, without deleting the plan. Display-
only — see CookListRecipe's docstring — so no backfill is needed, unlike
the list-level flag's import-batch backfill.

Plain boolean, same reasoning as 35c714c83663: server_default carries the
NOT NULL through existing rows on both dialects, no dual-dialect ALTER
TYPE handling needed.

Revision ID: a3783b13f0ff
Revises: 35c714c83663
Create Date: 2026-08-26 00:39:27.780142

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3783b13f0ff'
down_revision: Union[str, Sequence[str], None] = '35c714c83663'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "cooklistrecipe",
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("cooklistrecipe", "completed")
