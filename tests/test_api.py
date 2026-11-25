from pathlib import Path
import uuid
from fastapi.testclient import TestClient
import pytest
from backend.api import app
from backend.demo import DEMO_PASSWORD
from backend.db import engine,Base
P='/plan-review/api/v1'

@pytest.fixture()
def clients(test_database_path):
    assert engine.url.get_backend_name() == 'sqlite' and Path(engine.url.database).resolve() == test_database_path
    Base.metadata.drop_all(engine)
    with TestClient(app) as planner,TestClient(app) as reviewer,TestClient(app) as admin,TestClient(app) as spain:
        for c,name in [(planner,'planner'),(reviewer,'test_reviewer'),(admin,'test_steward'),(spain,'spain')]:
            r=c.post(P+'/sessions',json={'username':name,'password':DEMO_PASSWORD});assert r.status_code==200,r.text
            c.headers['X-CSRF-Token']=r.json()['csrf']
        yield planner,reviewer,admin,spain

def post(c,path,data,key=None):
    return c.post(P+path,json=data,headers={'Idempotency-Key':key or uuid.uuid4().hex})

def claim(c,path):
    revision=c.get(P+path).json()['revision']
    claimed=post(c,path+'/claim',{'revision':revision})
    assert claimed.status_code==200,claimed.text
    return c.get(P+path).json()

def test_success_response_waits_for_durable_commit(clients):
    from backend.db import SessionLocal, Mapping
    from sqlalchemy import select
    p,r,admin,s=clients
    checked=[]
    async def observed(scope,receive,send):
        async def boundary(message):
            if scope['type']=='http' and scope['path']==P+'/mappings' and message['type']=='http.response.start' and message['status']==200:
                with SessionLocal() as other:
                    assert other.scalar(select(Mapping).where(Mapping.name=='durable-response')) is not None
                checked.append(True)
            await send(message)
        await app(scope,receive,boundary)
    with TestClient(observed) as browser:
        browser.cookies.update(admin.cookies)
        browser.headers['X-CSRF-Token']=admin.headers['X-CSRF-Token']
        result=post(browser,'/mappings',{'name':'durable-response','warehouse':'UK_MAIN','config':{}})
        assert result.status_code==200,result.text
    assert checked==[True]

def test_commit_failure_returns_error_and_rolls_back(clients,monkeypatch):
    from backend.db import SessionLocal, Mapping
    from sqlalchemy import select
    p,r,admin,s=clients
    def fail_commit(session):raise RuntimeError('simulated storage commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(SessionLocal.class_,'commit',fail_commit)
        response=post(admin,'/mappings',{'name':'must-not-persist','warehouse':'UK_MAIN','config':{}})
    assert response.status_code==500
    assert 'simulated storage' not in response.text
    with SessionLocal() as db:
        assert db.scalar(select(Mapping).where(Mapping.name=='must-not-persist')) is None

def current(c):
    b=c.get(P+'/batches').json()[0]
    v=c.get(P+'/versions/'+b['current_id']).json()
    return b,v

def ready(c):
    b,v=current(c)
    edits=[]
    for row in v['items']:
        values={'reason_code':'特殊物料','reason':'测试已核实需求，保留本次数量','air_reason':'测试已确认急件需求'}
        edits.append({'id':row['id'],'values':values})
    r=c.patch(P+'/versions/'+v['id']+'/items',json={'revision':v['revision'],'changes':edits});assert r.status_code==200,r.text
    v=c.get(P+'/versions/'+v['id']).json();return b,v

def test_scope_csrf_and_planner_no_approval(clients):
    p,r,a,s=clients;b,v=current(p)
    assert s.get(P+'/versions/'+v['id']).status_code==403
    assert s.get(P+'/batches/'+b['id']).status_code==403
    assert post(p,'/versions/'+v['id']+'/finalize',{'revision':v['revision']}).status_code==403
    csrf=p.headers.pop('X-CSRF-Token')
    assert p.patch(P+'/versions/'+v['id']+'/items',json={'revision':1,'changes':[]}).status_code==403

def test_submit_with_warnings_is_idempotent_and_locks_version(clients):
    p,r,a,s=clients;b,v=current(p)
    assert p.get(P+'/versions/'+v['id']+'/confirmation').json()['affected_count']>0
    key=uuid.uuid4().hex;body={'revision':v['revision']}
    one=post(p,'/versions/'+v['id']+'/submit',body,key);two=post(p,'/versions/'+v['id']+'/submit',body,key)
    assert one.status_code==200 and one.json()==two.json()
    assert post(p,'/versions/'+v['id']+'/submit',{'revision':99},key).status_code==409
    assert p.patch(P+'/versions/'+v['id']+'/items',json={'revision':v['revision'],'changes':[]}).status_code==409

def test_full_review_return_resubmit_approve(clients):
    p,r,a,s=clients;b,v=ready(p)
    assert post(p,'/versions/'+v['id']+'/submit',{'revision':v['revision']}).status_code==200
    rv=claim(r,'/versions/'+v['id'])
    ids=[i['id'] for i in rv['items']]
    reviewed=post(r,'/versions/'+v['id']+'/reviews',{'revision':rv['revision'],'ids':ids,'decision':'APPROVED'})
    assert reviewed.status_code==200 and reviewed.json()['count']==len(ids) and not reviewed.json()['skipped']
    rv=r.get(P+'/versions/'+v['id']).json()
    assert post(r,'/versions/'+v['id']+'/finalize',{'revision':rv['revision']-1}).status_code==409
    returned=post(r,'/versions/'+v['id']+'/return',{'revision':rv['revision'],'ids':ids,'reason':'请核对空运数量'})
    assert returned.status_code==200,returned.text
    new_id=returned.json()['version_id'];nv=p.get(P+'/versions/'+new_id).json()
    assert nv['seq']==2 and all(i['decision'] is None for i in nv['items'])
    assert p.get(P+'/versions/'+v['id']).json()['state']=='RETURNED'
    assert p.get(P+'/batches/'+b['id']).json()['state']=='RETURNED'
    assert post(p,'/versions/'+new_id+'/submit',{'revision':nv['revision']}).status_code==200
    rv=claim(r,'/versions/'+new_id)
    result=post(r,'/versions/'+new_id+'/reviews',{'revision':rv['revision'],'ids':[i['id'] for i in rv['items']],'decision':'EXCEPTION_APPROVED','reason_code':'特殊物料','reason':'逐项核实真实需求','ack_flags':['MANUAL','COLLISION','MISSING_RATE','NO_SEA_RANGE','ABC_MISSING'],'air_confirmed':True})
    assert result.status_code==200 and not result.json()['skipped'],result.text
    final=post(r,'/versions/'+new_id+'/finalize',{'revision':result.json()['revision']})
    assert final.status_code==200,final.text
    assert p.get(P+'/batches/'+b['id']).json()['state']=='APPROVED'
    from backend.jobs import deliver_notifications
    while deliver_notifications():pass
    assert p.get(P+'/notifications').json()
    events=p.get(P+'/batches/'+b['id']).json()['events'];assert any(e['action']=='完成终审' for e in events)

def test_stale_revision_conflict_and_base_fields_protected(clients):
    p,r,a,s=clients;b,v=current(p);item=v['items'][0]
    body={'revision':v['revision'],'changes':[{'id':item['id'],'values':{'sea_plan_qty':'36'}}]}
    assert p.patch(P+'/versions/'+v['id']+'/items',json=body).status_code==200
    assert p.patch(P+'/versions/'+v['id']+'/items',json=body).status_code==409
    body['revision']+=1;body['changes'][0]['values']={'net_supply_before_plan':'0'}
    assert p.patch(P+'/versions/'+v['id']+'/items',json=body).status_code==422

def test_rule_publish_permission_proof_and_frozen_history(clients):
    p,r,a,s=clients;b,v=ready(p);post(p,'/versions/'+v['id']+'/submit',{'revision':v['revision']})
    rules=r.get(P+'/rules').json()['items'];base=rules[0]
    create=post(r,'/rules',{'source_id':base['id'],'name':'测试新标准','scope':'WAREHOUSE','scope_code':'UK_MAIN'}).json()
    assert post(r,'/rules/'+create['id']+'/publish',{'revision':create['revision'],'reason':'test'}).status_code==422
    package=create['package'];package['params']['fixed_ab']=13
    edited=r.patch(P+'/rules/'+create['id'],json={'revision':create['revision'],'package':package}).json()
    proof=post(r,'/rules/'+create['id']+'/dry-run',{'revision':edited['revision'],'snapshot_id':v['snapshot']['id']})
    assert proof.status_code==200,proof.text
    assert post(p,'/rules/'+create['id']+'/publish',{'revision':proof.json()['revision'],'reason':'test'}).status_code==403
    published=post(r,'/rules/'+create['id']+'/publish',{'revision':proof.json()['revision'],'reason':'测试确认'});assert published.status_code==200,published.text
    assert p.get(P+'/versions/'+v['id']).json()['rule']['id']==base['id']
    assert r.patch(P+'/rules/'+create['id'],json={'revision':published.json()['revision'],'package':package}).status_code==409

def test_copy_and_void_dont_reuse_approval(clients):
    p,r,a,s=clients;b,v=current(p)
    copied=post(p,'/batches/'+b['id']+'/copy',{});assert copied.status_code==200,copied.text
    new=copied.json();assert new['id']!=b['id'] and new['state']=='DRAFT'
    assert post(p,'/batches/'+new['id']+'/void',{'revision':new['revision'],'reason':'a'*2001}).status_code==422
    assert post(p,'/batches/'+new['id']+'/void',{'revision':new['revision']}).status_code==200
