"""add recipe image_generated

Marks a recipe's photo as an AI-generated illustration rather than a real
photo of the dish (scripts/generate_recipe_images.py) — see
backend/image_generation.py's docstring for why. Defaults false, so every
existing row (a real uploaded photo, a self-hosted blog image, or no
image at all) is unaffected.

Plain boolean, not an enum-like column, so this needs none of the
dual-dialect ALTER TYPE handling the enum-widening migrations do —
server_default carries the NOT NULL through existing rows on both
dialects.

Revision ID: 69956bf5c9bd
Revises: bfa3fe4647a1
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "69956bf5c9bd"
down_revision: Union[str, Sequence[str], None] = "bfa3fe4647a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recipe",
        sa.Column("image_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("recipe", "image_generated")
