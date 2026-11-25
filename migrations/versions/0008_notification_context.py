"""Link notifications to the plan version that produced them."""
from bisect import bisect_right
from collections import defaultdict
from hashlib import sha256
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def legacy_kind(payload):
    text = payload.get('text', '')
    if payload.get('reviewers'):
        return 'TRANSFERRED' if payload.get('recipient') else 'SUBMITTED'
    if text.endswith('行退回修改'):
        return 'RETURNED'
    if text.endswith('行审核提醒'):
        return 'REMINDER'
    if text.endswith(('已通过终审','复审完成，部分物料不批准','复审完成，全部物料不批准')):
        return 'FINALIZED'
    return 'GENERAL'


def mysql_backfill():
    # MySQL migrations are also distributed as standalone SQL. Both upgrade
    # modes execute these same updates against the installation's own records.
    batch_id = "JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.batch_id')) COLLATE utf8mb4_0900_bin"
    message = "JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.text'))"
    recipient = "JSON_EXTRACT(e.payload, '$.recipient')"
    kind = f"""CASE
        WHEN JSON_UNQUOTE(JSON_EXTRACT(e.payload,'$.reviewers')) IN ('true','1')
            THEN CASE WHEN JSON_TYPE({recipient})='STRING' AND JSON_UNQUOTE({recipient})<>''
                      THEN 'TRANSFERRED' ELSE 'SUBMITTED' END
        WHEN {message} LIKE '%行退回修改' THEN 'RETURNED'
        WHEN {message} LIKE '%行审核提醒' THEN 'REMINDER'
        WHEN {message} LIKE '%已通过终审' OR {message} LIKE '%复审完成，部分物料不批准'
             OR {message} LIKE '%复审完成，全部物料不批准' THEN 'FINALIZED'
        ELSE 'GENERAL' END"""
    version_at_event = f"""SELECT old.id FROM versions AS old
        WHERE old.batch_id={batch_id} AND old.created_at<=e.created_at
        ORDER BY old.created_at DESC,old.id DESC LIMIT 1"""
    op.execute(f"""UPDATE notifications AS n
        JOIN notification_events AS e ON n.batch_id={batch_id}
           AND BINARY n.text=BINARY {message}
           AND n.id=LEFT(SHA2(CONCAT(e.id,n.user_id),256),32)
        JOIN versions AS v ON v.id=({version_at_event})
        SET n.version_id=v.id,n.kind={kind},n.occurred_at=e.created_at""")
    op.execute(f"""UPDATE notification_events AS e
        JOIN versions AS v ON v.id=({version_at_event})
        SET e.payload=JSON_SET(e.payload,'$.kind',{kind},'$.version_id',v.id)
        WHERE e.state<>'DONE'""")


def upgrade():
    col = sa.String().with_variant(mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
    op.add_column('notifications', sa.Column('kind', col))
    op.add_column('notifications', sa.Column('version_id', col))
    op.add_column('notifications', sa.Column('occurred_at', col))
    op.create_index('ix_notice_inbox', 'notifications', ['user_id', 'created_at'])
    op.create_index('ix_notice_version', 'notifications', ['user_id', 'version_id'])
    if op.get_context().dialect.name == 'mysql':
        mysql_backfill()
        return
    conn = op.get_bind()
    events = sa.table('notification_events', sa.column('id',col), sa.column('created_at',col), sa.column('payload',sa.JSON), sa.column('state',col))
    versions = sa.table('versions', sa.column('id',col), sa.column('batch_id',col), sa.column('created_at',col))
    notices = sa.table('notifications', sa.column('id',col), sa.column('user_id',col), sa.column('batch_id',col),
                       sa.column('text',sa.Text), sa.column('kind',col), sa.column('version_id',col), sa.column('occurred_at',col))
    timelines = defaultdict(list)
    for batch_id, at, vid in conn.execute(sa.select(versions.c.batch_id, versions.c.created_at, versions.c.id).order_by(versions.c.created_at,versions.c.id)):
        if at and vid:
            timelines[batch_id].append((at,vid))
    recipients = defaultdict(set)
    for batch_id, text, user_id in conn.execute(sa.select(notices.c.batch_id, notices.c.text, notices.c.user_id).distinct()):
        recipients[(batch_id,text)].add(user_id)
    # Historical deliveries used sha256(event_id + recipient_id). A matching text
    # alone is insufficient when the same plan is submitted in consecutive rounds.
    for eid, at, payload, state in conn.execute(sa.select(events.c.id, events.c.created_at, events.c.payload, events.c.state)):
        if not at or not isinstance(payload,dict):
            continue
        batch_id = payload.get('batch_id')
        timeline = timelines.get(batch_id, [])
        pos = bisect_right(timeline,(at,chr(0x10ffff))) - 1
        if pos < 0:
            continue
        vid = timeline[pos][1]
        kind = legacy_kind(payload)
        ids = [sha256((eid+uid).encode()).hexdigest()[:32] for uid in recipients.get((batch_id,payload.get('text')), ())]
        if ids:
            conn.execute(notices.update().where(notices.c.id.in_(ids)).values(version_id=vid,kind=kind,occurred_at=at))
        # Queued events also need the original version when the worker resumes.
        if state != 'DONE':
            conn.execute(events.update().where(events.c.id==eid).values(payload={**payload,'kind':kind,'version_id':vid}))


def downgrade():
    op.drop_index('ix_notice_version',table_name='notifications')
    op.drop_index('ix_notice_inbox',table_name='notifications')
    with op.batch_alter_table('notifications') as table:
        table.drop_column('occurred_at')
        table.drop_column('version_id')
        table.drop_column('kind')
