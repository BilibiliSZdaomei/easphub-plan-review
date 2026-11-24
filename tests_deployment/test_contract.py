"""Deployment acceptance using a new synthetic database and actual built UI."""
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from native_fixture import prepare
from artifact_paths import artifact_root

PREFIX = '/apps/plan-review'
API = PREFIX+'/api/v1'


@pytest.fixture(scope='module')
def fixture():
    app, temporary, directory = prepare(os.environ.get('ADAPTATION_UI_DIR',artifact_root(ROOT)/'frontend/dist'))
    yield app, directory
    from backend.db import engine
    engine.dispose()
    temporary.cleanup()


def login(client, username='planner'):
    from backend.demo import DEMO_PASSWORD
    response = client.post(API+'/sessions',json={'username':username,'password':DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf']
    return response


def test_prefix_authentication_and_csrf(fixture):
    app, directory = fixture
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get(API+'/batches').status_code == 401
        assert client.get('/plan-review/api/v1/batches').status_code == 404
        response = client.get(PREFIX+'?x=%2Fhello%20world',follow_redirects=False)
        assert response.status_code == 307 and response.headers['location']==PREFIX+'/?x=%2Fhello%20world'
        html = client.get(PREFIX+'/').text
        assert client.get(PREFIX+'/nested/refresh?q=test').text == html
        assert client.get(PREFIX+'/api/v1/not-an-api').status_code == 404
        response = login(client)
        cookie = response.headers['set-cookie']
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path='+PREFIX in cookie
        batch = client.get(API+'/batches').json()[0]
        assert client.get(API+'/session-state').json()['demo'] is False
        csrf = client.headers.pop('X-CSRF-Token')
        assert client.patch(API+'/versions/'+batch['current_id']+'/items',json={'revision':1,'changes':[]}).status_code == 403
        client.headers['X-CSRF-Token'] = csrf
        assert client.delete(API+'/sessions/current').status_code == 200
        assert client.get(API+'/batches').status_code == 401
    with TestClient(app,base_url='https://testserver') as other:
        login(other,'spain')
        assert other.get(API+'/batches/'+batch['id']).status_code == 403


def test_synthetic_upload_and_chinese_formula_export(fixture):
    from backend.jobs import run_job
    app, _ = fixture
    with TestClient(app,base_url='https://testserver') as client:
        login(client)
        for kind in ('plan','v2'):
            response = client.get(API+'/template', params={'kind':kind})
            assert response.status_code == 200
            template = load_workbook(BytesIO(response.content), read_only=True)
            assert len(next(template.active.values)) >= 3
            template.close()
        standard = client.get(API+'/template', params={'kind':'standard'})
        assert standard.status_code == 200 and '物料号' in standard.content.decode('utf-8-sig')
        source = '物料号,海运计划,空运计划\nDEMO-0001,35,0\n'.encode('utf-8')
        uploaded = client.post(API+'/imports',data={'warehouse':'UK_MAIN','kind':'plan'},files={'file':('合成计划.csv',source,'text/csv')})
        assert uploaded.status_code == 200, uploaded.text
        run_job(uploaded.json()['id'])
        state = client.get(API+'/jobs/'+uploaded.json()['id']).json()
        assert state['state']=='DONE' and state['rows']==1
        original = client.get(API+'/jobs/'+uploaded.json()['id']+'/download')
        assert original.status_code == 200 and original.content == source
        issues = client.get(API+'/imports/'+uploaded.json()['id']+'/errors')
        assert issues.status_code == 200 and '物料号' in issues.content.decode('utf-8-sig')
        batch = client.get(API+'/batches').json()[0]
        version = client.get(API+'/versions/'+batch['current_id']).json()
        result = client.post(API+'/exports',json={'version_id':version['id']},headers={'Idempotency-Key':uuid.uuid4().hex})
        assert result.status_code == 200, result.text
        run_job(result.json()['id'])
        job = client.get(API+'/jobs/'+result.json()['id']).json()
        assert job['state']=='DONE' and job['rows']==len(version['items'])
        assert job['download_url'].startswith(API+'/jobs/') and job['filename'].startswith('计划审核_')
        response = client.get(job['download_url'])
        assert response.status_code==200 and "filename*=utf-8''" in response.headers['content-disposition']
        workbook = load_workbook(BytesIO(response.content),data_only=False)
        assert len(workbook.sheetnames)>=2
        assert any(cell.data_type=='f' for sheet in workbook for row in sheet for cell in row)
        workbook.close()


def test_real_readiness_failure_and_recovery(fixture):
    from backend.db import engine
    app, directory = fixture
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get('/health/ready').status_code==200
        manifest = directory/'ui/app-build.json'
        original = manifest.read_bytes()
        manifest.write_text('{"base_path":"/wrong"}',encoding='utf-8')
        assert client.get('/health/ready').status_code==503
        assert client.get('/health/live').status_code==200
        manifest.write_bytes(original)
        with engine.begin() as connection:
            current_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            connection.execute(text("UPDATE alembic_version SET version_num='unavailable'"))
        assert client.get('/health/ready').status_code==503
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num=:revision"), {'revision':current_revision})
        files = directory/'data/files'
        moved = directory/'data/files-unavailable'
        files.rename(moved)
        try:
            assert client.get('/health/ready').status_code==503
        finally:
            moved.rename(files)
        assert client.get('/health/ready').status_code==200


def test_mysql_ddl_and_unchanged_active_rule_invariant(fixture):
    from backend.db import Base, engine, Rule, transaction
    from sqlalchemy.exc import IntegrityError
    assert len(Base.metadata.tables)==13
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert 'VARCHAR(' in ddl and 'VARCHAR,' not in ddl
    environment = dict(os.environ)
    environment['PLAN_REVIEW_DATABASE_URL']='mysql+pymysql://synthetic:synthetic@127.0.0.1:1/synthetic'
    compiled = subprocess.run([sys.executable,'-m','alembic','upgrade','head','--sql'],cwd=ROOT,env=environment,capture_output=True,text=True,check=True)
    assert 'VARCHAR(255)' in compiled.stdout and 'COLLATE utf8mb4_0900_bin' in compiled.stdout
    assert 'CASE WHEN active = 1 THEN 1 ELSE NULL END' in compiled.stdout
    assert 'DOUBLE' in compiled.stdout
    evidence = artifact_root(ROOT, 'plan-review') / 'mysql-schema.sql'
    evidence.parent.mkdir(parents=True,exist_ok=True)
    evidence.write_text(compiled.stdout,encoding='utf-8')
    with transaction() as database:
        rule = database.scalar(select(Rule).where(Rule.active.is_(True)))
        values = {'name':'synthetic inactive','scope':rule.scope,'scope_code':rule.scope_code,'creator':rule.creator,'package':rule.package,'active':False}
        database.add_all([Rule(**values),Rule(**values)])
    with pytest.raises(IntegrityError):
        with transaction() as database:
            database.add(Rule(**{**values,'active':True}))
    assert engine.dialect.name=='sqlite'  # MySQL execution deliberately not claimed.


def test_worker_progress_and_stale_probe(fixture):
    _, directory = fixture
    heartbeat = directory/'worker.json'
    process = subprocess.Popen([sys.executable,'scripts/run_worker.py'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            if heartbeat.exists():
                payload = json.loads(heartbeat.read_text())
                if all(worker['progress']>0 for worker in payload['workers']):break
            time.sleep(.1)
        probe = subprocess.run([sys.executable,'scripts/healthcheck.py','worker'],cwd=ROOT,capture_output=True)
        assert probe.returncode==0, probe.stderr
    finally:
        process.terminate()
        process.wait(timeout=10)
    payload['written_at']=0
    heartbeat.write_text(json.dumps(payload),encoding='utf-8')
    assert subprocess.run([sys.executable,'scripts/healthcheck.py','worker'],cwd=ROOT,capture_output=True).returncode==1


def test_missing_production_database_fails_before_listen(fixture):
    environment = dict(os.environ)
    for name in list(environment):
        if name.startswith('PLAN_REVIEW_DATABASE_') or name.startswith('PLAN_REVIEW_DB_'):
            environment.pop(name)
    environment['DEPLOY_ENV']='company'
    result = subprocess.run([sys.executable,'scripts/serve_container.py'],cwd=ROOT,env=environment,capture_output=True,text=True,timeout=15)
    assert result.returncode!=0 and 'explicit database connection is required' in result.stderr
