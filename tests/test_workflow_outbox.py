import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.db import Batch, NotificationEvent, SessionLocal, User, WorkflowMail
from backend.demo import DEMO_PASSWORD
from backend.workflow_outbox import refresh_recipient_email
from test_api import P,clients,current,post


def apply(client,path,body,key=None):
    response=post(client,path,body,key)
    assert response.status_code==200,response.text
    return response.json()


def deliveries(kind):
    with SessionLocal() as db:
        rows = db.scalars(select(WorkflowMail).where(WorkflowMail.kind==kind)).all()
        return {row.recipient_id:row for row in rows}


def test_routing_full_lifecycle_snapshot_and_address_recovery(clients):
    planner,reviewer,admin,other=clients
    owner=planner.get(P+'/me').json()['user']; review_account=reviewer.get(P+'/me').json()['user']; admin_account=admin.get(P+'/me').json()['user']
    second=apply(admin,'/users',{'username':'second@example.invalid','password':DEMO_PASSWORD,'name':'Second',
                                'roles':['REVIEWER'],'warehouses':['UK_MAIN']})
    with SessionLocal.begin() as db:
        # A reviewer for another warehouse and a disabled reviewer both stay off the list.
        db.scalar(select(User).where(User.username=='spain')).roles=['REVIEWER']
        db.add(User(username='retired',name='Retired',password_hash='disabled',active=False,roles=['REVIEWER'],warehouses=['UK_MAIN']))
        # Even when the submitter holds review duties, their own submission is excluded.
        db.get(User,owner['id']).roles=['REVIEWER']
    batch,ver=current(planner)
    base='/versions/'+ver['id']; revision={'revision':ver['revision']}; key=uuid4().hex
    assert apply(planner,base+'/submit',revision,key)==apply(planner,base+'/submit',revision,key)
    submitted=deliveries('SUBMITTED')
    assert set(submitted)=={review_account['id'],second['id']}
    record=submitted[second['id']]
    assert record.state=='QUEUED' and record.destination=='second@example.invalid'
    assert record.id==hashlib.sha256(f"{record.event_id}/{second['id']}".encode()).hexdigest()
    assert submitted[review_account['id']].state=='WAITING_EMAIL' and submitted[review_account['id']].destination is None
    assert record.payload['version_no']==1 and record.payload['state']=='SUBMITTED' and record.payload['row_count']==len(ver['items'])
    assert record.payload['market']=='UK' and record.payload['plan_number']==batch['number']
    with SessionLocal.begin() as db:
        assert db.scalar(select(func.count()).select_from(WorkflowMail))==2
        assert db.get(NotificationEvent,record.event_id).payload['kind']=='SUBMITTED'
        u=db.get(User,review_account['id']); u.email='review@example.invalid'; refresh_recipient_email(db,u)
        db.get(Batch,batch['id']).title='Renamed after submission'
    submitted=deliveries('SUBMITTED')
    assert submitted[review_account['id']].state=='QUEUED' and submitted[review_account['id']].destination=='review@example.invalid'
    assert submitted[second['id']].payload['plan_title']==batch['title']
    claimed=apply(reviewer,base+'/claim',{'revision':reviewer.get(P+base).json()['revision']})
    assert set(deliveries('CLAIMED'))=={second['id']}
    transferred=apply(reviewer,base+'/transfer',{'revision':claimed['revision'],'reviewer_id':admin_account['id']})
    assert set(deliveries('TRANSFERRED'))=={admin_account['id']}
    marked=apply(admin,base+'/reviews',{'revision':transferred['revision'],'ids':[ver['items'][0]['id']],'decision':'REJECTED'})
    bounced=apply(admin,base+'/return',{'revision':marked['revision'],'reason':'Please review stock'})
    returned=deliveries('RETURNED')
    assert set(returned)=={owner['id']}
    item=returned[owner['id']]
    assert item.version_id==bounced['version_id'] and item.payload['version_no']==2 and item.payload['state']=='RETURNED'
    assert item.payload['reason']=='Please review stock' and item.payload['flagged_count']==1
    new='/versions/'+bounced['version_id']
    apply(planner,new+'/submit',{'revision':planner.get(P+new).json()['revision']})
    assert set(deliveries('RESUBMITTED'))=={review_account['id'],second['id']}
    assert deliveries('RESUBMITTED')[review_account['id']].payload['version_no']==2


@pytest.mark.parametrize('outcome',['APPROVED','REJECTED'])
def test_final_whole_plan_goes_to_original_owner(clients,outcome):
    planner,reviewer,_,_=clients
    batch,ver=current(planner); path='/versions/'+ver['id']
    submitted=apply(planner,path+'/submit',{'revision':ver['revision']})
    claimed=apply(reviewer,path+'/claim',{'revision':submitted['revision']})
    revision=claimed['revision']
    if outcome=='REJECTED':
        reviewed=apply(reviewer,path+'/reviews',{'revision':revision,'ids':[ver['items'][0]['id']],'decision':'REJECTED'})
        revision=reviewed['revision']
    apply(reviewer,path+'/finalize',{'revision':revision,'outcome':outcome})
    final=deliveries(outcome)
    assert set(final)=={batch['owner']}
    snapshot=final[batch['owner']].payload
    assert snapshot['state']==outcome and snapshot['row_count']==len(ver['items'])
    assert snapshot['approved_count']==(len(ver['items']) if outcome=='APPROVED' else 0)
    assert snapshot['rejected_count']==(len(ver['items']) if outcome=='REJECTED' else 0)


def test_failed_plan_commit_produces_no_workflow_mail(clients,monkeypatch):
    planner,*_=clients
    batch,ver=current(planner)
    def fail_commit(session):
        raise RuntimeError('synthetic failed commit')
    with monkeypatch.context() as patch:
        patch.setattr(SessionLocal.class_,'commit',fail_commit)
        assert post(planner,'/versions/'+ver['id']+'/submit',{'revision':ver['revision']}).status_code==500
    assert not deliveries('SUBMITTED')
    with SessionLocal() as db:
        assert db.get(Batch,batch['id']).state=='DRAFT'
