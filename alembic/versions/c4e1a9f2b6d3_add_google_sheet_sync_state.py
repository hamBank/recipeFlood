"""add google sheet sync state

Adds the three sync-state flags to ShoppingItem (sheet_linked,
sheet_detached, sheet_dirty — see ShoppingItem's docstring) and the
SheetPendingDelete table, both for backend/sheet_sync.py. Plain booleans
with server_default — same reasoning as a3783b13f0ff and 35c714c83663 —
so every existing row is NOT NULL False on both dialects with no dual-
dialect handling needed: no existing shopping item has ever been synced,
so "not linked, not detached, not dirty" is simply true of all of them.

Revision ID: c4e1a9f2b6d3
Revises: 1207a6fb80c4
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c4e1a9f2b6d3"
down_revision: Union[str, Sequence[str], None] = "1207a6fb80c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shoppingitem",
        sa.Column("sheet_linked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "shoppingitem",
        sa.Column("sheet_detached", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "shoppingitem",
        sa.Column("sheet_dirty", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "sheetpendingdelete",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("item_id"),
    )


def downgrade() -> None:
    op.drop_table("sheetpendingdelete")
    op.drop_column("shoppingitem", "sheet_dirty")
    op.drop_column("shoppingitem", "sheet_detached")
    op.drop_column("shoppingitem", "sheet_linked")
