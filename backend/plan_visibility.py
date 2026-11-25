"""The same plan scope applies to history, direct links, files and notifications."""
from sqlalchemy import and_, func, or_, select

from .db import Audit, Batch, Version
from .roles import has_role

REVIEWED_STATES = ('IN_REVIEW', 'RETURNED', 'APPROVED', 'PARTIALLY_APPROVED', 'REJECTED')
REVIEW_ACTIONS = ('领取复审', '转交复审', '保存行复审', '退回修改', '完成终审')


def recorded_decision(db, reviewer_id):
    """Older versions can have line decisions without a version-level assignment."""
    if db.get_bind().dialect.name == 'mysql':
        if reviewer_id is None:
            return func.json_search(Version.items, 'one', '%', None, '$[*].decision.status').is_not(None)
        candidate = func.json_object('decision', func.json_object('reviewer_id', reviewer_id))
        return func.json_contains(Version.items, candidate) == 1

    rows = func.json_each(Version.items).table_valued('value')
    field = '$.decision.status' if reviewer_id is None else '$.decision.reviewer_id'
    value = func.json_extract(rows.c.value, field)
    matches = value.is_not(None) if reviewer_id is None else value == reviewer_id
    return select(1).select_from(rows).where(matches).correlate(Version).exists()


def review_involvement(db, reviewer_id=None):
    by_version = Version.reviewer_id == reviewer_id if reviewer_id is not None else or_(
        Version.reviewer_id.is_not(None), Version.state.in_(REVIEWED_STATES), Version.finalized_at.is_not(None))
    versions = select(1).select_from(Version).where(
        Version.batch_id == Batch.id, or_(by_version, recorded_decision(db, reviewer_id)))
    events = select(1).select_from(Audit).where(Audit.batch_id == Batch.id, Audit.action.in_(REVIEW_ACTIONS))
    if reviewer_id is not None:
        events = events.where(or_(Audit.user_id == reviewer_id,
                                  and_(Audit.action == '转交复审', Audit.detail['reviewer_id'].as_string() == reviewer_id)))
    return or_(events.correlate(Batch).exists(), versions.correlate(Batch).exists())


def visible_batch_filter(db, user):
    warehouses = Batch.warehouse.in_(user.warehouses)
    own = Batch.owner == user.id
    if not has_role(user, 'REVIEWER'):
        return and_(warehouses, own)

    admin = has_role(user, 'ADMIN')
    shared = Batch.state != 'VOID' if admin else Batch.state.in_(('SUBMITTED', *REVIEWED_STATES))
    void_history = and_(Batch.state == 'VOID', review_involvement(db, None if admin else user.id))
    return and_(warehouses, or_(own, shared, void_history))
