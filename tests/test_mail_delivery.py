"""Direct SMTP worker acceptance with synthetic accounts and no external mail."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
import time

import pytest
from sqlalchemy import select

from backend import mail_delivery as delivery, workflow_outbox, workflow_smtp
from backend.db import SessionLocal, User, WorkflowMail
from test_api import P, clients


@pytest.fixture
def relay(clients,monkeypatch):
    monkeypatch.setattr(delivery,'smtp_enabled',lambda:True)
    monkeypatch.setattr(workflow_outbox,'_next_address_scan',0)
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.username=='test_reviewer')).email='review@example.invalid'
    return clients


def queue(number, *, user='test_reviewer', plan=1, state='QUEUED', attempts=0):
    with SessionLocal.begin() as db:
        recipient = db.scalar(select(User).where(User.username==user))
        stamp = (datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=number)).isoformat()
        ident = f'{number:064x}'
        snapshot={'kind':'SUBMITTED','plan_number':f'PR-{plan}', 'plan_title':'Synthetic',
                  'market':'UK','warehouse_name':'UK Warehouse','warehouse_code':'UK_MAIN',
                  'period':'2026-11','row_count':1,'actor_name':'Planner'}
        db.add(WorkflowMail(id=ident,event_id=f'{number:032x}',recipient_id=recipient.id,kind='SUBMITTED',
                            warehouse='UK_MAIN',batch_id=f'{plan:032x}',version_id=f'{plan:032x}',
                            destination=recipient.email,payload=snapshot,state=state,attempts=attempts,created_at=stamp))
    return ident


def change(ident,**fields):
    with SessionLocal.begin() as db:
        for key,value in fields.items():
            setattr(db.get(WorkflowMail,ident),key,value)


def test_configuration_and_status_scope(relay,monkeypatch):
    planner,_,admin,_=relay
    ident=queue(1)
    assert planner.get(P+'/mail-delivery/status').status_code==403
    assert admin.get(P+'/mail-delivery/status').json()=={'smtp_configured':True,'counts':{'QUEUED':1}}
    monkeypatch.setattr(delivery,'smtp_enabled',lambda:False)
    assert delivery.reserve_one() is None
    with SessionLocal() as db:
        assert db.get(WorkflowMail,ident).attempts==0


def test_competing_workers_and_idempotent_ack(relay):
    ident=queue(1); barrier=Barrier(2)
    def compete(_):
        barrier.wait(timeout=5)
        return delivery.reserve_one()
    with ThreadPoolExecutor(max_workers=2) as pool:
        items=[item for item in pool.map(compete,range(2)) if item]
    assert len(items)==1
    first,=items
    change(ident,lease_until=time.time()-1)
    assert not delivery.mark_sending(first)
    assert delivery.settle(first,'retry') is None
    second=delivery.reserve_one()
    assert second['lease_token']!=first['lease_token'] and second['message_id']==first['message_id']
    assert delivery.settle(first,'sent') is None
    assert delivery.settle(second,'sent') is None  # no committed DATA boundary
    assert delivery.mark_sending(second) and not delivery.mark_sending(second)
    def acknowledge(_):
        barrier.wait(timeout=5)
        return delivery.settle(second,'sent')
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(acknowledge,range(2)))==['SENT','SENT']
    assert delivery.settle(second,'failed') is None
    assert delivery.reserve_one() is None


def test_order_per_recipient_and_plan_and_backoff(relay):
    first=queue(1); later=queue(2); independent=queue(3,plan=2)
    a=delivery.reserve_one(); b=delivery.reserve_one()
    assert [a['id'],b['id']]==[first,independent]
    assert delivery.settle(a,'retry','SMTP_TEMPORARY')=='RETRY'
    assert delivery.settle(a,'retry','SMTP_TEMPORARY')=='RETRY'
    assert delivery.mark_sending(b) and delivery.settle(b,'sent')=='SENT'
    assert delivery.reserve_one() is None
    change(first,next_attempt_at=0)
    retry=delivery.reserve_one()
    assert retry['id']==first and delivery.mark_sending(retry)
    assert delivery.settle(retry,'sent')=='SENT'
    assert delivery.reserve_one()['id']==later


def test_retry_cap_and_uncertain_data_are_terminal(relay):
    limit=delivery.MAX_ATTEMPTS
    ident=queue(1,attempts=limit-1)
    last=delivery.reserve_one()
    assert delivery.settle(last,'retry','SMTP_TEMPORARY')=='FAILED'
    assert delivery.settle(last,'retry','SMTP_TEMPORARY')=='FAILED'
    lost=queue(2,attempts=limit-1)
    held=delivery.reserve_one()
    change(lost,lease_until=time.time()-1)
    assert delivery.reserve_one() is None and delivery.settle(held,'sent') is None
    maybe_sent=queue(3)
    item=delivery.reserve_one()
    assert delivery.mark_sending(item)
    change(maybe_sent,lease_until=time.time()-1)
    assert delivery.reserve_one() is None and delivery.settle(item,'sent') is None
    with SessionLocal() as db:
        assert db.get(WorkflowMail,ident).attempts==limit
        assert db.get(WorkflowMail,lost).state=='FAILED' and db.get(WorkflowMail,lost).attempts==limit
        uncertain=db.get(WorkflowMail,maybe_sent)
        assert (uncertain.state,uncertain.attempts,uncertain.last_error)==('FAILED',1,'SMTP_UNCERTAIN')


def test_recheck_address_and_permissions_immediately_before_data(relay):
    ident=queue(1)
    first=delivery.reserve_one()
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.username=='test_reviewer')).email='updated@example.invalid'
    assert not delivery.mark_sending(first)
    assert delivery.settle(first,'retry') is None
    second=delivery.reserve_one()
    assert second['to']=='updated@example.invalid'
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.username=='test_reviewer')).warehouses=['ES_NSC']
    assert not delivery.mark_sending(second)
    with SessionLocal() as db:
        revoked=db.get(WorkflowMail,ident)
        assert revoked.state=='CANCELLED' and revoked.last_error=='ACCESS_REVOKED'


def test_bounded_address_recovery_with_bad_and_disabled_accounts(relay,monkeypatch):
    with SessionLocal.begin() as db:
        db.add(User(username='bad',name='Bad mailbox',password_hash='placeholder',roles=['REVIEWER'],warehouses=['UK_MAIN'],
                    email='not an email'))
        db.add(User(username='inactive',name='Inactive',password_hash='placeholder',roles=['REVIEWER'],warehouses=['UK_MAIN'],active=False))
    for number in range(1,64):
        queue(number,user='bad',state='WAITING_EMAIL')
    disabled=queue(64,user='inactive',state='WAITING_EMAIL')
    wanted=queue(65,state='WAITING_EMAIL')
    queue(66,state='WAITING_EMAIL')
    assert delivery.reserve_one() is None
    with SessionLocal() as db:
        assert db.get(WorkflowMail,disabled).state=='CANCELLED'
        assert db.get(WorkflowMail,f'{1:064x}').next_attempt_at>time.time()
        assert db.get(WorkflowMail,wanted).state=='WAITING_EMAIL'
    assert delivery.reserve_one() is None
    monkeypatch.setattr(workflow_outbox,'_next_address_scan',0)
    ready=delivery.reserve_one()
    assert ready['id']==wanted and ready['to']=='review@example.invalid'


def test_dedicated_worker_calls_transport_after_durable_boundary(relay,monkeypatch):
    from backend.jobs import start_workers
    ident=queue(1)
    attempted=Event()
    def send(item,before_data):
        assert item['id']==ident and before_data()
        with SessionLocal() as db:
            assert db.get(WorkflowMail,ident).state=='SENDING'
        attempted.set()
        return 'sent',None
    monkeypatch.setattr(delivery,'send_workflow_mail',send)
    monkeypatch.setattr(workflow_smtp,'smtp_enabled',lambda:True)
    stop,threads=start_workers()
    try:
        assert len(threads)==3 and sum(t.name=='workflow-smtp' for t in threads)==1
        assert attempted.wait(5)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
    with SessionLocal() as db:
        assert db.get(WorkflowMail,ident).state=='SENT'
    monkeypatch.setattr(workflow_smtp,'smtp_enabled',lambda:False)
    stop,threads=start_workers()
    try:
        assert len(threads)==2
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
