"""Create an empty transactional outbox for future plan workflow transitions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    identity = sa.String().with_variant(mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
    epoch = sa.Float().with_variant(mysql.DOUBLE(), 'mysql')
    op.add_column('users', sa.Column('email', sa.String(254), nullable=True))
    op.create_table('workflow_mail',
        sa.Column('id',sa.String(64),primary_key=True), sa.Column('event_id',sa.String(32),nullable=False),
        sa.Column('recipient_id',identity,sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('kind',sa.String(16),nullable=False), sa.Column('warehouse',identity,nullable=False),
        sa.Column('batch_id',identity,nullable=False), sa.Column('version_id',identity,nullable=False),
        sa.Column('destination',sa.String(254)), sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('state',sa.String(20),nullable=False), sa.Column('attempts',sa.Integer(),nullable=False),
        sa.Column('next_attempt_at',epoch,nullable=False), sa.Column('lease_until',epoch,nullable=False),
        sa.Column('lease_token',sa.String(64)), sa.Column('last_error',sa.Text()),
        sa.Column('created_at',identity,nullable=False), sa.Column('sent_at',identity))
    op.create_index('ix_workflow_mail_due','workflow_mail',['state','next_attempt_at'])
    op.create_index('ix_workflow_mail_lease','workflow_mail',['state','lease_until'])
    op.create_index('ix_workflow_mail_recipient','workflow_mail',['recipient_id','state'])


def downgrade():
    op.drop_table('workflow_mail')
    op.drop_column('users','email')
