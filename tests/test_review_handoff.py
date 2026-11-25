import pytest
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
        assert {u['id'] for u in candidates}=={other_id,steward.get(P+'/me').json()['user']['id']}
        assert post(assigned,path+'/transfer',{'revision':rev,'reviewer_id':batch['owner']}).status_code==422
        assert post(other,path+'/transfer',{'revision':rev,'reviewer_id':winner_id}).status_code==403
        blank=post(assigned,path+'/reviews',{'revision':rev,'ids':[first],'decision':'REJECTED'})
        assert blank.status_code==200
        refused=post(assigned,path+'/reviews',{'revision':blank.json()['revision'],'ids':[first],'decision':'REJECTED','reason':'超出车型需求'})
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
        assert post(other,path+'/finalize',{'revision':rev}).status_code==422
        result=post(other,path+'/finalize',{'revision':rev,'outcome':'REJECTED'})
        assert result.status_code==200 and result.json()['state']=='REJECTED'
        final=planner.get(P+path).json()
        assert final['reviewer_id']==other_id and final['summary']['rejected']==1
        assert planner.get(P+path+'/items/'+first).json()['decision']==frozen
        assert planner.get(P+'/batches/'+batch['id']).json()['state']=='REJECTED'
        from backend.exporting import export_workbook
        from openpyxl import load_workbook
        from io import BytesIO
        wb=load_workbook(BytesIO(export_workbook({'items':final['items'],'metadata':{'版本状态':final['state']}})),data_only=True)
        header,*rows=list(wb["计划审核结果"].values)
        refused_row=next(row for row in rows if row[header.index('人工决定（留档）')]=='不批准')
        assert refused_row[header.index('本版可执行海运量')]==0 and refused_row[header.index('本版可执行空运量')]==0
        assert refused_row[header.index('复审依据')]=='超出车型需求'
        wb.close()


def test_whole_return_preserves_frozen_decisions_and_reopens_rejected_rows_first(clients):
    planner,reviewer,_,_=clients
    _,draft=ready(planner)
    path='/versions/'+draft['id']
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    version=claim(reviewer,path)
    first=next(r for r in version['items'] if r['result']['quantity_status']=='WITHIN')
    over=next(r for r in version['items'] if r['result']['quantity_status']=='ABOVE')
    refused=next(r for r in version['items'] if r['id'] not in (first['id'],over['id']))
    ids=[first['id'],over['id']]
    meta=post(reviewer,path+'/review-summary',{'ids':ids,'only_pending':True}).json()
    assert meta['exception_count']==1
    accepted=post(reviewer,path+'/reviews',{'revision':version['revision'],'ids':ids,'decision':'APPROVED'}).json()
    assert accepted['exception_count']==1
    denied=post(reviewer,path+'/reviews',{'revision':accepted['revision'],'ids':[refused['id']],'decision':'REJECTED'}).json()
    original={r['id']:r['decision'] for r in reviewer.get(P+path).json()['items']}
    assert original[first['id']]['status']=='APPROVED'
    assert original[over['id']]['status']=='EXCEPTION_APPROVED' and not original[over['id']]['reason']
    assert original[refused['id']]['status']=='REJECTED' and not original[refused['id']]['reason']
    returned=post(reviewer,path+'/return',{'revision':denied['revision']})
    assert returned.status_code==200,returned.text
    assert original=={r['id']:r['decision'] for r in planner.get(P+path).json()['items']}
    new='/versions/'+returned.json()['version_id']
    view=planner.get(P+new+'?page_size=1').json()
    assert view['reviewer_id'] is None
    assert view['items'][0]['id']==refused['id'] and view['items'][0]['return_requested']
    assert view['items'][0]['decision'] is None and view['items'][0]['previous_decision']==original[refused['id']]
    assert planner.get(P+new+'/selection?filter=returned').json()['ids']==[refused['id']]
    assert planner.get(P+new+'/items/'+over['id']).json()['decision']==original[over['id']]
    patched=planner.patch(P+new+'/items',json={'revision':view['revision'],'changes':[{'id':first['id'],'values':{'sea_plan_qty':'5555'}}]})
    assert patched.status_code==200
    assert planner.get(P+new+'/items/'+first['id']).json()['decision'] is None
    assert post(planner,new+'/submit',{'revision':patched.json()['revision']}).status_code==200
    fresh=claim(reviewer,new)
    assert fresh['summary']['reviewed']==1 and not fresh['summary']['rejected']
    assert post(reviewer,new+'/finalize',{'revision':fresh['revision']}).json()['state']=='APPROVED'


@pytest.mark.parametrize('mark_all', [False,True])
def test_whole_return_without_any_rejections_or_note(clients,mark_all):
    planner,reviewer,_,_=clients
    _,version=ready(planner)
    path='/versions/'+version['id']
    assert post(planner,path+'/submit',{'revision':version['revision']}).status_code==200
    v=claim(reviewer,path)
    rev=v['revision']
    if mark_all:
        rev=post(reviewer,path+'/reviews',{'revision':rev,'ids':[r['id'] for r in v['items']],'decision':'APPROVED'}).json()['revision']
    returned=post(reviewer,path+'/return',{'revision':rev})
    assert returned.status_code==200,returned.text
    next_version=planner.get(P+'/versions/'+returned.json()['version_id']).json()
    assert not next_version['summary']['return_requested']
    assert next_version['summary']['reviewed']==(len(v['items']) if mark_all else 0)


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
        assert post(peer,path+'/finalize',{'revision':rev}).status_code==422
        assert post(peer,path+'/finalize',{'revision':rev,'outcome':'REJECTED'}).json()['state']=='REJECTED'
        final=planner.get(P+path).json()
        assert final['summary']['total']==final['summary']['rejected']

def test_older_returned_draft_reopens_carried_rejection_on_read_and_submit(clients):
    from copy import deepcopy
    from backend.db import SessionLocal, Version
    planner,reviewer,_,_=clients
    _,draft=ready(planner)
    path='/versions/'+draft['id']
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    rv=claim(reviewer,path)
    target=rv['items'][-1]['id']
    rev=post(reviewer,path+'/reviews',{'revision':rv['revision'],'ids':[target],'decision':'REJECTED','reason':'核对库存'}).json()['revision']
    returned=post(reviewer,path+'/return',{'revision':rev}).json()['version_id']
    with SessionLocal.begin() as db:
        ver=db.get(Version,returned)
        rows=deepcopy(ver.items)
        row=next(r for r in rows if r['id']==target)
        row['decision']=deepcopy(row['previous_decision'])
        row.pop('return_requested');row.pop('return_reason')
        ver.items=rows
    np='/versions/'+returned
    v=planner.get(P+np+'?page_size=1').json()
    assert v['items'][0]['id']==target and v['items'][0]['return_reason']=='核对库存'
    assert v['summary']['return_requested']==1 and not v['summary']['rejected']
    assert post(planner,np+'/submit',{'revision':v['revision']}).status_code==200
    fresh=claim(reviewer,np)
    assert fresh['summary']['reviewed']==0
    assert planner.get(P+path+'/items/'+target).json()['decision']['status']=='REJECTED'


def test_v3_review_outcomes_for_flags_warnings_and_negative_calculations():
    from backend.exceptions import approval_status
    from backend.rules import MODEL_V3, calculate, default_package
    from test_rules import row
    package=default_package(MODEL_V3)
    item=row(replacement_target=5,sales_target=6,on_hand_qty=2,net_supply_before_plan=0,
             sea_plan_qty=3,air_plan_qty=2,current_sales=0,shortage_qty=0,avg_sales_3m=1,avg_sales_6m=1)
    result=calculate(item,package)
    assert result['quantity_status']=='WITHIN' and 'AIR' in result['manual_flags']
    assert approval_status(result)=='APPROVED'
    # W + X + Y = 21 outruns the [5, 6] range.
    over=calculate({**item,'air_plan_qty':18},package)
    assert over['future_qty']=='21' and over['quantity_status']=='ABOVE'
    assert approval_status(over)=='EXCEPTION_APPROVED'
    # A delay recommendation alone changes the approval classification.
    delay=calculate({**item,'fleet_qty':10000,'on_hand_qty':5,'net_supply_before_plan':10,
                     'replacement_target':10,'sales_target':20},package)
    assert delay['quantity_status']=='WITHIN' and delay['delay_replenishment']
    assert approval_status(delay)=='EXCEPTION_APPROVED'
    assert approval_status({**result,'turnover_warning':'周转过高'})=='APPROVED'
    assert approval_status({**result,'quantity_status':'NOT_APPLICABLE','review_mode':'MANUAL'})=='APPROVED'
    assert approval_status({**result,'quantity_status':'NOT_APPLICABLE','review_mode':'EXEMPT'})=='APPROVED'

def finalization_evidence(batch_id,version_id):
    from sqlalchemy import func,select
    from backend.db import Audit,Batch,Idempotency,NotificationEvent,PlanUndo,SessionLocal,Version
    with SessionLocal() as db:
        batch=db.get(Batch,batch_id)
        version=db.get(Version,version_id)
        counts=[db.scalar(select(func.count()).select_from(table)) for table in (Audit,Idempotency,NotificationEvent,PlanUndo)]
        return (version.items,version.state,version.revision,version.finalized_at,batch.state,batch.updated_at,*counts)


@pytest.mark.parametrize('row_status',['REJECTED','RETURNED'])
def test_rejected_or_legacy_returned_item_blocks_passing_the_entire_plan(clients,row_status):
    from copy import deepcopy
    from sqlalchemy import select
    from backend.db import NotificationEvent,SessionLocal,Version
    planner,reviewer,_,_=clients
    batch,draft=ready(planner)
    path='/versions/'+draft['id']
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    view=claim(reviewer,path)
    ordinary=next(row for row in view['items'] if row['approval_status']=='APPROVED')
    exception=next(row for row in view['items'] if row['approval_status']=='EXCEPTION_APPROVED')
    selected=[ordinary['id'],exception['id']]
    refused=next(row['id'] for row in view['items'] if row['id'] not in selected)
    rev=post(reviewer,path+'/reviews',{'revision':view['revision'],'ids':selected,'decision':'APPROVED'}).json()['revision']
    rev=post(reviewer,path+'/reviews',{'revision':rev,'ids':[refused],'decision':'REJECTED'}).json()['revision']
    if row_status=='RETURNED':
        # Exercise the saved legacy code at the same entry point as existing running plans.
        with SessionLocal.begin() as db:
            version=db.get(Version,draft['id'])
            rows=deepcopy(version.items)
            next(row['decision'] for row in rows if row['id']==refused)['status']='RETURNED'
            version.items=rows
        rev=reviewer.get(P+path).json()['revision']
    before=finalization_evidence(batch['id'],draft['id'])
    total=len(before[0])
    report=reviewer.get(P+path+'/confirmation?stage=finalize').json()
    assert report['approval_blocked'] and report['rejected']==1
    assert report['reviewed_approved']==2 and report['reviewed_exception']==1
    assert report['return_marked']==int(row_status=='RETURNED') and report['unreviewed']==total-3
    assert report['unreviewed_exception']==report['exception_approved']==0
    base={'revision':rev,'issue_hash':report['issue_hash']}
    for extra in ({},{'outcome':'APPROVED'},{'outcome':'PARTIALLY_APPROVED'},{'outcome':None}):
        assert post(reviewer,path+'/finalize',{**base,**extra}).status_code==422
    assert post(reviewer,path+'/finalize',{**base,'outcome':'REJECTED','issue_hash':'outdated'}).status_code==409
    assert finalization_evidence(batch['id'],draft['id'])==before
    body={**base,'outcome':'REJECTED'}
    closed=post(reviewer,path+'/finalize',body,'close-rejected-plan')
    assert closed.status_code==200 and closed.json()['state']=='REJECTED'
    assert post(reviewer,path+'/finalize',body,'close-rejected-plan').json()==closed.json()
    after=finalization_evidence(batch['id'],draft['id'])
    assert after[0]==before[0] and after[1]=='REJECTED' and after[3] and after[4]=='REJECTED'
    record=next(event['detail'] for event in planner.get(P+path+'/activity').json()['items'] if event['action']=='完成终审')
    expected={'outcome':'REJECTED','approved':0,'rejected':total,'reviewed_approved':2,'reviewed_rejected':1,
              'reviewed_exception':1,'unreviewed':total-3,'batch_approved':0,'exception_approved':0}
    assert {key:record[key] for key in expected}==expected
    with SessionLocal() as db:
        notes=[p for p in db.scalars(select(NotificationEvent.payload)) if p.get('kind')=='FINALIZED' and p.get('version_id')==draft['id']]
    assert len(notes)==1 and '整单不批准' in notes[0]['text'] and f'{total} 行均不执行' in notes[0]['text']


def test_whole_rejection_requires_at_least_one_rejected_item(clients):
    planner,reviewer,_,_=clients
    batch,draft=ready(planner)
    path='/versions/'+draft['id']
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    view=claim(reviewer,path)
    before=finalization_evidence(batch['id'],draft['id'])
    report=reviewer.get(P+path+'/confirmation?stage=finalize').json()
    assert not report['approval_blocked'] and report['unreviewed']==len(before[0])
    assert report['rejected']==report['reviewed_approved']==0
    base={'revision':view['revision'],'issue_hash':report['issue_hash']}
    assert post(reviewer,path+'/finalize',{**base,'outcome':'REJECTED'}).status_code==422
    assert finalization_evidence(batch['id'],draft['id'])==before
    completed=post(reviewer,path+'/finalize',{**base,'outcome':'APPROVED'})
    assert completed.status_code==200 and completed.json()['state']=='APPROVED'
    record=next(event['detail'] for event in planner.get(P+path+'/activity').json()['items'] if event['action']=='完成终审')
    assert record['approved']==report['total']==record['batch_approved']
    assert not record['rejected'] and record['exception_approved']==report['unreviewed_exception']
