"""widen ingredient source, add is_food

Two changes to `ingredient`:

* `source` becomes a plain VARCHAR. It was a database ENUM of the seven
  shops I guessed at; importing a real shopping list added seven more, and
  that list will keep growing. Postgres needs ALTER TYPE ... ADD VALUE for
  each addition while SQLite needs a table rebuild, so every future shop
  would have meant a two-dialect migration. A string column plus the Python
  `IngredientSource` enum for validation costs one migration, now, and none
  after it.
* `is_food` marks the things that come home from the shops but never go in
  a recipe — batteries, shampoo, cat litter. Defaults true, so every
  existing row is unaffected.

Revision ID: 582b0dc46fca
Revises: 7ccf1b050bbf
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "582b0dc46fca"
down_revision: Union[str, Sequence[str], None] = "7ccf1b050bbf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_SOURCES = (
    "markets", "supermarket", "butcher", "nut_shop", "deli",
    "asian_grocery", "other",
)


def upgrade() -> None:
    # server_default so the NOT NULL holds for rows that already exist; the
    # column keeps it afterwards, which is what we want for new rows too.
    op.add_column(
        "ingredient",
        sa.Column("is_food", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(op.f("ix_ingredient_is_food"), "ingredient", ["is_food"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE ingredient ALTER COLUMN source TYPE VARCHAR USING source::text")
        op.execute("ALTER TABLE ingredient ALTER COLUMN source SET DEFAULT 'supermarket'")
        op.execute("DROP TYPE IF EXISTS ingredientsource")
    else:
        # SQLite stores the enum as VARCHAR plus a CHECK constraint; the only
        # way to drop that constraint is to rebuild the table, which
        # batch_alter_table does.
        with op.batch_alter_table("ingredient") as batch:
            batch.alter_column(
                "source",
                existing_type=sa.Enum(*OLD_SOURCES, name="ingredientsource"),
                type_=sa.String(),
                existing_nullable=False,
                server_default="supermarket",
            )


def downgrade() -> None:
    # Rows using one of the newly added shops have no old-enum equivalent,
    # so fold them into 'other' before narrowing the column back.
    placeholders = ", ".join(f"'{value}'" for value in OLD_SOURCES)
    op.execute(f"UPDATE ingredient SET source = 'other' WHERE source NOT IN ({placeholders})")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"CREATE TYPE ingredientsource AS ENUM ({placeholders})")
        # Postgres won't implicitly cast a column's DEFAULT expression when
        # changing its type — only the USING clause covers existing data,
        # not the default — so the plain VARCHAR default has to come off
        # before the type change and go back on after. (Found running the
        # downgrade against a real Postgres instance for a later migration
        # that copies this same shape — this one had never actually been
        # exercised down to here.)
        op.execute("ALTER TABLE ingredient ALTER COLUMN source DROP DEFAULT")
        op.execute(
            "ALTER TABLE ingredient ALTER COLUMN source TYPE ingredientsource "
            "USING source::ingredientsource"
        )
        op.execute("ALTER TABLE ingredient ALTER COLUMN source SET DEFAULT 'supermarket'")
    else:
        with op.batch_alter_table("ingredient") as batch:
            batch.alter_column(
                "source",
                existing_type=sa.String(),
                type_=sa.Enum(*OLD_SOURCES, name="ingredientsource"),
                existing_nullable=False,
            )

    op.drop_index(op.f("ix_ingredient_is_food"), table_name="ingredient")
    op.drop_column("ingredient", "is_food")
