"""store instants as timestamptz

sqlmodel 0.0.45+ maps a plain `datetime` field to a timezone-aware type
(`timestamp with time zone` on Postgres), which is why requirements.txt
capped it below 0.0.45: `alembic check` flagged every timestamp column.
Every datetime column here is an instant (`utcnow()` writes aware UTC), so
the columns become timestamptz and the cap goes.

No `USING` clause on purpose. psycopg2 sends an aware datetime as a
timestamptz, and Postgres stores that in a plain `timestamp` column as the
wall-clock time in the session's TimeZone (checked: 04:52 UTC written with
the server in Australia/Melbourne is stored as 15:52). Postgres's own
timestamp -> timestamptz cast reads a value in that same session TimeZone,
so it recovers the original instant whatever zone the server runs in, and
the downgrade cast is its exact inverse.

SQLite has no column types to change, so this is a no-op there.

Revision ID: e8c3f1a7b2d5
Revises: d7b2e5a1c9f4
Create Date: 2026-11-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8c3f1a7b2d5'
down_revision: Union[str, Sequence[str], None] = 'd7b2e5a1c9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (table, column, nullable) for every datetime column.
COLUMNS = [
    ("cooklist", "created_at", False),
    ("cooklist", "updated_at", False),
    ("ingredient", "cost_updated_at", True),
    ("ingredient", "nutrition_updated_at", True),
    ("ingredient", "created_at", False),
    ("ingredient", "updated_at", False),
    ("preparedevent", "created_at", False),
    ("recipe", "added_date", False),
    ("recipe", "created_at", False),
    ("recipe", "updated_at", False),
    ("sheetpendingdelete", "created_at", False),
    ("shoppingitem", "checked_at", True),
    ("shoppingitem", "added_at", False),
    ("user", "created_at", False),
]


def _retype(to_aware: bool) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=not to_aware),
            type_=sa.DateTime(timezone=to_aware),
            existing_nullable=nullable,
        )


def upgrade() -> None:
    """Upgrade schema."""
    _retype(to_aware=True)


def downgrade() -> None:
    """Downgrade schema."""
    _retype(to_aware=False)
