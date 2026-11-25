"""A recipient's inbox, with actions resolved against live assignment and plan access."""
from datetime import datetime, timezone
from sqlalchemy import and_, case, false, func, or_, select, update
from sqlalchemy.orm import aliased
from . import services as svc
from .auth import scope
from .roles import has_role
from .db import Batch, Notification as Note, User, Version, Warehouse, now


KINDS = {'SUBMITTED','TRANSFERRED','RETURNED','CLAIMED','FINALIZED','REMINDER','GENERAL'}
ACTION_KINDS = ('SUBMITTED','TRANSFERRED','RETURNED','REMINDER')


def display_notice(text, kind, batch_state):
    # Preserve the stored message. Older finished plans keep their original review trail.
    suffix = ' 复审完成，部分物料不批准'
    if batch_state == 'PARTIALLY_APPROVED' and kind in ('FINALIZED', 'GENERAL', None) and text.endswith(suffix):
        return text[:-len(suffix)] + ' 历史结案（旧规则）'
    return text


def accessible(db,user):
    return (Note.user_id == user.id, Note.warehouse == Batch.warehouse, svc.visible_batch_filter(db,user))


def inbox_rows(db,user,warehouse='',kind=''):
    if warehouse:
        scope(user,warehouse)
    svc.demand(isinstance(kind,str) and (not kind or kind in KINDS),'通知类别无效')
    current = aliased(Version)
    following = aliased(Note)
    event_time=func.coalesce(Note.occurred_at,Note.created_at)
    following_time=func.coalesce(following.occurred_at,following.created_at)
    newer = select(following.id).where(
        following.user_id==Note.user_id, following.version_id==Note.version_id,
        following.kind.in_(ACTION_KINDS),
        or_(following_time>event_time,and_(following_time==event_time,following.id>Note.id))
    ).correlate(Note).exists()
    live = and_(Note.version_id==Batch.current_id, ~newer)
    edit = and_(live, Batch.owner==user.id,
                or_(and_(Note.kind=='RETURNED',Batch.state=='RETURNED'),
                    and_(Note.kind=='REMINDER',Batch.state=='DRAFT')))
    outcomes = [(edit,'EDIT')]
    if has_role(user,'REVIEWER'):
        review = and_(live, Note.kind.in_(('SUBMITTED','TRANSFERRED')),
                      Batch.owner!=user.id,Batch.state.in_(svc.ACTIVE_REVIEW_STATES))
        # An assignee that lost the reviewer role or this warehouse releases the
        # task for a new claim, matching the workflow's assignment() contract.
        by_warehouse = {}
        for candidate in db.execute(select(User.id,User.roles,User.warehouses).where(User.active.is_(True))):
            if has_role(candidate,'REVIEWER'):
                for code in set(candidate.warehouses).intersection(user.warehouses):
                    by_warehouse.setdefault(code,[]).append(candidate.id)
        valid_holder = or_(false(),*(and_(Batch.warehouse==w,current.reviewer_id.in_(ids)) for w,ids in by_warehouse.items()))
        outcomes.extend([(and_(review,current.reviewer_id==user.id),'REVIEW'),
                         (and_(review,or_(current.reviewer_id.is_(None),~valid_holder)),'CLAIM')])
    kind_value = func.coalesce(Note.kind,'GENERAL')
    query = select(
        Note.id, Note.batch_id, Note.warehouse, Warehouse.name.label('warehouse_name'),
        Batch.title, Batch.number, Batch.state, current.reviewer_name,
        Note.text, Note.seen, event_time.label('at'), Note.created_at.label('delivered_at'), kind_value.label('kind'),
        case(*outcomes,else_=None).label('action')
    ).select_from(Note).join(Batch,Batch.id==Note.batch_id).join(current,current.id==Batch.current_id
    ).join(Warehouse,Warehouse.code==Batch.warehouse).where(*accessible(db,user))
    if warehouse:
        query=query.where(Note.warehouse==warehouse)
    if kind:
        query=query.where(kind_value==kind)
    return query.subquery()


def tab_filter(rows,tab):
    svc.demand(isinstance(tab,str) and tab in ('all','unread','action'),'通知筛选无效')
    return {'all':True,'unread':rows.c.seen.is_(False),'action':rows.c.action.is_not(None)}[tab]


def inbox(db,user,tab='all',warehouse='',kind='',page=1,size=20):
    rows=inbox_rows(db,user,warehouse,kind)
    before=now()
    visible=rows.c.delivered_at<=before
    all_count,unread,action,action_unread=db.execute(select(func.count(),func.count(case((rows.c.seen.is_(False),1))),
        func.count(rows.c.action),func.count(case((and_(rows.c.action.is_not(None),rows.c.seen.is_(False)),1)))).select_from(rows).where(visible)).one()
    counts={'all':all_count,'unread':unread,'action':action}
    condition=tab_filter(rows,tab)
    total=counts[tab]
    page=max(1,min(page,(total+size-1)//size))
    result=db.execute(select(rows).where(visible,condition).order_by(rows.c.at.desc(),rows.c.id.desc())
                      .offset((page-1)*size).limit(size)).mappings().all()
    items = [{**r, 'text':display_notice(r['text'],r['kind'],r['state'])} for r in result]
    return {'items':items,'counts':counts,'page':page,'size':size,'total':total,'unread_in_filter':action_unread if tab=='action' else unread,'before':before}


def mark(db,user,note_id):
    note=db.scalar(select(Note).join(Batch,Batch.id==Note.batch_id)
                   .where(*accessible(db,user),Note.id==note_id).with_for_update())
    svc.demand(note is not None,'通知不存在或访问权限已变更',404)
    note.seen=True
    return {'ok':True}


def mark_filtered(db,user,tab,warehouse,kind,before):
    rows=inbox_rows(db,user,warehouse,kind)
    try:
        cutoff=datetime.fromisoformat(before) if isinstance(before,str) else None
        valid=cutoff is not None and cutoff.tzinfo is not None and cutoff<=datetime.fromisoformat(now())
    except (ValueError,TypeError):
        valid=False
    svc.demand(valid,'通知范围已变化，请刷新')
    before=cutoff.astimezone(timezone.utc).isoformat()
    ids=list(db.scalars(select(rows.c.id).where(rows.c.seen.is_(False),rows.c.delivered_at<=before,tab_filter(rows,tab))))
    count=0
    for start in range(0,len(ids),400):
        count+=db.execute(update(Note).where(Note.id.in_(ids[start:start+400]),Note.user_id==user.id,
                                            Note.seen.is_(False)).values(seen=True)).rowcount
    return {'count':count}
