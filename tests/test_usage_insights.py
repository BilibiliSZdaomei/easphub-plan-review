from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func,select,update

from backend.api import app
from backend.db import SessionLocal, UsageDay, UsageMetric, UsagePresence, UsageReceipt, User
from backend.demo import DEMO_PASSWORD
from backend.usage_retention import prune
from test_api import clients, P

EVENTS = P + '/usage/events'
REPORT = P + '/usage/insights'


def batch(*events, sent_at=None):
    return {'batch_id':str(uuid.uuid4()),'sent_at':time.time() if sent_at is None else sent_at,'events':list(events)}


def event(kind='view',page='plans',device='desktop',**fields):
    return {'kind':kind,'page':page,'device':device,**fields}


def record(client,*events,**options):
    response = client.post(EVENTS,json=batch(*events,**options))
    assert response.status_code == 200,response.text


def test_usage_totals_reports_heat_and_scope(clients):
    planner,reviewer,admin,spain = clients
    record(planner,event(),event('click',target='filter',x=7,y=5),event('repeat',target='filter'),event('pulse'))
    stamp = time.time()
    midnight = datetime.fromtimestamp(stamp,timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    record(planner,event('view','history'),sent_at=midnight-0.1)
    record(reviewer,event('view','detail','mobile'),event('click','detail','mobile',target='approve',x=0,y=0),
           event('error','detail','mobile',target='submit'),event('validation','detail','mobile',target='submit'))
    record(spain,event('view','rules'),event('pulse'))
    params = {'scope':'team','days':7,'page':'plans','device':'desktop'}
    team = admin.get(REPORT,params=params).json()
    assert team['summary'] == {'page_views':4,'active_days':2,'active_users':3,'online_users':2,'click_count':2,'friction_events':3}
    assert len(team['trend']) == 7 and team['trend'][-2]['active_users'] == 1 and team['trend'][-1]['page_views'] == 3
    assert team['heatmap'] == {'columns':8,'rows':6,'cells':[{'x':7,'y':5,'count':1,'actions':[{'target':'filter','count':1}]}],'total':1}
    assert {x['target']:x['count'] for x in team['actions']} == {'filter':1,'approve':1}
    assert {x['kind'] for x in team['friction']} == {'repeat','error','validation'}
    assert len(team['pages']) == 4 and sum(p['page_views'] for p in team['pages']) == 4
    own = admin.get(REPORT,params={'user_id':reviewer.get(P+'/me').json()['user']['id']}).json()
    assert [p['id'] for p in own['people']] == [admin.get(P+'/me').json()['user']['id']]
    assert own['summary']['page_views'] == 0
    for client in (planner, reviewer):
        for query in ({}, {'scope':'me'}, {'scope':'team'}):
            assert client.get(REPORT,params=query).status_code == 403
    with SessionLocal.begin() as db:
        db.execute(update(User).where(User.username == 'test_steward').values(warehouses=['UK_MAIN']))
    limited = admin.get(REPORT,params=params).json()
    identifiers = {p['id'] for p in limited['people']}
    assert planner.get(P+'/me').json()['user']['id'] in identifiers
    assert spain.get(P+'/me').json()['user']['id'] not in identifiers
    assert limited['summary']['page_views'] == 2 and limited['summary']['online_users'] == 1

    record(planner,event('click',target='import',x=7,y=5),event('click',target='import',x=7,y=5))
    cells = admin.get(REPORT,params=params).json()['heatmap']['cells']
    assert cells == [{'x':7,'y':5,'count':3,'actions':[{'target':'import','count':2},{'target':'filter','count':1}]}]
    with SessionLocal.begin() as db:
        db.execute(update(User).where(User.username == 'test_steward').values(roles=['REVIEWER']))
    assert admin.get(REPORT).status_code == 403
    assert admin.get(REPORT,params=params).status_code == 403


def test_online_distinct_sessions_logout_and_expiry(clients):
    planner,_,admin,_ = clients
    record(planner,event('pulse'),event('pulse'))
    with TestClient(app) as second:
        login = second.post(P+'/sessions',json={'username':'planner','password':DEMO_PASSWORD}).json()
        second.headers['X-CSRF-Token'] = login['csrf']
        record(second,event('pulse'))
        def online():
            return admin.get(REPORT,params={'scope':'team'}).json()['summary']['online_users']
        assert online() == 1
        assert planner.delete(P+'/sessions/current').status_code == 200 and online() == 1
        assert second.delete(P+'/sessions/current').status_code == 200 and online() == 0
    record(admin,event('pulse'),sent_at=time.time()-130)
    assert online() == 0
    record(admin,event('pulse'))
    with SessionLocal.begin() as db:
        db.execute(update(UsagePresence).values(last_seen=time.time()-121))
    assert online() == 0


def test_duplicate_batches_concurrent_commits_and_forwarding(clients,monkeypatch):
    import backend.usage as usage
    planner,_,admin,_ = clients
    forwarded=[]
    def after_commit(events):
        with SessionLocal() as db:
            forwarded.append((db.scalar(select(func.sum(UsageDay.views))),[e.kind for e in events]))
    monkeypatch.setattr(usage,'umami_enabled',lambda:True)
    monkeypatch.setattr(usage,'forward_usage',after_commit)
    payload = batch(event(),event('click',target='save',x=1,y=2))
    barrier = Barrier(2)
    def send(_):
        barrier.wait(timeout=5)
        return planner.post(EVENTS,json=payload).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(send,range(2))) == [200,200]
    assert forwarded == [(1,['view','click'])]
    assert planner.post(EVENTS,json={**payload,'events':[event('pulse')]}).status_code == 409
    assert admin.get(REPORT,params={'scope':'team'}).json()['summary']['click_count'] == 1
    def fail(_):
        raise RuntimeError('synthetic failed commit')
    with monkeypatch.context() as patch:
        patch.setattr(SessionLocal.class_,'commit',fail)
        assert planner.post(EVENTS,json=batch(event())).status_code == 500
    assert len(forwarded) == 1 and admin.get(REPORT,params={'scope':'team'}).json()['summary']['page_views'] == 1


def test_usage_rejects_private_data_invalid_dimensions_and_cross_site(clients):
    planner,_,admin,_ = clients
    for invalid in (event('click',target='account',x=8,y=1), event('click',target='button',x=0,y=True),
                    event('click'), event('error',target='account_name'),event('pulse',x=0),
                    event('view','/plan/real-id'),event('view',title='A private title')):
        assert planner.post(EVENTS,json=batch(invalid)).status_code == 422
    for changes in ({'user_id':'somebody'}, {'events':[]},{'events':[event()]*61},
                    {'sent_at':time.time()-86410},{'sent_at':time.time()+310}):
        assert planner.post(EVENTS,json={**batch(event()),**changes}).status_code == 422
    for headers in ({'Origin':'https://foreign.invalid'}, {'Origin':'https://testserver'},
                    {'Sec-Fetch-Site':'same-site'}, {'X-CSRF-Token':'invalid'}):
        assert planner.post(EVENTS,json=batch(event()),headers=headers).status_code == 403
    assert planner.post(EVENTS,content=b'[' + b' '*16384 + b']').status_code == 413
    assert admin.get(REPORT,params={'page':'private-material'}).status_code == 422
    assert admin.get(REPORT,params={'days':365}).status_code == 422
    assert admin.get(REPORT,params={'scope':'team'}).json()['summary']['active_users'] == 0
    with TestClient(app) as guest:
        assert guest.post(EVENTS,json=batch(event())).status_code == 401
        assert guest.get(REPORT).status_code == 401


def test_rollups_receipts_and_presence_retention(clients):
    planner,*_ = clients
    record(planner,event(),event('pulse'))
    stamp=time.time()
    cutoff = datetime.fromtimestamp(stamp,timezone.utc).date() - timedelta(days=30)
    with SessionLocal.begin() as db:
        db.execute(update(UsageDay).values(day=cutoff))
        db.execute(update(UsageMetric).values(day=cutoff))
        db.execute(update(UsageReceipt).values(expires=stamp-1))
        db.execute(update(UsagePresence).values(last_seen=stamp-121))
        assert prune(db,stamp) is False
        for model in (UsageDay,UsageMetric,UsageReceipt,UsagePresence):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_https_origin_behind_company_proxy(clients,monkeypatch):
    import backend.usage as usage
    planner,*_ = clients
    monkeypatch.setattr(usage,'DEPLOY_ENV','company')
    # TestClient runs the backend on plain HTTP, like the private Nginx upstream.
    shared = {'Host':'work.company.test','Origin':'https://work.company.test','Sec-Fetch-Site':'same-origin'}
    assert planner.post(EVENTS,json=batch(event()),headers=shared).status_code == 200
    for change in ({'Origin':'http://work.company.test','X-Forwarded-Proto':'http'},
                   {'Origin':'https://else.company.test','Sec-Fetch-Site':'same-site'},
                   {'Origin':'https://work.company.test:8080'}, {'Sec-Fetch-Site':'cross-site'}):
        assert planner.post(EVENTS,json=batch(event()),headers={**shared,**change}).status_code == 403
