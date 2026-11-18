"""add engine benchmark to model versions

Revision ID: b7e2d4f8a1c3
Revises: a3f1c9e7d2b4
Create Date: 2026-11-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'b7e2d4f8a1c3'
down_revision: str | None = 'a3f1c9e7d2b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'model_versions',
        sa.Column('benchmark', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('model_versions', 'benchmark')
