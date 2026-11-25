from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from backend.db import Job, SessionLocal, Snapshot
from backend.rules import upgrade_to_v3
from backend.services import active_rule
from test_api import P, clients, post, claim
from test_data import csvfile, upload


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def setup_plan(planner):
    with SessionLocal.begin() as db:
        rule = active_rule(db, 'UK_MAIN')
        rule.package = upgrade_to_v3(rule.package)
    batch = ok(post(planner, '/batches', {'warehouse':'UK_MAIN','period':'2026-11','title':'计划基础数据'}))
    return '/versions/'+batch['current_id']


@pytest.mark.parametrize('full', [True, False], ids=['v3', 'compact'])
def test_plan_upload_requires_one_explicit_transport_quantity(clients, full):
    planner, _, steward, _ = clients
    path = setup_plan(planner)
    draft = ok(planner.get(P+path))
    records = [('SEA', 4, None), ('AIR', None, 3), ('ZERO', 0, None), ('NONE', ' ', None)]

    def contents(records):
        if not full:
            return csvfile(['物料号,海运计划,空运计划'] + [
                ','.join('' if value is None else str(value) for value in row) for row in records]), '数量.csv'
        book = load_workbook(BytesIO(planner.get(P+'/template?kind=v3').content))
        for row, (code, sea, air) in enumerate(records, 2):
            for column, value in [('A', code), ('X', sea), ('Y', air)]:
                book['审核表'][column+str(row)] = value
        stream = BytesIO()
        book.save(stream)
        book.close()
        return stream.getvalue(), '计划.xlsx'

    invalid, name = contents(records)
    job = upload(planner, 'plan', invalid, name)
    issue, = job['issues']
    assert (issue['row'], issue['material_code'], issue['field']) == (5, 'NONE', 'plan_quantities')
    assert '至少填写一项' in planner.get(P+'/imports/'+job['id']+'/errors').text
    if not full:
        with SessionLocal.begin() as db:
            saved = db.get(Job, job['id'])
            saved.result = {**saved.result, 'plan_quantities_checked': False, 'issues': []}
    body = {'revision':draft['revision'], 'version_id':draft['id']}
    rejected = post(planner, '/imports/'+job['id']+'/commit', body)
    assert rejected.status_code == 422 and 'NONE' in rejected.text
    assert ok(planner.get(P+path))['revision'] == draft['revision']
    if full:
        assert not upload(steward, 'v3', invalid, name)['issues']
    corrected, name = contents(records[:3]+[('NONE', 0, 0)])
    job = upload(planner, 'plan', corrected, name)
    assert not job['issues']
    ok(post(planner, '/imports/'+job['id']+'/commit', body))
    rows = [row['input'] for row in ok(planner.get(P+path))['items']]
    assert {r['material_code']:(r['sea_plan_qty'],r['air_plan_qty']) for r in rows} == {
        'SEA':('4','0'), 'AIR':('0','3'), 'ZERO':('0','0'), 'NONE':('0','0')}


def test_planner_import_recalculate_and_review_without_shared_snapshot(clients):
    planner, reviewer, _, _ = clients
    path = setup_plan(planner)
    def draft(): return ok(planner.get(P+path))
    def commit(job):
        state=draft()
        ok(post(planner,'/imports/'+job['id']+'/commit',{'revision':state['revision'],'version_id':state['id']}))
    def snapshots():
        with SessionLocal() as db:
            return set(db.scalars(select(Snapshot.id)))
    original=snapshots()
    book=load_workbook(BytesIO(planner.get(P+'/template?kind=v3').content))
    sheet=book['审核表']
    for col,val in {'A':'P-1','B':'支架','F':'A','G':'Y','H':18000,'V':4,'W':0,'X':2,'Y':7,'Z':0.03,
                    'AA':5,'AB':6,'L':123,'M':456,'AC':999,'AM':'旧建议','AN':'同意','AO':88,'AP':'同意','AQ':'旧签批'}.items():
        sheet[f'{col}2']=val
    for col,val in zip('NOPQRS',[0,1,2,3,4,5]): sheet[f'{col}2']=val
    file=BytesIO();book.save(file);book.close()
    job=upload(planner,'plan',file.getvalue(),'本月计划.xlsx')
    assert job['plan_format']=='v3' and job['rows']==1
    commit(job)
    state=draft(); row,=state['items']; inp=row['input']
    assert state['snapshot'] is None and state['summary']['plan_reference']==1 and state['summary']['PENDING']==0
    assert row['result']['future_qty']=='6' and (inp['avg_sales_3m'],inp['avg_sales_6m'])==('4','2.5')
    assert not row['decision'] and '旧签批' not in str(row) and inp['source']['file']=='本月计划.xlsx'
    def patch(client,revision,reference):
        return client.patch(P+path+'/items',json={'revision':revision,'changes':[{'id':row['id'],'reference':reference}]})
    assert patch(reviewer,state['revision'],{'on_hand_qty':'8'}).status_code==403
    assert patch(planner,state['revision'],{'future_qty':'99'}).status_code==422
    assert patch(planner,state['revision'],{'decision':'APPROVED'}).status_code==422
    ok(patch(planner,state['revision'],{'on_hand_qty':'8','monthly_sales':[0,0,0,0,3,6]}))
    assert patch(planner,state['revision'],{'on_hand_qty':'4'}).status_code==409
    state=draft(); row,=state['items']
    assert row['input']['avg_sales_3m']=='3' and row['result']['future_qty']=='10'
    commit(upload(planner,'plan',csvfile(['物料号,海运计划,空运计划','P-1,3,7'])))
    state=draft(); row,=state['items']
    assert row['input']['on_hand_qty']=='8' and row['input']['avg_sales_6m']=='1.5'
    assert row['input']['source']['file']=='本月计划.xlsx' and row['input']['plan_source']['file']=='data.csv'
    assert row['result']['future_qty']=='11' and state['snapshot'] is None
    warnings=ok(planner.get(P+path+'/confirmation'))
    ok(post(planner,path+'/submit',{'revision':state['revision'],'issue_hash':warnings['issue_hash']}))
    assigned=claim(reviewer,path)
    decision=ok(post(reviewer,path+'/reviews',{'revision':assigned['revision'],'ids':[row['id']],
                     'decision':'RETURNED','reason':'核对库存后调整海运'}))
    returned=ok(post(reviewer,path+'/return',{'revision':decision['revision']}))
    next_path='/versions/'+returned['version_id']
    next_state=ok(planner.get(P+next_path))
    assert next_state['items'][0]['return_reason']=='核对库存后调整海运'
    ok(planner.patch(P+next_path+'/items',json={'revision':next_state['revision'],
                    'changes':[{'id':row['id'],'values':{'sea_plan_qty':'1'},'reference':{'on_hand_qty':'6'}}]}))
    revised=ok(planner.get(P+next_path))
    assert revised['items'][0]['result']['future_qty']=='7' and draft()['items'][0]['result']['future_qty']=='11'
    submit=ok(planner.get(P+next_path+'/confirmation'))
    ok(post(planner,next_path+'/submit',{'revision':revised['revision'],'issue_hash':submit['issue_hash']}))
    assigned=claim(reviewer,next_path)
    ok(post(reviewer,next_path+'/reviews',{'revision':assigned['revision'],'ids':[row['id']],'decision':'APPROVED',
            'ack_flags':assigned['items'][0]['result']['manual_flags'],'air_confirmed':True,'reason':'已核对库存'}))
    assert ok(planner.get(P+next_path))['items'][0]['decision']['status']=='APPROVED'
    assert snapshots()==original


def test_hand_entry_and_partial_rows_can_coexist(clients):
    planner, _, _, _=clients
    path=setup_plan(planner)
    state=ok(planner.get(P+path))
    ok(post(planner,path+'/items',{'revision':state['revision'],'items':[
        {'material_code':'HAND','sea_plan_qty':'3','reference':{'material_name':'前门支架','material_abc':'A',
            'is_key_model':True,'fleet_qty':'18000','on_hand_qty':'4','net_supply_before_plan':'0',
            'monthly_sales':[0,1,2,3,4,5],'replacement_rate':'2%','replacement_target':5,'sales_target':6}},
        {'material_code':'QTY','sea_plan_qty':'3'}]}))
    state=ok(planner.get(P+path)); by_code={row['input']['material_code']:row for row in state['items']}
    assert by_code['HAND']['result']['future_qty']=='7' and by_code['HAND']['input']['replacement_rate']=='0.02'
    assert by_code['QTY']['result']['basis_pending'] and state['summary']['PENDING']==1
    assert state['summary']['plan_reference']==1 and state['snapshot'] is None
    job=upload(planner,'plan',csvfile(['物料号,海运计划,空运计划','HAND,6,0','NEW,1,0']))
    ok(post(planner,'/imports/'+job['id']+'/commit',{'version_id':state['id'],'revision':state['revision'],'mode':'update_quantities'}))
    updated=ok(planner.get(P+path))
    by_code={row['input']['material_code']:row for row in updated['items']}
    assert set(by_code)=={'HAND','QTY','NEW'} and updated['summary']['PENDING']==2
    assert by_code['HAND']['result']['future_qty']=='10' and by_code['QTY']['input']['sea_plan_qty']=='3'


def test_quantity_update_preserves_blanks_and_clears_explicit_zeros(clients):
    planner = clients[0]
    path = setup_plan(planner)
    draft = ok(planner.get(P+path))
    ok(post(planner, path+'/items', {'revision':draft['revision'], 'items':[
        {'material_code':code, 'sea_plan_qty':'7', 'air_plan_qty':'4'} for code in ('SEA','AIR','KEEP')]}))

    def apply(rows, mode):
        job = upload(planner, 'plan', csvfile(['物料号,海运计划,空运计划', *rows]))
        assert not job['issues']
        state = ok(planner.get(P+path))
        ok(post(planner, '/imports/'+job['id']+'/commit', {'version_id':state['id'],
                'revision':state['revision'], 'mode':mode}))
        return {r['input']['material_code']:(r['input']['sea_plan_qty'],r['input']['air_plan_qty'])
                for r in ok(planner.get(P+path))['items']}

    assert apply(['SEA,12, ', 'AIR,,6', 'NEW,,3'], 'update_quantities') == {
        'SEA':('12','4'), 'AIR':('7','6'), 'KEEP':('7','4'), 'NEW':('0','3')}
    assert apply(['SEA,,0', 'AIR,0,'], 'update_quantities') == {
        'SEA':('12','0'), 'AIR':('0','6'), 'KEEP':('7','4'), 'NEW':('0','3')}
    assert apply(['KEEP,2,'], 'replace') == {'KEEP':('2','0')}
