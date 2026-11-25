"""Keep reversible row edits within the current plan version."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    string = sa.String().with_variant(mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
    blob = sa.LargeBinary().with_variant(mysql.LONGBLOB(), 'mysql')
    op.create_table('plan_undo',
                    sa.Column('version_id', string, sa.ForeignKey('versions.id'), primary_key=True),
                    sa.Column('revision', sa.Integer(), primary_key=True),
                    sa.Column('actor_id', string, nullable=False),
                    sa.Column('label', string, nullable=False),
                    sa.Column('row_count', sa.Integer(), nullable=False),
                    sa.Column('payload', blob, nullable=False))


def downgrade():
    op.drop_table('plan_undo')

