"""add recipe source_page and web import source

Two changes to `recipe`:

* `source_page` — a page number for a recipe cited from a book or
  magazine rather than a URL ("Plenty More", page 133). Plain additive
  column.
* `import_source` becomes a plain VARCHAR, same reasoning and same
  technique as `582b0dc46fca` (widen ingredient source): it was a
  Postgres-native ENUM of four fixed values, and adding `web` (recipes
  fetched from someone else's site via the cooking-history CSV import)
  needs `ALTER TYPE ... ADD VALUE` on Postgres and a table rebuild on
  SQLite — a two-dialect migration for every future import source. A
  string column plus the Python `ImportSource` enum for validation costs
  one migration, now, and none after it.

Revision ID: bfa3fe4647a1
Revises: 9f515fcf77aa
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "bfa3fe4647a1"
down_revision: Union[str, Sequence[str], None] = "9f515fcf77aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_SOURCES = ("manual", "blog", "ai_image", "ai_paste")


def upgrade() -> None:
    op.add_column("recipe", sa.Column("source_page", sa.Integer(), nullable=True))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE recipe ALTER COLUMN import_source TYPE VARCHAR USING import_source::text"
        )
        op.execute("ALTER TABLE recipe ALTER COLUMN import_source SET DEFAULT 'manual'")
        op.execute("DROP TYPE IF EXISTS importsource")
    else:
        # SQLite stores the enum as VARCHAR plus a CHECK constraint; the only
        # way to drop that constraint is to rebuild the table, which
        # batch_alter_table does. Without this, 'web' would still be
        # rejected by the old 4-value CHECK left behind by a plain
        # alter_column.
        with op.batch_alter_table("recipe") as batch:
            batch.alter_column(
                "import_source",
                existing_type=sa.Enum(*OLD_SOURCES, name="importsource"),
                type_=sa.String(),
                existing_nullable=False,
                server_default="manual",
            )


def downgrade() -> None:
    # Recipes imported as 'web' have no old-enum equivalent; fold them into
    # 'manual' before narrowing the column back.
    placeholders = ", ".join(f"'{value}'" for value in OLD_SOURCES)
    op.execute(
        f"UPDATE recipe SET import_source = 'manual' WHERE import_source NOT IN ({placeholders})"
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"CREATE TYPE importsource AS ENUM ({placeholders})")
        # Postgres won't implicitly cast a column's DEFAULT expression when
        # changing its type — only the USING clause covers existing data,
        # not the default — so the plain VARCHAR default has to come off
        # before the type change and go back on after.
        op.execute("ALTER TABLE recipe ALTER COLUMN import_source DROP DEFAULT")
        op.execute(
            "ALTER TABLE recipe ALTER COLUMN import_source TYPE importsource "
            "USING import_source::importsource"
        )
        op.execute("ALTER TABLE recipe ALTER COLUMN import_source SET DEFAULT 'manual'")
    else:
        with op.batch_alter_table("recipe") as batch:
            batch.alter_column(
                "import_source",
                existing_type=sa.String(),
                type_=sa.Enum(*OLD_SOURCES, name="importsource"),
                existing_nullable=False,
            )

    op.drop_column("recipe", "source_page")
