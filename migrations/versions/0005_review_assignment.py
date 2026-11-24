"""Store the active reviewer and the name used for this review version."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    column_type = sa.String().with_variant(
        mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
    with op.batch_alter_table('versions') as batch:
        batch.add_column(sa.Column('reviewer_id', column_type, nullable=True))
        batch.add_column(sa.Column('reviewer_name', column_type, nullable=True))


def downgrade():
    with op.batch_alter_table('versions') as batch:
        batch.drop_column('reviewer_name')
        batch.drop_column('reviewer_id')
