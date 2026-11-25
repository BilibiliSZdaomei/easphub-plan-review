"""Snapshot workflow mail and its recipients in the plan transition transaction."""
import hashlib
from threading import Lock
import time
from sqlalchemy import case, select, update

from .account_email import notification_email
from .db import User, Warehouse, WorkflowMail
from .markets import market_key

_scan_lock = Lock()
_next_address_scan = 0.0
ADDRESS_SCAN_INTERVAL = 10
ADDRESS_RECHECK_SECONDS = 900


def recover_waiting_addresses(db,stamp,is_authorized):
    """Catch concurrent edits and externally imported addresses, without rescanning the entire outbox."""
    global _next_address_scan
    tick = time.monotonic()
    if tick < _next_address_scan or not _scan_lock.acquire(blocking=False):
        return
    try:
        if tick < _next_address_scan:
            return
        _next_address_scan = tick + ADDRESS_SCAN_INTERVAL
    finally:
        _scan_lock.release()

    mail = WorkflowMail
    waiting = (mail.state == 'WAITING_EMAIL', mail.next_attempt_at <= stamp)
    rows = db.execute(select(mail,User).join(User,User.id==mail.recipient_id).where(*waiting)
                      .order_by(mail.next_attempt_at,mail.id).limit(64)).all()
    for item,user in rows:
        if not is_authorized(user,item):
            changes = {'state':'CANCELLED','last_error':'ACCESS_REVOKED','destination':None,'next_attempt_at':0}
        else:
            address = notification_email(user)
            changes = ({'state':'QUEUED','destination':address,'next_attempt_at':0,'last_error':None} if address
                       else {'destination':None,'next_attempt_at':stamp + ADDRESS_RECHECK_SECONDS})
        db.execute(update(mail).where(mail.id == item.id,*waiting).values(**changes).execution_options(synchronize_session=False))
    # A just-recovered row can be leased in the same transaction. Re-read its state.
    if rows:
        db.expire_all()


def refresh_recipient_email(db,user):
    address = notification_email(user)
    pending = update(WorkflowMail).where(WorkflowMail.recipient_id == user.id,
                                        WorkflowMail.state.in_(('WAITING_EMAIL','QUEUED','RETRY')))
    if address:
        waiting = WorkflowMail.state == 'WAITING_EMAIL'
        # Keep a transport retry's existing backoff. Only a missing-address wait wakes immediately.
        pending = pending.ordered_values((WorkflowMail.next_attempt_at,case((waiting,0),else_=WorkflowMail.next_attempt_at)),
                                         (WorkflowMail.state,case((waiting,'QUEUED'),else_=WorkflowMail.state)),
                                         (WorkflowMail.destination,address))
    else:
        pending = pending.values(destination=None,next_attempt_at=0,state='WAITING_EMAIL')
    db.execute(pending.execution_options(synchronize_session=False))


def enqueue(db,event,kind,batch,version,actor,*,target=None,approved_count=0,rejected_count=0,flagged_count=0,reason=''):
    owner = db.get(User,batch.owner)
    if kind in ('SUBMITTED','RESUBMITTED','CLAIMED'):
        candidates = db.scalars(select(User).where(User.active.is_(True)))
        recipients = [u for u in candidates if 'REVIEWER' in u.roles and batch.warehouse in u.warehouses
                      and u.id not in (actor.id,batch.owner)]
    elif kind == 'TRANSFERRED':
        # The transition already validated eligibility, including an explicitly assigned admin.
        recipients = [target]
    elif kind in ('RETURNED','APPROVED','REJECTED'):
        recipients = [owner] if owner.active and batch.warehouse in owner.warehouses else []
    else:
        raise ValueError('Unknown plan workflow event')
    if not recipients:
        return
    warehouse = db.get(Warehouse,batch.warehouse)
    snapshot = {'kind':kind,'plan_number':batch.number,'plan_title':batch.title,'period':batch.period,
                'warehouse_code':warehouse.code,'warehouse_name':warehouse.name,'market':market_key(warehouse.market),
                'batch_id':batch.id,'version_id':version.id,'version_no':version.seq,'state':batch.state,
                'actor_id':actor.id,'actor_name':actor.name,'owner_name':owner.name,'occurred_at':event.created_at,
                'row_count':len(version.items),'approved_count':approved_count,'rejected_count':rejected_count,
                'flagged_count':flagged_count,'reason':reason}
    for user in recipients:
        address = notification_email(user)
        key = hashlib.sha256(f'{event.id}/{user.id}'.encode()).hexdigest()
        db.add(WorkflowMail(id=key,event_id=event.id,recipient_id=user.id,kind=kind,warehouse=warehouse.code,
                            batch_id=batch.id,version_id=version.id,destination=address,created_at=event.created_at,
                            payload={**snapshot,'recipient_name':user.name},state='QUEUED' if address else 'WAITING_EMAIL'))
