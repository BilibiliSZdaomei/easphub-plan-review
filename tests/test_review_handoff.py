from test_api import P, clients, post, ready, claim
from test_data import csvfile, upload


def test_bulk_review_preserves_individual_decisions_and_audits_applied_ids(clients):
    planner, reviewer, _, _ = clients
    batch, draft = ready(planner)
    path = '/versions/' + draft['id']
    assert post(planner, path+'/submit', {'revision':draft['revision']}).status_code == 200
    version = claim(reviewer,path)
    ordinary = [r['id'] for r in version['items'] if r['result']['quantity_status']=='WITHIN'
                and not r['result']['manual_flags'] and r['result']['data_status']!='ERROR']
    first, second = ordinary[:2]
    saved = post(reviewer, path+'/reviews', {'revision':version['revision'],'ids':[first],
                 'decision':'EXCEPTION_APPROVED','reason_code':'特殊物料','reason':'复核后保留特殊订单'})
    assert saved.status_code == 200
    decision = reviewer.get(P+path+'/items/'+first).json()['decision']
    meta = post(reviewer, path+'/review-summary', {'ids':[first,second],'only_pending':True}).json()
    assert meta['count']==1 and meta['preserved']==1
    bulk = post(reviewer, path+'/reviews', {'revision':saved.json()['revision'],'ids':[first,second],
                 'decision':'APPROVED','only_pending':True}).json()
    assert bulk['count']==1 and bulk['preserved']==1 and not bulk['skipped']
    assert reviewer.get(P+path+'/items/'+first).json()['decision']==decision
    event = next(event for event in reviewer.get(P+'/batches/'+batch['id']).json()['events']
                 if event['action']=='保存行复审')
    assert event['detail']['ids']==[second]
    repeat = post(reviewer, path+'/reviews', {'revision':bulk['revision'],'ids':[first],
                  'decision':'APPROVED','only_pending':True}).json()
    assert repeat['count']==0 and repeat['preserved']==1 and repeat['revision']==bulk['revision']


def test_targeted_return_carries_only_this_round_through_plan_reimport(clients):
    planner, reviewer, _, spain = clients
    batch, draft = ready(planner)
    path = '/versions/'+draft['id']
    assert post(planner, path+'/submit', {'revision':draft['revision']}).status_code == 200
    version = claim(reviewer,path)
    marked = next(row for row in version['items'] if row['input']['material_code']=='DEMO-0001')
    other = next(row for row in version['items'] if row['input']['material_code']=='DEMO-0002')
    payload = {'revision':version['revision'],'reason':'请核对指定物料的补货节奏'}
    assert post(reviewer,path+'/return',{**payload,'ids':['wrong-row']}).status_code==422
    assert reviewer.get(P+path).json()['state']=='IN_REVIEW'
    returned = post(reviewer,path+'/return',{**payload,'ids':[marked['id']]}).json()
    current = '/versions/'+returned['version_id']
    selected = planner.get(P+current+'?filter=returned').json()
    assert selected['summary']['return_requested']==1
    assert selected['items'][0]['id']==marked['id'] and selected['items'][0]['decision'] is None
    assert planner.get(P+current+'/selection?filter=returned').json()['ids']==[marked['id']]
    assert spain.get(P+current+'/selection?filter=returned').status_code==403
    previous = planner.get(P+path+'/items/'+marked['id']).json()
    assert not previous.get('return_requested')
    event = planner.get(P+'/batches/'+batch['id']).json()['events'][0]
    assert event['detail']['material_codes']==['DEMO-0001']
    job = upload(planner,'plan',csvfile(['物料号,海运计划,空运计划','DEMO-0001,35,0','DEMO-0002,35,0']))
    assert post(planner,'/imports/'+job['id']+'/commit',{'version_id':returned['version_id'],
                'revision':selected['revision']}).status_code==200
    assert planner.get(P+current+'/selection?filter=returned').json()['ids']==[marked['id']]
    result = planner.get(P+current+'/confirmation').json()
    submitted = post(planner,current+'/submit',{'revision':result['revision'],'force':True,
                     'accept_issues':True,'reason':'核实后重新提交','issue_hash':result['issue_hash']})
    assert submitted.status_code==200
    claimed = claim(reviewer,current)
    again = post(reviewer,current+'/return',{'revision':claimed['revision'],'ids':[other['id']],
                 'reason':'请核对另一项'}).json()
    assert planner.get(P+'/versions/'+again['version_id']+'/selection?filter=returned').json()['ids']==[other['id']]
    assert planner.get(P+current+'/items/'+marked['id']).json()['return_requested']



def another_reviewer(client, warehouses=('UK_MAIN',)):
    from backend.auth import hasher
    from backend.db import SessionLocal, User
    from backend.demo import DEMO_PASSWORD
    with SessionLocal.begin() as db:
        u = User(username='test_peer',name='第二复审人',roles=['REVIEWER'],warehouses=list(warehouses),password_hash=hasher.hash(DEMO_PASSWORD))
        db.add(u)
        db.flush()
        user_id = u.id
    session = client.post(P+'/sessions',json={'username':'test_peer','password':DEMO_PASSWORD})
    assert session.status_code==200
    client.headers['X-CSRF-Token'] = session.json()['csrf']
    return user_id


def test_single_winner_concurrent_claim_and_transfer_with_partial_decisions(clients):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from backend.api import app
    planner,reviewer,steward,spain=clients
    batch,draft=ready(planner)
    path='/versions/'+draft['id']
    submitted=post(planner,path+'/submit',{'revision':draft['revision']}).json()
    rev=submitted['revision']
    first,second=(r['id'] for r in draft['items'][:2])
    assert post(reviewer,path+'/reviews',{'revision':rev,'ids':[first]}).status_code==403
    assert post(reviewer,path+'/return',{'revision':rev,'ids':[first],'reason':'未领取'}).status_code==403
    assert post(reviewer,path+'/finalize',{'revision':rev}).status_code==403
    assert post(spain,path+'/claim',{'revision':rev}).status_code==403
    with TestClient(app) as peer:
        another_reviewer(peer)
        clients_list=[reviewer,peer]
        barrier=Barrier(2)
        def compete(person):
            barrier.wait(timeout=5)
            return post(person,path+'/claim',{'revision':rev})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(compete,clients_list))
        assert sorted(r.status_code for r in results)==[200,409], [r.text for r in results]
        index=next(i for i,r in enumerate(results) if r.status_code==200)
        assigned,other=clients_list[index],clients_list[1-index]
        winner_id=assigned.get(P+'/me').json()['user']['id']
        other_id=other.get(P+'/me').json()['user']['id']
        rev=results[index].json()['revision']
        assert assigned.get(P+path).json()['reviewer_id']==winner_id
        assert assigned.get(P+'/batches/'+batch['id']).json()['reviewer_id']==winner_id
        candidates=assigned.get(P+path+'/reviewers').json()
        assert [u['id'] for u in candidates]==[other_id]
        assert post(assigned,path+'/transfer',{'revision':rev,'reviewer_id':batch['owner']}).status_code==422
        assert post(other,path+'/transfer',{'revision':rev,'reviewer_id':winner_id}).status_code==403
        assert post(assigned,path+'/reviews',{'revision':rev,'ids':[first],'decision':'REJECTED'}).status_code==422
        refused=post(assigned,path+'/reviews',{'revision':rev,'ids':[first],'decision':'REJECTED','reason':'超出车型需求'})
        assert refused.status_code==200
        frozen=assigned.get(P+path+'/items/'+first).json()['decision']
        key='transfer-once'
        transfer={'revision':refused.json()['revision'],'reviewer_id':other_id}
        accepted=post(assigned,path+'/transfer',transfer,key)
        assert accepted.status_code==200
        assert post(assigned,path+'/transfer',transfer,key).json()==accepted.json()
        rev=accepted.json()['revision']
        assert post(assigned,path+'/finalize',{'revision':rev}).status_code==403
        assert post(assigned,path+'/reviews',{'revision':rev,'ids':[second]}).status_code==403
        assert other.get(P+path+'/items/'+first).json()['decision']==frozen
        assert other.get(P+path+'?filter=rejected').json()['total']==1
        result=post(other,path+'/finalize',{'revision':rev})
        assert result.status_code==200 and result.json()['state']=='PARTIALLY_APPROVED'
        final=planner.get(P+path).json()
        assert final['reviewer_id']==other_id and final['summary']['rejected']==1
        assert planner.get(P+path+'/items/'+first).json()['decision']==frozen
        assert planner.get(P+'/batches/'+batch['id']).json()['state']=='PARTIALLY_APPROVED'
        from backend.exporting import export_workbook
        from openpyxl import load_workbook
        from io import BytesIO
        wb=load_workbook(BytesIO(export_workbook({'items':final['items'],'metadata':{'版本状态':final['state']}})),data_only=True)
        header,*rows=list(wb.active.values)
        refused_row=next(row for row in rows if row[header.index('人工决定（留档）')]=='不批准')
        assert refused_row[header.index('终审核准海运量')]==0 and refused_row[header.index('终审核准空运量')]==0
        assert refused_row[header.index('复审依据')]=='超出车型需求'
        wb.close()


def test_line_specific_returns_preserve_untouched_decisions_and_invalidate_edits(clients):
    planner,reviewer,_,_=clients
    batch,draft=ready(planner)
    path='/versions/'+draft['id']
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    version=claim(reviewer,path)
    ids=[r['id'] for r in version['items'][:5]]
    rev=version['revision']
    kinds=['APPROVED','EXCEPTION_APPROVED','REJECTED','RETURNED','RETURNED']
    notes=['','高峰需求','停供','核对库存','补充急件原因']
    assert post(reviewer,path+'/return',{'revision':rev,'reason':'只有整批原因'}).status_code==422
    for i,action,note in zip(ids,kinds,notes):
        resp=post(reviewer,path+'/reviews',{'revision':rev,'ids':[i],'decision':action,'reason':note})
        assert resp.status_code==200,resp.text
        rev=resp.json()['revision']
    assert post(reviewer,path+'/finalize',{'revision':rev}).status_code==422
    marked=reviewer.get(P+path+'?filter=return_marked').json()
    assert marked['total']==2 and marked['summary']['return_marked']==2
    new=post(reviewer,path+'/return',{'revision':rev})
    assert new.status_code==200,new.text
    np='/versions/'+new.json()['version_id']
    view=planner.get(P+np).json()
    assert view['reviewer_id'] is None
    rows={r['id']:r for r in view['items']}
    assert [rows[i]['decision']['status'] for i in ids[:3]]==kinds[:3]
    assert all(rows[i]['decision'] is None for i in ids[3:])
    assert [rows[i]['return_reason'] for i in ids[3:]]==notes[3:]
    assert all(rows[i]['previous_decision']['reason']==note for i,note in zip(ids,notes))
    patched=planner.patch(P+np+'/items',json={'revision':view['revision'],'changes':[{'id':ids[0],'values':{'sea_plan_qty':'5555'}}]})
    assert patched.status_code==200
    assert planner.get(P+np+'/items/'+ids[0]).json()['decision'] is None
    assert planner.get(P+path+'/items/'+ids[0]).json()['decision']['status']=='APPROVED'
    submitted=post(planner,np+'/submit',{'revision':patched.json()['revision']})
    assert submitted.status_code==200
    fresh=claim(reviewer,np)
    assert fresh['summary']['reviewed']==2
    assert post(reviewer,np+'/finalize',{'revision':fresh['revision']}).json()['state']=='PARTIALLY_APPROVED'


def test_ineligible_previous_reviewer_can_be_replaced_and_all_rows_rejected(clients):
    from fastapi.testclient import TestClient
    from backend.api import app
    from backend.db import SessionLocal, User
    planner,reviewer,_,_=clients
    _,draft=ready(planner)
    path='/versions/'+draft['id']
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    assigned=claim(reviewer,path)
    with TestClient(app) as peer:
        another_reviewer(peer)
        with SessionLocal.begin() as db:
            db.get(User,assigned['reviewer_id']).active=False
        assert peer.get(P+path).json()['reviewer_id'] is None
        assigned=claim(peer,path)
        rev=post(peer,path+'/reviews',{'revision':assigned['revision'],'ids':[r['id'] for r in assigned['items']],
                 'decision':'REJECTED','reason':'本期需求已取消'}).json()['revision']
        assert post(peer,path+'/finalize',{'revision':rev}).json()['state']=='REJECTED'
        final=planner.get(P+path).json()
        assert final['summary']['total']==final['summary']['rejected']
