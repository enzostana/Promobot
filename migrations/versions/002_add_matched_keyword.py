"""add matched_keyword to promotions

Revision ID: 002_add_matched_keyword
Revises: 001_initial_schema
Create Date: 2026-09-14 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_add_matched_keyword'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('promotions', sa.Column('matched_keyword', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('promotions', 'matched_keyword')