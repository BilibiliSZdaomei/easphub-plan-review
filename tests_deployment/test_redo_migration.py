"""Upgrade a populated 0009 undo history in a dedicated empty SQLite or MySQL database."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import json
import os
from pathlib import Path
import subprocess
import sys
import zlib

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('dialect',['sqlite','mysql'])
def test_upgrade_0009_undo_history_and_new_redo(tmp_path,dialect):
    mysql_url=os.environ.get('PLAN_REVIEW_TEST_EMPTY_MYSQL_URL')
    if dialect=='mysql' and not mysql_url:
        pytest.skip('Provide the URL of a dedicated empty MySQL test database')
    env={k:v for k,v in os.environ.items() if not k.startswith(('PLAN_REVIEW_DATABASE_URL','PLAN_REVIEW_DB_'))}
    env.update(APP_DATA_DIR=str(tmp_path/'data'),PLAN_REVIEW_DATA=str(tmp_path/'data'),PYTHONPATH=str(ROOT),
               PYTHONDONTWRITEBYTECODE='1',APP_BASE_PATH='/plan-review',DEPLOY_ENV='local',PLAN_REVIEW_DEMO='1',
               PLAN_REVIEW_WORKER='0')
    if dialect=='mysql': env['PLAN_REVIEW_DATABASE_URL']=mysql_url
    run=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),dialect],cwd=ROOT,env=env,
                       capture_output=True,text=True,encoding='utf-8',timeout=120)
    assert run.returncode==0,run.stdout+run.stderr
    assert 'upgrade, undo, redo, downgrade verified' in run.stdout


def exercise_migration(dialect):
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import inspect,select,text
    from backend.api import app
    from backend.db import Batch,PlanRedo,PlanUndo,Rule,SessionLocal,User,Version,engine
    from backend.demo import DEMO_PASSWORD,seed_demo
    from backend.rules import calculate

    assert engine.dialect.name==dialect
    assert not inspect(engine).get_table_names(),'Migration test needs its own empty database'
    config=Config(str(ROOT/'alembic.ini'))
    # Seed through the current application, then expose historical columns only.
    command.upgrade(config,'head')
    with SessionLocal.begin() as db:
        seed_demo(db)
    command.downgrade(config,'0009')
    assert 'plan_undo' in inspect(engine).get_table_names() and 'plan_redo' not in inspect(engine).get_table_names()
    with SessionLocal.begin() as db:
        batch=db.scalar(select(Batch).where(Batch.number=='PR-DEMO-UK_MAIN'))
        version=db.get(Version,batch.current_id)
        version_id=version.id
        owner_id=batch.owner
        before=deepcopy(version.items)
        after=deepcopy(before)
        after[0]['input']['sea_plan_qty']='139'
        after[0]['result']=calculate(after[0]['input'],db.get(Rule,version.rule_id).package)
        version.items=after
        db.flush()
        old_rev=version.revision
        # Original 0009 wire format: only the inverse, no precomputed redo payload.
        inverse={'changed':{before[0]['id']:[{'input':before[0]['input'],'result':before[0]['result']},[]]},
                 'removed':[],'created':[],'basis':{},'order':None}
        payload=zlib.compress(json.dumps(inverse,ensure_ascii=False,separators=(',',':')).encode(),1)
        db.add(PlanUndo(version_id=version_id,revision=old_rev,actor_id=owner_id,label='修改计划明细',row_count=1,payload=payload))
    command.upgrade(config,'0010')
    inspector=inspect(engine)
    assert inspector.get_pk_constraint('plan_redo')['constrained_columns']==['version_id','revision']
    assert inspector.get_foreign_keys('plan_redo')[0]['referred_table']=='versions'
    if dialect=='mysql':
        with engine.connect() as conn:
            assert str(conn.scalar(text('SELECT VERSION()'))).startswith('8.')
            kind=conn.scalar(text("SELECT DATA_TYPE FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='plan_redo' AND column_name='payload'"))
            assert kind=='longblob'
    with SessionLocal() as db:
        assert db.get(PlanUndo,(version_id,old_rev)).payload==payload
        assert db.scalar(select(PlanRedo.revision)) is None
    # Exercise today's HTTP application on today's schema after checking the 0010 transition.
    assert 'user_avatars' not in inspector.get_table_names()
    command.upgrade(config,'0011')
    assert inspect(engine).get_foreign_keys('user_avatars')[0]['referred_table']=='users'
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO user_avatars (user_id,preset,source,revision) VALUES (:id,:preset,:source,:revision)'),
                     {'id':owner_id,'preset':'parts','source':'draftbit-personas','revision':'7b5234c44b3cef49d483b1462398bc9ea07bfa12'})
    command.upgrade(config,'0012')
    assert 'email' not in {col['name'] for col in inspect(engine).get_columns('users')}
    # A pending notification from before the mail rollout must never enqueue mail.
    from backend.db import NotificationEvent
    with SessionLocal.begin() as db:
        db.add(NotificationEvent(payload={'kind':'SUBMITTED','owner':owner_id,'batch_id':batch.id,'warehouse':batch.warehouse,
                                         'version_id':version_id,'reviewers':True,'recipient':None,'text':'existing notification'}))
    command.upgrade(config,'head')
    assert inspect(engine).get_foreign_keys('usage_presence')[0]['referred_table']=='sessions'
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT COUNT(*) FROM usage_days'))==0
        assert conn.scalar(text('SELECT preset FROM user_avatars WHERE user_id=:id'),{'id':owner_id})=='parts'
        assert conn.scalar(text('SELECT COUNT(*) FROM users WHERE email IS NOT NULL'))==0
        assert conn.scalar(text('SELECT COUNT(*) FROM workflow_mail'))==0
    from backend.jobs import deliver_notifications
    while deliver_notifications():
        pass
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT COUNT(*) FROM workflow_mail'))==0
    path='/plan-review/api/v1/versions/'+version_id
    with TestClient(app) as client:
        login=client.post('/plan-review/api/v1/sessions',json={'username':'planner','password':DEMO_PASSWORD})
        assert login.status_code==200,login.text
        client.headers['X-CSRF-Token']=login.json()['csrf']
        assert login.json()['user']['avatar_preset']=='parts'
        avatar=client.patch('/plan-review/api/v1/profile/avatar',json={'avatar_preset':'order'})
        assert avatar.status_code==200 and avatar.json()['avatar_preset']=='order'
        state=client.get(path).json()
        assert state['undo']=={'label':'修改计划明细','count':1} and state['redo'] is None
        response=client.post(path+'/undo',headers={'Idempotency-Key':'post-upgrade-undo'},json={'revision':old_rev})
        assert response.status_code==200,response.text
        undo=client.get(path).json()
        assert undo['undo'] is None and undo['redo']==state['undo']
        with SessionLocal() as db:
            assert db.get(Version,version_id).items==before
        gate=Barrier(2)
        def replay(_):
            gate.wait(timeout=5)
            return client.post(path+'/redo',headers={'Idempotency-Key':'post-upgrade-redo'},json={'revision':undo['revision']})
        with ThreadPoolExecutor(max_workers=2) as pool:
            redo,retry=pool.map(replay,range(2))
        assert (redo.status_code,retry.status_code)==(200,200),(redo.text,retry.text)
        assert redo.json()==retry.json() and redo.json()['revision']==undo['revision']+1
        final=client.get(path).json()
        assert final['items']==state['items'] and final['redo'] is None and final['undo']==state['undo']
    command.downgrade(config,'0009')
    assert 'plan_redo' not in inspect(engine).get_table_names()
    assert 'user_avatars' not in inspect(engine).get_table_names()
    assert 'usage_days' not in inspect(engine).get_table_names()
    with SessionLocal() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0009'
        assert db.get(Version,version_id).items==after
        assert db.get(PlanUndo,(version_id,final['revision'])).label=='修改计划明细'
    engine.dispose()
    print(dialect,'upgrade, undo, redo, downgrade verified')


if __name__=='__main__':
    exercise_migration(sys.argv[1])
