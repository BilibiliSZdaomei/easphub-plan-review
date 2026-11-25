"""Plan and archived-file access follows the current role, warehouse and review history."""
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api import app
from backend.db import Batch, SessionLocal, User, Version
from backend.demo import DEMO_PASSWORD
from backend.jobs import run_job
from test_api import P, claim, clients, current, post, ready
from test_review_handoff import another_reviewer


def sign_in(client, name):
    response = client.post(P+'/sessions', json={'username':name, 'password':DEMO_PASSWORD})
    assert response.status_code == 200
    client.headers['X-CSRF-Token'] = response.json()['csrf']


def batch_ids(client):
    response = client.get(P+'/batches')
    assert response.status_code == 200
    return {row['id'] for row in response.json()}


def test_private_void_rechecks_direct_links_and_preexisting_files(clients):
    owner, reviewer, admin, spain = clients
    batch, draft = current(owner)
    url = '/batches/'+batch['id']
    version = '/versions/'+draft['id']
    row_id = draft['items'][0]['id']
    export = post(admin, '/exports', {'version_id':draft['id']}).json()
    run_job(export['id'])
    download = '/jobs/'+export['id']+'/download'
    assert admin.get(P+download).status_code == 200
    imported = owner.post(P+'/imports', data={'kind':'plan','warehouse':batch['warehouse'],'version_id':draft['id']},
                          files={'file':('quantities.csv', '物料号,海运计划,空运计划\nTEST,1,0'.encode())})
    assert imported.status_code == 200
    job = imported.json()['id']
    run_job(job)
    assert admin.get(P+'/jobs/'+job+'/download').status_code == 200

    with TestClient(app) as coworker:
        sign_in(coworker, 'europe_planner')
        assert batch['id'] not in batch_ids(coworker)
        assert batch['id'] not in batch_ids(reviewer)
        assert batch['id'] in batch_ids(admin)
        assert coworker.get(P+version).status_code == 403
        assert post(owner, url+'/void', {'revision':draft['revision'], 'reason':'取消本期草稿'}).status_code == 200
        assert owner.get(P+url).json()['state'] == 'VOID'
        assert batch['id'] in batch_ids(owner)
        for other in (coworker, reviewer, admin, spain):
            assert batch['id'] not in batch_ids(other)
            for path in (url, version, version+'/activity', version+'/selection', version+'/confirmation',
                         version+'/items/'+row_id, version+'/diff?against='+draft['id'],
                         '/template?kind=v3&version_id='+draft['id']):
                assert other.get(P+path).status_code == 403, path
            assert post(other, '/exports', {'version_id':draft['id']}).status_code == 403
            assert post(other, url+'/copy', {}).status_code == 403
        assert admin.get(P+'/jobs/'+export['id']).status_code == 403
        assert admin.get(P+download).status_code == 403
        for suffix in ('/jobs/'+job,'/jobs/'+job+'/download','/imports/'+job+'/errors'):
            assert admin.get(P+suffix).status_code == 403


def test_void_after_handoff_visible_to_owner_handlers_and_warehouse_admin(clients):
    owner, first, admin, other_warehouse = clients
    batch, draft = ready(owner)
    version = '/versions/'+draft['id']
    batch_path = '/batches/'+batch['id']
    with TestClient(app) as next_reviewer, TestClient(app) as uninvolved:
        next_id = another_reviewer(next_reviewer)
        with SessionLocal.begin() as db:
            db.scalar(select(User).where(User.username=='europe_planner')).roles = ['REVIEWER']
        sign_in(uninvolved, 'europe_planner')
        assert post(owner, version+'/submit', {'revision':draft['revision']}).status_code == 200
        assert batch['id'] in batch_ids(uninvolved)
        claimed = claim(first, version)
        transfer = post(first, version+'/transfer', {'revision':claimed['revision'], 'reviewer_id':next_id})
        assert transfer.status_code == 200
        return_body = {'revision':transfer.json()['revision'], 'ids':[draft['items'][0]['id']], 'reason':'请修改本行'}
        returned = post(next_reviewer, version+'/return', return_body, key='return-once')
        assert returned.status_code == 200
        new_version = '/versions/'+returned.json()['version_id']
        next_draft = owner.get(P+new_version).json()
        assert post(owner, batch_path+'/void', {'revision':next_draft['revision'], 'reason':'不再提报'}).status_code == 200
        for allowed in (owner, first, next_reviewer, admin):
            assert batch['id'] in batch_ids(allowed)
            assert allowed.get(P+new_version+'/activity').status_code == 200
        for hidden in (uninvolved, other_warehouse):
            assert batch['id'] not in batch_ids(hidden)
            assert hidden.get(P+version).status_code == 403
        with SessionLocal.begin() as db:
            db.get(User,next_id).warehouses = ['ES_NSC']
        assert next_reviewer.get(P+batch_path).status_code == 403
        assert post(next_reviewer, version+'/return', return_body, key='return-once').status_code == 403


def test_void_legacy_line_decisions_and_submission_without_review(clients):
    owner, reviewer, admin, _ = clients
    batch, draft = current(owner)
    with SessionLocal.begin() as db:
        db.get(Batch,batch['id']).state = 'VOID'
        version = db.get(Version,draft['id'])
        version.state = 'VOID'
        version.submitted_at = version.created_at
    assert batch['id'] not in batch_ids(admin)
    assert batch['id'] not in batch_ids(reviewer)
    with SessionLocal.begin() as db:
        version = db.get(Version,draft['id'])
        rows = deepcopy(version.items)
        reviewer_id = db.scalar(select(User.id).where(User.username=='test_reviewer'))
        rows[0]['decision'] = {'status':'REJECTED', 'reviewer_id':reviewer_id}
        version.items = rows
    assert batch['id'] in batch_ids(admin)
    assert batch['id'] in batch_ids(reviewer)
    with TestClient(app) as uninvolved:
        another_reviewer(uninvolved)
        assert batch['id'] not in batch_ids(uninvolved)
