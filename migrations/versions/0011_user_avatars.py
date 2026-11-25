"""Keep the saved avatar choice with its plan-review account."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    user_id = sa.String().with_variant(mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
    op.create_table('user_avatars',
                    sa.Column('user_id', user_id, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
                    sa.Column('preset', sa.String(16), nullable=False),
                    sa.Column('source', sa.String(32), nullable=False),
                    sa.Column('revision', sa.String(40), nullable=False),
                    sa.Column('config', sa.JSON(none_as_null=True), nullable=True))


def downgrade():
    op.drop_table('user_avatars')
