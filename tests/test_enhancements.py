import json
from copy import deepcopy
from io import BytesIO
from decimal import Decimal
import pytest
from openpyxl import load_workbook
from fastapi import HTTPException
from test_api import clients,post,current,P,claim
from test_data import upload,csvfile
from test_rules import row
from backend.rules import calculate,default_package
from backend.table_query import decision_label,display_row,query_items
from backend.periods import period_info
from backend.db import SessionLocal,Version,Job,User
from backend.jobs import run_job,export_workbook


def test_iso_weeks_and_months():
    assert period_info('历史周期',strict=False)['label']=='历史周期'
    assert period_info('2026-W37')['start']=='2026-09-07'
    assert period_info('2026-W37')['end']=='2026-09-13'
    assert period_info('2020-W53')['end']=='2021-01-03'
    assert period_info('2024-02')['end']=='2024-02-29'
    assert period_info('2026-W53')['end']=='2027-01-03'
    for invalid in ('2025-W53','2026-W00','2026-13','2026-09-01','hello'):
        with pytest.raises(HTTPException):period_info(invalid)


def test_review_decision_filter_and_selection_use_the_displayed_version(clients):
    planner, reviewer, _, _ = clients
    _, draft = current(planner)
    path='/versions/'+draft['id']
    row_ids={row['id'] for row in draft['items']}
    def check(client, route, label, expected):
        filters={'decision':{'values':[label]}}
        query={'column_filters':json.dumps(filters)}
        result=client.get(P+route,params=query).json()
        assert result['total']==len(expected)
        assert {row['id'] for row in result['items']}==expected
        assert set(client.get(P+route+'/selection',params=query).json()['ids'])==expected
        if expected:
            assert label in result['column_options']['decision']
            assert {row['table_values']['decision'] for row in result['items']}=={label}
            detail=client.get(P+route+'/items/'+next(iter(expected))).json()
            assert detail['table_values']['decision']==label
        return filters
    draft_filter=check(planner,path,'未提交',row_ids)
    check(planner,path,'待复审',set())
    job=post(planner,'/exports',{'version_id':draft['id'],'scope':'filtered','column_filters':draft_filter}).json()
    with SessionLocal() as db:
        payload=db.get(Job,job['id']).payload
        assert {row['id'] for row in payload['items']}==row_ids
        assert payload['metadata']['排序']=='计划原顺序'
        workbook=load_workbook(BytesIO(export_workbook(payload)),data_only=True)
        assert {row[16] for row in list(workbook["计划审核结果"].values)[1:]}=={'未提交'}
        workbook.close()
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    result=claim(reviewer,path)
    check(reviewer,path,'待复审',row_ids)
    first=draft['items'][0]['id']
    reviewed=post(reviewer,path+'/reviews',{'revision':result['revision'],'ids':[first],'decision':'APPROVED'}).json()
    check(reviewer,path,'已批准',{first})
    second=next(i for i in row_ids if i!=first)
    returned=post(reviewer,path+'/return',{'revision':reviewed['revision'],'reason':'调整数量','ids':[second]}).json()
    check(reviewer,path,'未复审',row_ids-{first})
    check(reviewer,path,'退回修改',set())
    check(reviewer,path,'已批准',{first})
    next_path='/versions/'+returned['version_id']
    check(planner,next_path,'未提交',row_ids-{first,second})
    needs_edit=check(planner,next_path,'需修改',{second})
    job=post(planner,'/exports',{'version_id':returned['version_id'],'scope':'filtered','column_filters':needs_edit}).json()
    with SessionLocal() as db:
        exported=db.get(Job,job['id']).payload
        assert [r['id'] for r in exported['items']]==[second]
        workbook=load_workbook(BytesIO(export_workbook(exported)),data_only=True)
        assert list(workbook["计划审核结果"].values)[1][16]=='需修改'
        workbook.close()
    assert decision_label(None,'VOID')=='未复审'
    assert decision_label({'status':'BATCH_APPROVED'},'APPROVED')=='整批通过'
    assert decision_label({'status':'EXCEPTION_APPROVED'},'RETURNED')=='例外批准'


def test_week_creation_contract(clients):
    p,_,_,_=clients;b,v=current(p)
    data={'title':'每周计划','warehouse':'UK_MAIN','snapshot_id':v['snapshot']['id'],'period':'2026-W37'}
    result=post(p,'/batches',data)
    assert result.status_code==200,result.text
    assert result.json()['period_info']['kind']=='week'
    assert post(p,'/batches',{**data,'period':'2025-W53'}).status_code==422


def test_whole_batch_filter_sort_paging_selection_export(clients):
    p,_,_,other=clients;b,v=current(p)
    items=[]
    for n in range(123):
        inp=row(material_code=f'T-{n:03}',sea_plan_qty=str(n),is_key_model=n%2==0)
        items.append({'id':str(n),'input':inp,'result':calculate(inp),'decision':None})
    with SessionLocal.begin() as db:db.get(Version,v['id']).items=items
    for capacity in (15,50,100,300,500,1000,10000):
        listing=p.get(P+'/versions/'+v['id'],params={'page_size':capacity,'table_view':'true'}).json()
        assert listing['page_size']==capacity and len(listing['items'])==min(capacity,len(items))
        assert listing['items'][0]['table_values']['material_code']==items[0]['input']['material_code']
    conditions={'sea_plan_qty':{'min':'8','max':'122'},'is_key_model':{'values':['是']}}
    query={'column_filters':json.dumps(conditions),'sort_key':'sea_plan_qty','sort_direction':'desc','page_size':20}
    results=[p.get(P+'/versions/'+v['id'],params={**query,'page':n}).json() for n in (1,2,3)]
    expected=[str(n) for n in range(122,7,-2)]
    assert [r['id'] for page in results for r in page['items']]==expected
    assert results[0]['total']==58
    assert all(Decimal(r['table_values']['pipeline_days']) == 150 and Decimal(r['table_values']['future_days']) == (50 + int(r['id'])) * 3 for r in results[0]['items'])
    assert all(r['table_values']['m']=='10' for r in results[0]['items'])
    selected=p.get(P+'/versions/'+v['id']+'/selection',params=query).json()
    assert selected['ids']==expected
    result=post(p,'/exports',{'version_id':v['id'],'scope':'filtered','column_filters':conditions,'sort_key':'sea_plan_qty','sort_direction':'desc'})
    run_job(result.json()['id'])
    with SessionLocal() as db:
        job=db.get(Job,result.json()['id']);assert job.state=='DONE',job.error
        assert [r['id'] for r in job.payload['items']]==expected
    for bad in ({'sort_key':'__bad'},{'column_filters':'invalid'},{'column_filters':json.dumps({'sea_plan_qty':{'min':10,'max':1}})}):
        assert p.get(P+'/versions/'+v['id'],params=bad).status_code==422
    assert other.get(P+'/versions/'+v['id']+'/selection',params=query).status_code==403


def test_sort_nulls_and_filter_missing_not_zero():
    rows=[]
    for n,val in enumerate(('2',None,'0','10','?')):
        inp=row(fleet_qty=val);rows.append({'id':n,'input':inp,'result':calculate(inp)})
    assert [r['id'] for r in query_items(rows,sort_key='fleet_qty')]==[2,0,3,1,4]
    assert [r['id'] for r in query_items(rows,sort_key='fleet_qty',sort_direction='desc')]==[3,0,2,1,4]
    assert [r['id'] for r in query_items(rows,column_filters={'fleet_qty':{'blank':'only'}})]==[1,4]
    assert [r['id'] for r in query_items(rows,column_filters={'fleet_qty':{'min':0,'max':0}})]==[2]

def test_english_text_filter_uses_displayed_advice_and_manual_checks():
    source = row(material_code='CH-1', air_plan_qty='1')
    result = calculate(source)
    result['advice'] = '备货多，建议减少1,200.5pcs；建议延迟补货'
    items = [{'id':'item', 'input':source, 'result':result}]

    def found(key, term, lang='en', op='contains'):
        rule = {'term':term, 'op':op}
        if lang:
            rule['lang'] = lang
        return bool(query_items(items, column_filters={key:rule}))

    assert found('attention', 'AIR FREIGHT')
    assert found('advice', 'Excess stock. Reduce by 1,200.5 pcs; Delay replenishment', op='eq')
    assert found('advice', 'delay', op='not_contains') is False
    assert found('advice', '建议延迟', lang=None)
    with pytest.raises(HTTPException):
        found('material_name', 'anything')
    with pytest.raises(HTTPException):
        found('advice', 'test', lang='unsupported')


def test_excel_filter_conditions_and_dependent_choices():
    items=[]
    for idx,(code,qty,status) in enumerate([('Ab-01','2','APPROVED'),('AB-02','0','REJECTED'),('CB-02',None,'BATCH_APPROVED')]):
        inp=row(material_code=code,fleet_qty=qty)
        items.append({'id':idx,'input':inp,'result':calculate(inp),'decision':{'status':status}})
    def ids(key,rule):
        return [r['id'] for r in query_items(items,column_filters={key:rule})]
    for op,term,expected in [('contains','b-',[0,1,2]),('not_contains','ab',[2]),('eq','ab-02',[1]),('ne','ab-02',[0,2]),('starts','aB',[0,1]),('ends','02',[1,2])]:
        assert ids('material_code',{'op':op,'term':term})==expected
    for op,expected in [('eq',[1]),('ne',[0]),('gt',[0]),('ge',[0,1]),('lt',[]),('le',[1])]:
        assert ids('fleet_qty',{'op':op,'term':0})==expected
    assert ids('fleet_qty',{'blank':'only'})==[2]
    assert ids('fleet_qty',{'blank':'exclude'})==[0,1]
    assert ids('decision',{'values':['不批准','整批通过']})==[1,2]
    items[1]['result'].update(delay_replenishment=True,turnover_warning='周转过高')
    assert ids('status',{'values':['建议延迟补货','周转过高']})==[1]
    facets={'decision':set(),'status':set()}
    rows=query_items(items,column_filters={'material_code':{'op':'starts','term':'ab'},'decision':{'values':['不批准']}},facets=facets)
    assert [r['id'] for r in rows]==[1]
    assert facets['decision']=={'已批准','不批准'}
    assert '建议延迟补货' in facets['status']


def test_warnings_allow_submission_and_finalization_without_individual_confirmations(clients):
    p,r,a,s=clients;b,v=current(p)
    job=upload(p,'plan',csvfile(['物料号,海运计划,空运计划','DEMO-0001,?,1','DEMO-0002,9999,0']))
    committed=post(p,'/imports/'+job['id']+'/commit',{'version_id':v['id'],'revision':v['revision']})
    assert committed.status_code==200
    vid=v['id'];v=p.get(P+'/versions/'+vid).json()
    report=p.get(P+'/versions/'+vid+'/confirmation').json()
    assert report['total']==2 and report['error_rows']==1 and report['affected_count']==2
    body={'revision':report['revision']}
    assert post(p,'/versions/'+vid+'/submit',{**body,'issue_hash':'stale'}).status_code==409
    assert s.get(P+'/versions/'+vid+'/confirmation').status_code==403
    accepted=post(p,'/versions/'+vid+'/submit',body,'force-idempotent')
    assert accepted.status_code==200,accepted.text
    assert post(p,'/versions/'+vid+'/submit',body,'force-idempotent').json()==accepted.json()
    frozen=claim(r,'/versions/'+vid)
    bad=next(x for x in frozen['items'] if x['result']['data_status']=='ERROR')
    assert bad['input']['sea_plan_qty']=='?' and bad['result']['future_qty'] is None
    assert bad['submission_override']['mode']=='advisory' and bad['submission_override']['user_id']
    assert all(x['decision'] is None for x in frozen['items'])
    report=r.get(P+'/versions/'+vid+'/confirmation?stage=finalize').json()
    body={'revision':report['revision']}
    assert post(a,'/versions/'+vid+'/finalize',body).status_code==403
    # Even a dual-role owner cannot use the override to self-approve.
    with SessionLocal.begin() as db:db.get(User,b['owner']).roles=['PLANNER','REVIEWER']
    assert post(p,'/versions/'+vid+'/finalize',body).status_code==403
    final=post(r,'/versions/'+vid+'/finalize',body);assert final.status_code==200,final.text
    final=r.get(P+'/versions/'+vid).json()
    assert final['state']=='APPROVED' and final['summary']['ERROR']==1
    assert report['unreviewed_exception']==2 and report['exception_approved']==2
    for item in final['items']:
        assert item['decision']['status']=='EXCEPTION_APPROVED' and item['decision']['batch'] and not item['decision']['ack_flags']
        assert item['decision']['reviewer_id'] and item['decision']['air_confirmed'] is False
    bad=next(x for x in final['items'] if x['result']['data_status']=='ERROR')
    assert not bad['decision'].get('data_error_accepted') and bad['input']['sea_plan_qty']=='?'
    copied=post(p,'/batches/'+b['id']+'/copy',{}).json()
    assert all(not x.get('submission_override') and not x['decision'] for x in p.get(P+'/versions/'+copied['current_id']).json()['items'])
    events=p.get(P+'/batches/'+b['id']).json()['events']
    assert {'提交复审','完成终审'}<={e['action'] for e in events}
    event=next(e for e in events if e['action']=='完成终审')
    assert event['detail']['warning_rows']==2 and event['detail']['batch_approved']==2


def test_return_clears_acknowledgement_and_new_revision_rejects_stale(clients):
    p,r,_,_=clients;b,v=current(p);vid=v['id']
    old=p.get(P+'/versions/'+vid+'/confirmation').json()
    changed=p.patch(P+'/versions/'+vid+'/items',json={'revision':v['revision'],'changes':[{'id':v['items'][0]['id'],'values':{'sea_plan_qty':'7'}}]})
    assert changed.status_code==200
    body={'force':True,'accept_issues':True,'reason':'本地确认测试','revision':old['revision'],'issue_hash':old['issue_hash']}
    assert post(p,'/versions/'+vid+'/submit',body).status_code==409
    report=p.get(P+'/versions/'+vid+'/confirmation').json();body.update(revision=report['revision'],issue_hash=report['issue_hash'])
    submitted=post(p,'/versions/'+vid+'/submit',body);assert submitted.status_code==200
    claimed=claim(r,'/versions/'+vid)
    returned=post(r,'/versions/'+vid+'/return',{'revision':claimed['revision'],'ids':[v['items'][0]['id']],'reason':'重新核对'})
    assert returned.status_code==200
    new=p.get(P+'/versions/'+returned.json()['version_id']).json()
    assert all(not x.get('submission_override') for x in new['items'])
    assert any(x.get('submission_override') for x in p.get(P+'/versions/'+vid).json()['items'])


def test_export_formulas_and_initial_values():
    inputs=[row(),row(sea_plan_qty='?'),row(material_name='工具',fleet_qty=None),row(avg_sales_3m=0,avg_sales_6m=0)]
    rows=[{'input':i,'result':calculate(i)} for i in inputs]
    data=export_workbook({'items':rows,'rule_package':default_package(),'metadata':{}})
    formulas=load_workbook(BytesIO(data),data_only=False);values=load_workbook(BytesIO(data),data_only=True)
    assert formulas.calculation.fullCalcOnLoad
    assert formulas['计划审核结果']['K2'].value.startswith('=IF(')
    assert '\\' not in formulas['计划审核结果']['K2'].value
    for idx,item in enumerate(rows,2):
        for col,key in [('F','future_qty'),('G','lower'),('H','upper'),('AG','m'),('M','suggested_sea_qty'),('N','residual_excess')]:
            assert formulas['计划审核结果'][f'{col}{idx}'].data_type=='f'
            value=values['计划审核结果'][f'{col}{idx}'].value;expected=item['result'][key]
            assert (value is None and expected is None) or Decimal(str(value))==Decimal(expected)
        assert all(formulas['计划审核结果'][f'{col}{idx}'].data_type=='f' for col in ('AH','AI','BB','BC','BD'))
        if item['result']['m']=='0':
            assert values['计划审核结果'][f'AI{idx}'].value=='无销量'
        else:
            assert values['计划审核结果'][f'AI{idx}'].value == (float(item['result']['future_days']) if item['result']['future_days'] is not None else None)
    assert values['计划审核结果']['C3'].value=='?'
    formulas.close();values.close()


def test_exception_finalization_preserves_valid_decisions_and_covers_hidden_rows(clients):
    p,r,_,_=clients;b,v=current(p);vid=v['id']
    items=[]
    for n in range(125):
        inp=row(material_code=f'FORCE-{n}',sea_plan_qty=30 if n==0 else 9999)
        items.append({'id':str(n),'input':inp,'result':calculate(inp),'decision':None})
    with SessionLocal.begin() as db:db.get(Version,vid).items=items
    v=p.get(P+'/versions/'+vid).json()
    submitted=post(p,'/versions/'+vid+'/submit',{'revision':v['revision']});assert submitted.status_code==200
    claimed=claim(r,'/versions/'+vid)
    reviewed=post(r,'/versions/'+vid+'/reviews',{'revision':claimed['revision'],'ids':['0'],'decision':'APPROVED'})
    assert reviewed.status_code==200 and reviewed.json()['count']==1
    report=r.get(P+'/versions/'+vid+'/confirmation?stage=finalize').json()
    assert report['total']==125 and report['affected_count']==124 and report['truncated'] and len(report['rows'])==100
    complete=r.get(P+'/versions/'+vid+'/confirmation?stage=finalize&all=true').json()
    assert complete['issue_hash']==report['issue_hash'] and not complete['truncated']
    assert len(complete['rows'])==124 and complete['rows'][-1]['id']=='124'
    body={'revision':report['revision'],'force':True,'accept_issues':True,'reason':'全批次统一核对测试','issue_hash':report['issue_hash']}
    assert post(r,'/versions/'+vid+'/finalize',{**body,'issue_hash':'stale'}).status_code==409
    assert post(r,'/versions/'+vid+'/finalize',body).status_code==200
    with SessionLocal() as db:
        rows=db.get(Version,vid).items
        assert rows[0]['decision']['status']=='APPROVED' and not rows[0]['decision'].get('forced')
        assert all(x['decision']['status']=='EXCEPTION_APPROVED' and x['decision']['batch'] and x['decision']['reason']==body['reason'] for x in rows[1:])
