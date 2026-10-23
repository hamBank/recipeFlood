"""add user shopping_edit_default_shop

A per-user switch for the shopping list's "Edit default shops" mode,
which shows a shop picker on each line that changes the pantry
ingredient's own `source`. Stored on the user, like
shopping_show_ticked, so it follows them across reloads and devices.

Plain boolean with a server_default, same reasoning as 326d0f450982.

Revision ID: d7b2e5a1c9f4
Revises: c4e1a9f2b6d3
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b2e5a1c9f4'
down_revision: Union[str, Sequence[str], None] = 'c4e1a9f2b6d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "user",
        sa.Column(
            "shopping_edit_default_shop", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user", "shopping_edit_default_shop")
