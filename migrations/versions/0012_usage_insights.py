"""Aggregate signed-in usage; retain only a short deduplication window for batches."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.String().with_variant(mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
    epoch = sa.Float().with_variant(mysql.DOUBLE(), 'mysql')
    op.create_table('usage_days',
        sa.Column('user_id', identity, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('day', sa.Date(), primary_key=True), sa.Column('views', sa.Integer(), nullable=False),
        sa.Column('clicks', sa.Integer(), nullable=False), sa.Column('friction', sa.Integer(), nullable=False))
    op.create_index('ix_usage_days_day', 'usage_days', ['day'])
    op.create_table('usage_metrics',
        sa.Column('user_id', identity, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('day', sa.Date(), primary_key=True), sa.Column('kind', sa.String(12), primary_key=True),
        sa.Column('page', sa.String(12), primary_key=True), sa.Column('device', sa.String(8), primary_key=True),
        sa.Column('target', sa.String(12), primary_key=True), sa.Column('cell', sa.Integer(), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False))
    op.create_index('ix_usage_metrics_day', 'usage_metrics', ['day'])
    op.create_table('usage_receipts', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('digest', sa.String(64), nullable=False), sa.Column('nonce', sa.String(32), nullable=False),
        sa.Column('expires', epoch, nullable=False))
    op.create_index('ix_usage_receipts_expires', 'usage_receipts', ['expires'])
    op.create_table('usage_presence',
        sa.Column('session_hash', identity, sa.ForeignKey('sessions.token_hash', ondelete='CASCADE'), primary_key=True),
        sa.Column('last_seen', epoch, nullable=False))
    op.create_index('ix_usage_presence_last_seen', 'usage_presence', ['last_seen'])


def downgrade():
    for table in ('usage_presence', 'usage_receipts', 'usage_metrics', 'usage_days'):
        op.drop_table(table)
