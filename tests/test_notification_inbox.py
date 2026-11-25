from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.api import app
from backend.db import Batch, Notification, SessionLocal, User
from backend.jobs import deliver_notifications
from test_api import P, clients, post, ready, claim
from test_review_handoff import another_reviewer


def drain():
    while deliver_notifications():
        pass


def feed(client, query=''):
    response=client.get(P+'/notification-inbox'+query)
    assert response.status_code==200,response.text
    return response.json()


def test_dynamic_work_after_claim_transfer_return_and_resubmission(clients):
    planner,reviewer,_,other_warehouse=clients
    batch,version=ready(planner)
    route='/versions/'+version['id']
    with TestClient(app) as peer:
        target=another_reviewer(peer)
        assert post(planner,route+'/submit',{'revision':version['revision']}).status_code==200
        drain()
        req=feed(reviewer,'?tab=action')['items'][0]
        assert (req['action'],req['kind'],req['warehouse_name'])==('CLAIM','SUBMITTED',batch['warehouse_name'])
        assert feed(other_warehouse)['total']==0
        v=claim(reviewer,route)
        drain()
        assert feed(reviewer,'?tab=action')['items'][0]['action']=='REVIEW'
        assert feed(peer,'?tab=action')['total']==0
        assert feed(planner,'?kind=CLAIMED')['total']==1
        assert post(reviewer,route+'/transfer',{'revision':v['revision'],'reviewer_id':target}).status_code==200
        drain()
        assert feed(reviewer,'?tab=action')['total']==0
        active=feed(peer,'?tab=action')
        assert active['total']==1 and active['items'][0]['kind']=='TRANSFERRED'
        v=peer.get(P+route).json()
        returned=post(peer,route+'/return',{'revision':v['revision'],'ids':[v['items'][0]['id']],'reason':'请更正海运'})
        assert returned.status_code==200,returned.text
        drain()
        assert feed(peer,'?tab=action')['total']==0
        change=feed(planner,'?tab=action')['items']
        assert len(change)==1 and change[0]['action']=='EDIT' and change[0]['kind']=='RETURNED'
        path='/versions/'+returned.json()['version_id']
        draft=planner.get(P+path).json()
        assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
        drain()
        assert feed(planner,'?tab=action')['total']==0
        latest=feed(peer,'?tab=action')['items']
        assert len(latest)==1 and latest[0]['action']=='CLAIM' and latest[0]['kind']=='SUBMITTED'


def test_scoped_read_and_visibility_with_late_delivery(clients):
    planner,reviewer,_,spain=clients
    batch,v=ready(planner)
    path='/versions/'+v['id']
    assert post(planner,path+'/submit',{'revision':v['revision']}).status_code==200
    drain()
    initial=feed(reviewer,'?kind=SUBMITTED')
    note=initial['items'][0]
    assert post(spain,'/notifications/'+note['id']+'/seen',{}).status_code==404
    with SessionLocal.begin() as db:
        owner=db.scalar(select(User.id).where(User.username=='test_reviewer'))
        db.add_all([Notification(user_id=owner,batch_id=batch['id'],warehouse=batch['warehouse'],text='稍后送达的旧事件',kind='SUBMITTED',
                                 occurred_at=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()),
                    Notification(user_id=owner,batch_id=batch['id'],warehouse=batch['warehouse'],text='其他类别',kind='GENERAL')])
    body={'tab':'all','warehouse':batch['warehouse'],'kind':'SUBMITTED','before':initial['before']}
    assert post(reviewer,'/notification-inbox/seen',body).json()['count']==1
    assert post(reviewer,'/notification-inbox/seen',body).json()['count']==0
    assert feed(reviewer,'?tab=unread')['total']==2
    assert feed(spain,'?tab=action')['total']==0
    with SessionLocal.begin() as db:
        db.get(Batch,batch['id']).state='VOID'
    assert feed(reviewer)['total']==0
    assert post(reviewer,'/notifications/'+note['id']+'/seen',{}).status_code==404
    assert reviewer.get(P+'/notifications?all=true').json()==[]
    assert post(reviewer,'/notification-inbox/seen',body).json()['count']==0

def test_upgrade_links_old_deliveries_to_original_round(tmp_path):
    import hashlib
    import json
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text

    engine=create_engine('sqlite:///'+str(tmp_path/'earlier.sqlite3'))
    migration=import_module('migrations.versions.0008_notification_context')
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE notifications (id TEXT PRIMARY KEY,user_id TEXT,batch_id TEXT,text TEXT,seen BOOLEAN,created_at TEXT)')
            conn.exec_driver_sql('CREATE TABLE notification_events (id TEXT PRIMARY KEY,created_at TEXT,state TEXT,payload JSON)')
            conn.exec_driver_sql('CREATE TABLE versions (id TEXT PRIMARY KEY,batch_id TEXT,created_at TEXT)')
            conn.exec_driver_sql("INSERT INTO versions VALUES ('v1','b','2026-11-01'),('v2','b','2026-11-03')")
            payload=json.dumps({'batch_id':'b','reviewers':True,'text':'计划已提交，等待复审'})
            rows=[('e1','2026-11-02','DONE',payload),('e2','2026-11-04','QUEUED',payload)]
            conn.exec_driver_sql("INSERT INTO notification_events VALUES (?,?,?,?)",rows)
            nid=hashlib.sha256(b'e1peer').hexdigest()[:32]
            conn.exec_driver_sql("INSERT INTO notifications VALUES (?,?,?,?,?,?)",(nid,'peer','b','计划已提交，等待复审',1,'2026-11-05'))
            conn.exec_driver_sql("INSERT INTO notifications VALUES ('manual','peer','b','计划已提交，等待复审',0,'2026-11-05')")
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            restored=conn.execute(text("SELECT kind,version_id,occurred_at,seen FROM notifications WHERE id=:id"),{'id':nid}).one()
            assert tuple(restored)==('SUBMITTED','v1','2026-11-02',1)
            assert conn.exec_driver_sql("SELECT version_id FROM notifications WHERE id='manual'").scalar() is None
            queued=json.loads(conn.exec_driver_sql("SELECT payload FROM notification_events WHERE id='e2'").scalar())
            assert queued['version_id']=='v2' and queued['kind']=='SUBMITTED'
    finally:
        engine.dispose()


def test_historical_final_notice_keeps_archive_text_in_storage(clients):
    planner, _, _, foreign = clients
    batch, version = ready(planner)
    original = batch['title'] + ' 复审完成，部分物料不批准'
    with SessionLocal() as db:
        db.get(Batch, batch['id']).state = 'PARTIALLY_APPROVED'
        note = Notification(user_id=batch['owner'], batch_id=batch['id'], warehouse=batch['warehouse'],
                            version_id=version['id'], kind='FINALIZED', text=original)
        db.add(note)
        db.commit()
        note_id = note.id
    for endpoint in ('/notifications?all=true', '/notification-inbox?kind=FINALIZED'):
        result = planner.get(P+endpoint).json()
        items = result if isinstance(result,list) else result['items']
        assert next(n['text'] for n in items if n['id']==note_id) == batch['title'] + ' 历史结案（旧规则）'
    assert feed(foreign, '?kind=FINALIZED')['total'] == 0
    with SessionLocal() as db:
        assert db.get(Notification, note_id).text == original
