"""MySQL-only active-rule uniqueness; no business data rewrite.

Initial revisions now compile correctly for pristine MySQL databases. Existing
SQLite/PostgreSQL schemas only advance the revision marker. A nonconforming
existing MySQL schema is refused instead of silently changing text comparisons.
"""
from alembic import op, context
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != 'mysql':
        return
    if not context.is_offline_mode():
        connection = op.get_bind()
        incompatible = connection.execute(sa.text("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name != 'alembic_version'
              AND data_type = 'varchar'
              AND (character_maximum_length < 255 OR collation_name != 'utf8mb4_0900_bin')
        """)).scalar()
        if incompatible:
            raise RuntimeError('Existing MySQL text definitions need a separate reviewed migration; no automatic conversion')
        duplicate = connection.execute(sa.text('SELECT 1 FROM rules WHERE active = 1 GROUP BY scope, scope_code HAVING COUNT(*) > 1 LIMIT 1')).first()
        if duplicate:
            raise RuntimeError('Multiple active rules exist; review them before adding the constraint')
    # MySQL 8.4 functional key: NULL allows multiple inactive revisions.
    op.execute('CREATE UNIQUE INDEX uq_rules_active_scope_mysql ON rules (scope, scope_code, (CASE WHEN active = 1 THEN 1 ELSE NULL END))')
    op.drop_index('ix_rules_active_scope', table_name='rules')


def downgrade():
    if op.get_bind().dialect.name == 'mysql':
        op.create_index('ix_rules_active_scope', 'rules', ['scope','scope_code'], unique=False)
        op.drop_index('uq_rules_active_scope_mysql', table_name='rules')
