"""Internal SMTP queue. Only delivery status is exposed by HTTP."""
import logging
import os
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.orm import aliased

from .account_email import notification_email
from .api_common import context
from .auth import role
from .db import User, WorkflowMail, now, transaction
from .roles import has_role
from .workflow_mail_templates import render_payload
from .workflow_outbox import recover_waiting_addresses
from .workflow_smtp import send_workflow_mail, smtp_enabled

router = APIRouter()
LEASE_SECONDS = 300
MAX_ATTEMPTS = 8
PENDING = ('QUEUED','RETRY','WAITING_EMAIL','RUNNING','SENDING')


def plan_link(batch_id):
    address = os.environ.get('PLAN_REVIEW_PUBLIC_URL', '').strip()
    if not address or any(c.isspace() for c in address) or not re.fullmatch('[0-9a-f]{32}', batch_id):
        return None
    try:
        url = urlsplit(address)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            return None
        return address.rstrip('/') + '/?' + urlencode({'plan':batch_id})
    except ValueError:
        return None


def still_authorized(person, mail):
    if not person or not person.active or mail.warehouse not in person.warehouses or not has_role(person,'PLANNER'):
        return False
    if mail.kind in ('SUBMITTED','RESUBMITTED','CLAIMED'):
        return 'REVIEWER' in person.roles
    if mail.kind == 'TRANSFERRED':
        return has_role(person,'REVIEWER')
    return True


def recipient_address(item, person):
    """Refresh a queued destination and close the reservation when it is undeliverable."""
    if not still_authorized(person,item):
        item.state='CANCELLED'
        item.last_error='ACCESS_REVOKED'
        item.destination=None
    else:
        item.destination=notification_email(person)
        if item.destination:
            return item.destination
        item.state='WAITING_EMAIL'
        item.last_error=None
    item.lease_until=0
    item.lease_token=None
    return None


def reserve_one():
    if not smtp_enabled():
        return None
    stamp = time.time()
    mail = WorkflowMail
    expired = and_(mail.state.in_(('RUNNING','SENDING')),mail.lease_until <= stamp)
    due = or_(and_(mail.state.in_(('QUEUED','RETRY')),mail.next_attempt_at <= stamp),expired)
    previous = aliased(mail)
    earlier = exists(select(previous.id).where(
        previous.batch_id == mail.batch_id, previous.recipient_id == mail.recipient_id, previous.state.in_(PENDING),
        or_(previous.created_at < mail.created_at, and_(previous.created_at == mail.created_at, previous.id < mail.id))))
    with transaction() as db:
        recover_waiting_addresses(db,stamp,still_authorized)
        item = db.scalar(select(mail).where(due,~earlier).order_by(mail.created_at,mail.id)
                         .limit(1).with_for_update(skip_locked=True))
        if item is None:
            return None
        token = secrets.token_urlsafe(24)
        # Include the observed lease in the compare-and-set: another worker can start DATA
        # or replace the lease between the candidate read and the write (especially on SQLite).
        match = (mail.id==item.id, mail.state==item.state, mail.lease_token==item.lease_token, due)
        if item.state=='SENDING' or item.attempts>=MAX_ATTEMPTS:
            db.execute(update(mail).where(*match).values(state='FAILED',lease_until=0,lease_token=None,
                       last_error='SMTP_UNCERTAIN' if item.state=='SENDING' else 'SMTP_TEMPORARY'))
            return None
        won = db.execute(update(mail).where(*match).values(state='RUNNING',lease_token=token,lease_until=stamp+LEASE_SECONDS))
        if not won.rowcount:
            return None
        address = recipient_address(item,db.get(User,item.recipient_id))
        if not address:
            return None
        try:
            content = render_payload(item.payload,plan_url=plan_link(item.batch_id))
        except (KeyError,TypeError,ValueError):
            item.state='FAILED'
            item.lease_until=0
            item.lease_token=None
            item.last_error='TEMPLATE_INVALID'
            return None
        item.attempts += 1
        return {'id':item.id,'kind':item.kind,'lease_token':token,'lease_until':stamp+LEASE_SECONDS,
                'message_id':'<'+item.id+'@mail.easphub.invalid>','to':address,
                'subject':content['subject'],'text':content['text'],'sender_name':content['sender_name']}


def mark_sending(message):
    """Commit the irreversible delivery boundary before the SMTP client sends DATA."""
    stamp = time.time()
    mail = WorkflowMail
    with transaction() as db:
        match = (mail.id==message['id'],mail.state=='RUNNING',mail.lease_token==message['lease_token'],mail.lease_until>stamp)
        recipient_id=db.scalar(select(mail.recipient_id).where(*match))
        if recipient_id is None:
            return False
        # Match account maintenance's lock order: account, then its pending mail.
        person = db.scalar(select(User).where(User.id==recipient_id).with_for_update())
        changed = db.execute(update(mail).where(*match).values(state='SENDING',lease_until=stamp+LEASE_SECONDS))
        if not changed.rowcount:
            return False
        item = db.get(mail,message['id'])
        address = recipient_address(item,person)
        if not address:
            item.attempts -= 1
            return False
        if address!=message['to']:
            item.attempts -= 1
            item.state='QUEUED'
            item.next_attempt_at=0
            item.lease_until=0
            item.lease_token=None
            return False
        return True


def settle(message,result,code=None):
    """Return the committed state, or None if the caller no longer owns this delivery."""
    if result not in ('sent','failed','retry'):
        raise ValueError('Unknown SMTP result')
    stamp=time.time()
    mail=WorkflowMail
    with transaction() as db:
        item=db.scalar(select(mail).where(mail.id==message['id']).with_for_update())
        if item is None or item.lease_token!=message['lease_token']:
            return None
        expected={'sent':'SENT','failed':'FAILED','retry':'RETRY'}[result]
        if result=='retry' and (code=='SMTP_UNCERTAIN' or item.attempts>=MAX_ATTEMPTS):
            expected='FAILED'
        if item.state==expected:
            return expected
        states=('SENDING',) if result=='sent' else ('RUNNING','SENDING')
        changed=db.execute(update(mail).where(mail.id==item.id,mail.state.in_(states),
                           mail.lease_token==message['lease_token'],mail.lease_until>stamp).values(
                           state=expected,lease_until=0,
                           next_attempt_at=(stamp+min(3600,30*2**min(item.attempts-1,7)) if expected=='RETRY' else 0),
                           sent_at=now() if expected=='SENT' else None,last_error=None if expected=='SENT' else (code or 'SMTP_TEMPORARY')))
        if changed.rowcount:
            return expected
        db.refresh(item,with_for_update=True)
        return expected if item.state==expected and item.lease_token==message['lease_token'] else None


def delivery_loop(stop):
    while not stop.is_set():
        try:
            item=reserve_one()
            if item is None:
                stop.wait(2)
                continue
            result,code=send_workflow_mail(item,before_data=lambda:mark_sending(item))
            settle(item,result,code)
        except Exception as exc:
            # The committed RUNNING/SENDING boundary determines whether a crash can retry.
            logging.getLogger(__name__).warning('Workflow mail worker failure: %s',type(exc).__name__)
            stop.wait(2)


@router.get('/mail-delivery/status')
def delivery_status(ctx=Depends(context,scope='function')):
    db,admin=ctx
    role(admin,'ADMIN')
    rows=db.execute(select(WorkflowMail.state,func.count()).where(WorkflowMail.warehouse.in_(admin.warehouses))
                    .group_by(WorkflowMail.state))
    return {'smtp_configured':smtp_enabled(),'counts':dict(rows.all())}
