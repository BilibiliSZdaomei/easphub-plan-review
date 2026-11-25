from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api import app
from backend.db import Audit, PlanRedo, PlanUndo, SessionLocal, Snapshot, uid
from test_api import P, claim, clients, current, post, ready
from test_data import csvfile, upload


def test_saved_edits_and_deleted_rows_undo_in_order_with_fresh_revisions(clients):
    planner, reviewer, _, spain = clients
    batch, start = current(planner)
    path = '/versions/'+start['id']
    ids = [r['id'] for r in start['items'][:2]]
    changes = [{'id':rid,'values':{'sea_plan_qty':'61','reason':'预计用量增加'}} for rid in ids]
    saved = planner.patch(P+path+'/items',json={'revision':start['revision'],'changes':changes})
    assert saved.status_code == 200, saved.text
    after_edit = planner.get(P+path).json()
    assert after_edit['undo'] == {'label':'修改计划明细','count':2}
    assert spain.get(P+path).status_code == 403
    assert post(reviewer,path+'/undo',{'revision':after_edit['revision']}).status_code == 403
    deleted = planner.request('DELETE',P+path+'/items',json={'ids':ids,'revision':after_edit['revision']})
    assert deleted.status_code == 200
    after_delete = planner.get(P+path).json()
    rev = deleted.json()['revision']
    assert post(planner,path+'/undo',{'revision':after_edit['revision']}).status_code == 409
    first = post(planner,path+'/undo',{'revision':rev},'undo-delete')
    assert first.status_code == 200, first.text
    assert post(planner,path+'/undo',{'revision':rev},'undo-delete').json()==first.json()
    middle = planner.get(P+path).json()
    assert middle['items'] == after_edit['items'] and middle['undo'] == after_edit['undo']
    assert middle['revision'] > rev
    assert post(planner,path+'/undo',{'revision':middle['revision']}).status_code == 200
    final = planner.get(P+path).json()
    assert final['items'] == start['items'] and final['undo'] is None
    assert post(planner,path+'/undo',{'revision':final['revision']}).status_code == 409
    # Resume in another browser session without an in-memory copy of the action stack.
    with TestClient(app) as second_tab:
        second_tab.cookies.update(planner.cookies)
        second_tab.headers['X-CSRF-Token']=planner.headers['X-CSRF-Token']
        refreshed=second_tab.get(P+path).json()
        assert refreshed['redo']=={'label':'修改计划明细','count':2}
        assert post(spain,path+'/redo',{'revision':refreshed['revision']}).status_code==403
        assert post(second_tab,path+'/redo',{'revision':rev}).status_code==409
        redone=post(second_tab,path+'/redo',{'revision':refreshed['revision']},'repeat-edit')
        assert redone.status_code==200,redone.text
        assert set(redone.json()['affected_ids'])==set(ids)
        assert post(second_tab,path+'/redo',{'revision':refreshed['revision']},'repeat-edit').json()==redone.json()
        repeated=second_tab.get(P+path).json()
        assert repeated['items']==after_edit['items'] and repeated['redo']=={'label':'删除物料','count':2}
        assert post(second_tab,path+'/redo',{'revision':repeated['revision']}).status_code==200
        snapshot=second_tab.get(P+path).json()
        assert snapshot['redo'] is None and snapshot['items']==after_delete['items']
        assert post(second_tab,path+'/redo',{'revision':snapshot['revision']}).status_code==409
    with SessionLocal() as db:
        assert [e.detail['operation'] for e in db.scalars(select(Audit).where(
            Audit.batch_id==batch['id'],Audit.action=='重做明细操作').order_by(Audit.created_at))]==['修改计划明细','删除物料']
        events = db.scalars(select(Audit).where(Audit.batch_id==batch['id'],Audit.action=='撤销明细操作')
                           .order_by(Audit.created_at)).all()
        assert [(e.detail['operation'],e.detail['count']) for e in events]==[('删除物料',2),('修改计划明细',2)]


def test_replace_import_restores_removed_rows_and_original_source(clients):
    planner = clients[0]
    _, before = current(planner)
    path = '/versions/'+before['id']
    job = upload(planner,'plan',csvfile(['物料号,海运计划,空运计划','DEMO-0002,199,']))
    imported = post(planner,'/imports/'+job['id']+'/commit',{'version_id':before['id'],'revision':before['revision']})
    assert imported.status_code == 200, imported.text
    now = planner.get(P+path).json()
    assert now['total'] == 1 and now['undo']['label'] == '导入计划'
    assert post(planner,path+'/undo',{'revision':now['revision']}).status_code == 200
    back = planner.get(P+path).json()
    assert back['items'] == before['items'] and back['snapshot']==before['snapshot']
    assert back['redo']=={'label':'导入计划','count':len(before['items'])}
    again=post(planner,path+'/redo',{'revision':back['revision']})
    assert again.status_code==200,again.text
    imported_again=planner.get(P+path).json()
    assert imported_again['items']==now['items'] and imported_again['snapshot']==now['snapshot']
    assert imported_again['items'][0]['input']['plan_source']['job_id']==job['id']


def test_batch_review_undo_preserves_prior_decision_and_cannot_cross_transfer(clients):
    planner, reviewer, admin, _ = clients
    _, draft = ready(planner)
    path = '/versions/'+draft['id']
    assert draft['undo'] and post(planner,path+'/submit',{'revision':draft['revision']}).status_code == 200
    version = claim(reviewer,path)
    assert planner.get(P+path).json()['undo'] is None and version['undo'] is None
    assert post(planner,path+'/undo',{'revision':version['revision']}).status_code == 403
    ids = [r['id'] for r in version['items'][:4]]
    first = post(reviewer,path+'/reviews',{'revision':version['revision'],'ids':ids[:1],
                  'decision':'REJECTED','reason':'核对库存'})
    assert first.status_code == 200, first.text
    before = reviewer.get(P+path).json()
    bulk = post(reviewer,path+'/reviews',{'revision':before['revision'],'ids':ids,'decision':'APPROVED','only_pending':True})
    assert bulk.status_code == 200, bulk.text
    after = reviewer.get(P+path).json()
    assert after['undo']=={'label':'复审决定','count':3}
    assert admin.get(P+path).json()['undo'] is None
    assert post(admin,path+'/undo',{'revision':after['revision']}).status_code == 403
    assert post(reviewer,path+'/undo',{'revision':after['revision']}).status_code == 200
    restored = reviewer.get(P+path).json()
    assert restored['items'] == before['items'] and restored['undo']['count']==1
    assert restored['redo']=={'label':'复审决定','count':3}
    assert admin.get(P+path).json()['redo'] is None
    assert post(admin,path+'/redo',{'revision':restored['revision']}).status_code==403
    assert post(reviewer,path+'/redo',{'revision':restored['revision']}).status_code==200
    again=reviewer.get(P+path).json()
    assert again['items']==after['items']  # Original reviewer, review timestamp, exception and reject decisions.
    assert post(reviewer,path+'/undo',{'revision':again['revision']}).status_code==200
    restored=reviewer.get(P+path).json()
    # A handoff starts a fresh stack even after a transfer back to the original reviewer.
    choices = reviewer.get(P+path+'/reviewers').json()
    to = next(c for c in choices if c['username']=='test_steward')
    sent = post(reviewer,path+'/transfer',{'revision':restored['revision'],'reviewer_id':to['id']})
    assert sent.status_code == 200, sent.text
    assert admin.get(P+path).json()['undo'] is None
    assert post(reviewer,path+'/undo',{'revision':sent.json()['revision']}).status_code == 403
    assert post(admin,path+'/undo',{'revision':sent.json()['revision']}).status_code == 409
    assert admin.get(P+path).json()['redo'] is None
    assert post(reviewer,path+'/redo',{'revision':sent.json()['revision']}).status_code==403
    assert post(admin,path+'/redo',{'revision':sent.json()['revision']}).status_code==409
    forwarded=sent.json()['revision']
    initial_reviewer=next(c for c in admin.get(P+path+'/reviewers').json() if c['username']=='test_reviewer')
    returned=post(admin,path+'/transfer',{'revision':forwarded,'reviewer_id':initial_reviewer['id']})
    assert returned.status_code==200,returned.text
    assert reviewer.get(P+path).json()['redo'] is None
    assert post(reviewer,path+'/redo',{'revision':returned.json()['revision']}).status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(PlanUndo.revision).where(PlanUndo.version_id==draft['id'])) is None
        assert db.scalar(select(PlanRedo.revision).where(PlanRedo.version_id==draft['id'])) is None



def test_add_and_basis_undo_restore_row_identity_and_stock_basis(clients):
    planner = clients[0]
    _, before = current(planner)
    path = '/versions/'+before['id']
    row = before['items'][0]
    remove = planner.request('DELETE',P+path+'/items',json={'revision':before['revision'],'ids':[row['id']]})
    added = post(planner,path+'/items',{'revision':remove.json()['revision'],'items':[
                 {'material_code':row['input']['material_code'],'sea_plan_qty':'17'}]})
    assert added.status_code == 200, added.text
    now = planner.get(P+path).json()
    assert now['undo']=={'label':'添加物料','count':1}
    assert now['items'][-1]['id'] != row['id']
    first = post(planner,path+'/undo',{'revision':now['revision']}).json()
    assert post(planner,path+'/undo',{'revision':first['revision']}).status_code == 200
    restored = planner.get(P+path).json()
    assert restored['items']==before['items']
    redo_delete=post(planner,path+'/redo',{'revision':restored['revision']})
    assert redo_delete.status_code==200
    redo_add=post(planner,path+'/redo',{'revision':redo_delete.json()['revision']})
    assert redo_add.status_code==200
    assert planner.get(P+path).json()['items']==now['items']
    assert redo_add.json()['affected_ids']==[now['items'][-1]['id']]
    undo_add=post(planner,path+'/undo',{'revision':redo_add.json()['revision']})
    assert post(planner,path+'/undo',{'revision':undo_add.json()['revision']}).status_code==200
    restored=planner.get(P+path).json()

    with SessionLocal() as db:
        original = db.get(Snapshot,before['snapshot']['id'])
        replacement = Snapshot(id=uid(),warehouse=original.warehouse,name='新库存',
                               as_of='2026-10-02',basis=original.basis,net_mode=original.net_mode,
                               creator=original.creator,digest='test-basis',items=[
                                   {**r,'net_supply_before_plan':'520'} for r in original.items])
        db.add(replacement)
        db.commit()
        new_id = replacement.id
    switched = post(planner,path+'/basis',{'revision':restored['revision'],'snapshot_id':new_id})
    assert switched.status_code == 200,switched.text
    now = planner.get(P+path).json()
    assert now['snapshot']['id']==new_id and now['undo']['label']=='更换计算依据'
    assert post(planner,path+'/undo',{'revision':now['revision']}).status_code == 200
    restored = planner.get(P+path).json()
    assert restored['snapshot']==before['snapshot'] and restored['items']==before['items']
    assert restored['redo']=={'label':'更换计算依据','count':len(now['items'])}
    assert post(planner,path+'/redo',{'revision':restored['revision']}).status_code==200
    repeated=planner.get(P+path).json()
    assert repeated['items']==now['items'] and repeated['snapshot']==now['snapshot'] and repeated['rule']==now['rule']


def test_noop_preserves_redo_but_new_edit_discards_only_the_abandoned_branch(clients):
    planner=clients[0]
    _,start=current(planner)
    path='/versions/'+start['id']
    rid=start['items'][0]['id']
    def edit(rev,value):
        return planner.patch(P+path+'/items',json={'revision':rev,'changes':[{'id':rid,'values':{'sea_plan_qty':value}}]})
    first=edit(start['revision'],'63')
    assert first.status_code==200
    second=edit(first.json()['revision'],'64')
    rolled=post(planner,path+'/undo',{'revision':second.json()['revision']}).json()
    assert edit(rolled['revision'],'63').status_code==200
    kept=planner.get(P+path).json()
    assert kept['redo']=={'label':'修改计划明细','count':1} and kept['undo']
    new_branch=edit(kept['revision'],'65')
    assert new_branch.status_code==200
    branched=planner.get(P+path).json()
    assert branched['redo'] is None and branched['undo']==kept['undo']
    assert post(planner,path+'/redo',{'revision':branched['revision']}).status_code==409
    back=post(planner,path+'/undo',{'revision':branched['revision']}).json()
    assert post(planner,path+'/undo',{'revision':back['revision']}).status_code==200
    assert planner.get(P+path).json()['items']==start['items']


def test_racing_redos_commit_once_and_replays_do_not_cross_submission(clients):
    planner=clients[0]
    batch,start=ready(planner)
    path='/versions/'+start['id']
    row=start['items'][0]
    edit=planner.patch(P+path+'/items',json={'revision':start['revision'],'changes':[{'id':row['id'],'values':{'sea_plan_qty':'79'}}]})
    rolled=post(planner,path+'/undo',{'revision':edit.json()['revision']})
    rev=rolled.json()['revision']
    gate=Barrier(2)
    def click(key):
        gate.wait(timeout=5)
        return post(planner,path+'/redo',{'revision':rev},key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(click,['first-tab','second-tab']))
    assert sorted(r.status_code for r in results)==[200,409]
    key=['first-tab','second-tab'][next(i for i,r in enumerate(results) if r.status_code==200)]
    win=next(r.json() for r in results if r.status_code==200)
    assert post(planner,path+'/redo',{'revision':rev},key).json()==win
    with SessionLocal() as db:
        assert len(db.scalars(select(Audit.id).where(Audit.batch_id==batch['id'],Audit.action=='重做明细操作')).all())==1
    submitted=post(planner,path+'/submit',{'revision':win['revision']})
    assert submitted.status_code==200,submitted.text
    assert planner.get(P+path).json()['redo'] is None
    frozen=planner.get(P+path).json()
    # Retrying the original acknowledged request returns its receipt, but never edits a later stage.
    assert post(planner,path+'/redo',{'revision':rev},key).json()==win
    assert post(planner,path+'/redo',{'revision':frozen['revision']}).status_code in (403,409)
    assert planner.get(P+path).json()==frozen


def test_same_key_concurrent_retry_yields_one_audit_event(clients):
    planner=clients[0]
    batch,version=ready(planner)
    path='/versions/'+version['id']
    undone=post(planner,path+'/undo',{'revision':version['revision']}).json()
    gate=Barrier(2)
    def click(_):
        gate.wait(timeout=5)
        return post(planner,path+'/redo',{'revision':undone['revision']},'same-request')
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=pool.map(click,range(2))
    assert (a.status_code,b.status_code)==(200,200)
    assert a.json()==b.json()
    current=planner.get(P+path).json()
    assert current['items']==version['items'] and current['revision']==a.json()['revision']
    with SessionLocal() as db:
        assert len(db.scalars(select(Audit.id).where(Audit.batch_id==batch['id'],Audit.action=='重做明细操作')).all())==1


def test_twenty_step_history_remains_bounded_across_undo_and_redo(clients):
    planner=clients[0]
    _,version=current(planner)
    path='/versions/'+version['id']
    rid=version['items'][0]['id']
    rev=version['revision']
    for n in range(23):
        saved=planner.patch(P+path+'/items',json={'revision':rev,'changes':[{'id':rid,'values':{'sea_plan_qty':str(300+n)}}]})
        assert saved.status_code==200,saved.text
        rev=saved.json()['revision']
    for method,last_qty in [('undo','302'),('redo','322')]:
        for _ in range(20):
            moved=post(planner,path+'/'+method,{'revision':rev})
            assert moved.status_code==200,moved.text
            rev=moved.json()['revision']
        assert post(planner,path+'/'+method,{'revision':rev}).status_code==409
        state=planner.get(P+path).json()
        assert next(row['input']['sea_plan_qty'] for row in state['items'] if row['id']==rid)==last_qty
        with SessionLocal() as db:
            counts=[len(db.scalars(select(t.revision).where(t.version_id==version['id'])).all()) for t in (PlanUndo,PlanRedo)]
            assert sum(counts)==20


def test_redo_full_workbook_then_single_quantity_update_recovers_both_sources(clients):
    from openpyxl import Workbook,load_workbook
    from backend.template_assets import WORKBOOK_TEMPLATES
    planner=clients[0]
    _,original=current(planner)
    path='/versions/'+original['id']
    template=load_workbook(WORKBOOK_TEMPLATES['v3'][0],read_only=True)
    headers=next(template['审核表'].values)
    template.close()
    full=Workbook()
    sheet=full.active
    sheet.title='审核表'
    sheet.append(headers)
    for col,value in {'A':'NEW-PART','B':'普通件','T':0,'U':0,'W':6,'X':8,'Y':3}.items():
        sheet[col+'2']=value
    binary=BytesIO()
    full.save(binary)
    full.close()
    def commit(content,name,mode):
        job=upload(planner,'plan',content,name)
        assert job['state']=='DONE' and not job['issues'],job
        prev=planner.get(P+path).json()
        response=post(planner,'/imports/'+job['id']+'/commit',{'version_id':original['id'],'mode':mode,'revision':prev['revision']})
        assert response.status_code==200,response.text
        return job['id'],planner.get(P+path).json()
    first,full_version=commit(binary.getvalue(),'整表.xlsx','replace')
    assert original['snapshot'] and full_version['snapshot'] is None
    second,updated=commit(csvfile(['物料号,海运计划,空运计划','NEW-PART,9,']),'仅数量.csv','update_quantities')
    source=updated['items'][0]['input']
    assert (source['sea_plan_qty'],source['air_plan_qty'])==('9','3')
    assert source['source']['job_id']==first and source['plan_source']['job_id']==second
    rev=updated['revision']
    for method,expected in [('undo',full_version),('undo',original),('redo',full_version),('redo',updated)]:
        response=post(planner,path+'/'+method,{'revision':rev})
        assert response.status_code==200,response.text
        restored=planner.get(P+path).json()
        assert restored['items']==expected['items'] and restored['snapshot']==expected['snapshot']
        rev=restored['revision']
