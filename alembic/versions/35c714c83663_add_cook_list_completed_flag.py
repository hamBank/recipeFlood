"""add cook list completed flag

Declutters the list screen rather than driving any other behavior — see
CookList's docstring. Backfills every existing cooking-history import
batch (description == 'Cooking history import') to completed=True in the
same migration, since those rows are already cooked, definitionally, and
would otherwise all show up as still-open work the first time the new
"show completed" filter ships.

Plain boolean, not an enum-like column — same reasoning as
69956bf5c9bd's image_generated: server_default carries the NOT NULL
through existing rows on both dialects, no dual-dialect ALTER TYPE
handling needed.

Revision ID: 35c714c83663
Revises: 69956bf5c9bd
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "35c714c83663"
down_revision: Union[str, Sequence[str], None] = "69956bf5c9bd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IMPORTED_DESCRIPTION = "Cooking history import"


def upgrade() -> None:
    op.add_column(
        "cooklist",
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    cooklist = sa.table(
        "cooklist",
        sa.column("description", sa.String()),
        sa.column("completed", sa.Boolean()),
    )
    op.execute(
        cooklist.update()
        .where(cooklist.c.description == _IMPORTED_DESCRIPTION)
        .values(completed=True)
    )


def downgrade() -> None:
    op.drop_column("cooklist", "completed")
