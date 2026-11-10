"""add ingredient.prep_terms

Per-ingredient preparation words ("juice", "zest" for a lemon; "boneless",
"fillet" for a chicken thigh). A recipe line whose extra words are all listed
here is the same purchase as the ingredient, and the words move to the line's
note. A JSON list like `aliases`.

Existing rows are backfilled with an empty list, so nothing changes until
someone adds terms.

Revision ID: a9d4c7e2b1f6
Revises: e8c3f1a7b2d5
Create Date: 2026-11-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d4c7e2b1f6'
down_revision: Union[str, Sequence[str], None] = 'e8c3f1a7b2d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ingredient", sa.Column("prep_terms", sa.JSON(), nullable=True))
    op.execute("UPDATE ingredient SET prep_terms = '[]'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("ingredient", "prep_terms")
