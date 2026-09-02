"""initial schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-02 22:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Sources table
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=False, server_default='telegram'),
        sa.Column('chat_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sources_chat_id'), 'sources', ['chat_id'], unique=False)

    # 2. Promotions table
    op.create_table(
        'promotions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='telegram'),
        sa.Column('source_message_id', sa.String(length=100), nullable=True),
        sa.Column('source_chat_id', sa.String(length=100), nullable=True),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('product_name', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('original_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('sale_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('discount_percentage', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('store', sa.String(length=100), nullable=True),
        sa.Column('product_id', sa.String(length=100), nullable=True),
        sa.Column('original_url', sa.Text(), nullable=False),
        sa.Column('affiliate_url', sa.Text(), nullable=True),
        sa.Column('image_url', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('filter_reason', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_promotions_source_chat_id'), 'promotions', ['source_chat_id'], unique=False)
    op.create_index(op.f('ix_promotions_store'), 'promotions', ['store'], unique=False)
    op.create_index(op.f('ix_promotions_product_id'), 'promotions', ['product_id'], unique=False)
    op.create_index(op.f('ix_promotions_category'), 'promotions', ['category'], unique=False)
    op.create_index(op.f('ix_promotions_status'), 'promotions', ['status'], unique=False)
    op.create_index(op.f('ix_promotions_content_hash'), 'promotions', ['content_hash'], unique=False)
    op.create_index(op.f('ix_promotions_created_at'), 'promotions', ['created_at'], unique=False)

    # 3. Promotion Sources (duplicate tracker)
    op.create_table(
        'promotion_sources',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('promotion_id', sa.Integer(), nullable=False),
        sa.Column('source_chat_id', sa.String(length=100), nullable=False),
        sa.Column('source_message_id', sa.String(length=100), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_promotion_sources_promotion_id'), 'promotion_sources', ['promotion_id'], unique=False)

    # 4. Affiliate Links
    op.create_table(
        'affiliate_links',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('promotion_id', sa.Integer(), nullable=True),
        sa.Column('store', sa.String(length=100), nullable=False),
        sa.Column('original_url', sa.Text(), nullable=False),
        sa.Column('affiliate_url', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # 5. Publications
    op.create_table(
        'publications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('promotion_id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=False, server_default='telegram'),
        sa.Column('target_chat_id', sa.String(length=100), nullable=False),
        sa.Column('target_message_id', sa.String(length=100), nullable=True),
        sa.Column('formatted_content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='published'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['promotion_id'], ['promotions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_publications_promotion_id'), 'publications', ['promotion_id'], unique=False)

    # 6. Filters
    op.create_table(
        'filters',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rule_name', sa.String(length=100), nullable=False),
        sa.Column('rule_type', sa.String(length=50), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rule_name')
    )

    # 7. Settings
    op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_settings_key'), 'settings', ['key'], unique=True)


def downgrade() -> None:
    op.drop_table('settings')
    op.drop_table('filters')
    op.drop_table('publications')
    op.drop_table('affiliate_links')
    op.drop_table('promotion_sources')
    op.drop_table('promotions')
    op.drop_table('sources')
