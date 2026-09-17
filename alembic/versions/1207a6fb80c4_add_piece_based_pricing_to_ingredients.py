"""add piece-based pricing to ingredients

Lets a pantry item be priced and shopped for per piece instead of by
weight or volume — eggs, a can of something, anything sold and priced
per item where forcing it through a weight guess just to get a cost
would be both unnecessary and a source of error. See
backend/models.py's MeasureKind and backend/costing.py's module
docstring.

Two additive, nullable columns. `measure_kind` itself needs no
migration to widen — it's a plain VARCHAR with no DB-level CHECK
constraint (create_constraint=False on the model's Column), the same
reason 9f515fcf77aa's addition of "volume" needed none either.

Revision ID: 1207a6fb80c4
Revises: 03cfdcc9ce56
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1207a6fb80c4'
down_revision: Union[str, Sequence[str], None] = '03cfdcc9ce56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ingredient', sa.Column('package_size_units', sa.Float(), nullable=True))
    op.add_column('ingredient', sa.Column('cost_per_unit_cents', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ingredient', 'cost_per_unit_cents')
    op.drop_column('ingredient', 'package_size_units')
