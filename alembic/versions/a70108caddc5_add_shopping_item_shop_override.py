"""add shopping item shop override

A one-off "not from the usual place this time" per shopping-list line,
independent of the linked ingredient's own `source` — see ShoppingItem's
docstring. Nullable with no default: null means "follow the pantry",
which is every existing row's actual behavior today, so backfilling
anything here would be inventing data.

Revision ID: a70108caddc5
Revises: a3783b13f0ff
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a70108caddc5"
down_revision: Union[str, Sequence[str], None] = "a3783b13f0ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shoppingitem",
        sa.Column(
            "shop_override",
            sa.Enum(
                "markets", "supermarket", "butcher", "nut_shop", "deli",
                "asian_grocery", "fishmonger", "bakery", "bottle_shop",
                "cake_supplies", "chemist", "hardware", "newsagent", "other",
                name="ingredientsource", native_enum=False, length=32,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("shoppingitem", "shop_override")
