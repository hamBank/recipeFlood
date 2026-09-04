"""add prepared event cook_list_id

Links a PreparedEvent back to the CookList that auto-created it — set
only when a recipe joined a cooking list (see routers/cook_lists.py's
sync_prepared_event), null for anything logged by hand from the recipe
page. Nullable, no server_default needed: existing rows are all
hand-logged and correctly become NULL.

Revision ID: 03cfdcc9ce56
Revises: 326d0f450982
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '03cfdcc9ce56'
down_revision: Union[str, Sequence[str], None] = '326d0f450982'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Batch mode: SQLite can't ALTER TABLE ADD CONSTRAINT directly, and
    # batch mode's rebuild-the-table approach works on Postgres too.
    with op.batch_alter_table("preparedevent") as batch_op:
        batch_op.add_column(sa.Column("cook_list_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            op.f("ix_preparedevent_cook_list_id"), ["cook_list_id"]
        )
        batch_op.create_foreign_key(
            "fk_preparedevent_cook_list_id_cooklist",
            "cooklist",
            ["cook_list_id"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("preparedevent") as batch_op:
        batch_op.drop_constraint(
            "fk_preparedevent_cook_list_id_cooklist", type_="foreignkey"
        )
        batch_op.drop_index(op.f("ix_preparedevent_cook_list_id"))
        batch_op.drop_column("cook_list_id")
