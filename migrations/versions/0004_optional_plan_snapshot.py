"""Allow a plan to be recorded before warehouse data is available."""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def set_snapshot_nullable(nullable):
    column_type = sa.String().with_variant(
        mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
    with op.batch_alter_table('versions') as batch:
        batch.alter_column('snapshot_id', existing_type=column_type, nullable=nullable)


def upgrade():
    set_snapshot_nullable(True)


def downgrade():
    if not context.is_offline_mode():
        pending = op.get_bind().execute(sa.text(
            'SELECT 1 FROM versions WHERE snapshot_id IS NULL LIMIT 1')).first()
        if pending:
            raise RuntimeError('存在未关联快照的计划版本，无法降级并保留这些记录')
    set_snapshot_nullable(False)
