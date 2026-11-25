from io import BytesIO
from copy import deepcopy
import pytest
from openpyxl import Workbook,load_workbook
from test_api import clients,post,current,P,ready
from backend.adapters import parse_file,normalize
from backend.db import SessionLocal,Job,Snapshot
from backend.jobs import run_job,claim_job,export_workbook

PLAN_REASON_LABELS = {
    '预计用量有变化': '市场需求变化',
    '已有订单要交付': '已确认特殊订单',
    '配合船期或到货时间': '补货节奏',
    '备件有特殊备货要求': '特殊物料',
    '库存或销量需要说明': '数据口径说明',
    '其他原因': '其他',
}

def upload(c,kind,content,name='data.csv',mode='NET_PROVIDED'):
    r=c.post(P+'/imports',files={'file':(name,content)},data={'warehouse':'UK_MAIN','kind':kind,'net_mode':mode})
    assert r.status_code==200,r.text
    jid=r.json()['id'];run_job(jid)
    return c.get(P+'/jobs/'+jid).json()

def csvfile(rows):return ('\ufeff'+'\n'.join(rows)).encode('utf-8')

def test_downloaded_plan_template_guides_and_imports_a_single_real_row(clients):
    planner = clients[0]
    response = planner.get(P+'/template', params={'kind': 'plan'})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert '.xlsx' in response.headers['content-disposition']
    workbook = load_workbook(BytesIO(response.content))
    entry = workbook['计划明细']
    assert workbook.active == entry
    assert workbook['填写示例'].sheet_state == 'visible'
    headers = ['物料号', '物料名称', '海运计划', '空运计划', '原因类别', '计划说明', '空运说明']
    for cell, label in zip(entry[1], headers, strict=True):
        title, guidance = cell.value.split('\n', 1)
        assert title == label and guidance.strip()
        assert cell.alignment.wrap_text
        assert cell.comment and cell.comment.text.strip()
    for cell in (entry['C1'], entry['D1']):
        assert all(hint in cell.comment.text for hint in ('留空保留原量', '填 0 清零', '新增物料', '至少填一项'))
    assert '下拉列表' in entry['E1'].comment.text
    code_hint = entry['A1'].value
    assert '主数据' in code_hint and '0' not in code_hint and '零' not in code_hint
    assert entry['B1'].value == '物料名称\n选填 · 备件描述'
    assert entry['A2'].number_format == '@' or entry.column_dimensions['A'].number_format == '@'
    reason_list, = [validation for validation in entry.data_validations.dataValidation
                    if validation.type == 'list' and 'E2' in validation.sqref]
    assert reason_list.formula1.strip('"').split(',') == list(PLAN_REASON_LABELS)
    example = workbook['填写示例']
    assert [cell.comment.text for cell in example[4]] == [cell.comment.text for cell in entry[1]]
    assert '未列出的物料保留' in example['A19'].value
    examples = {row[0]:row[2] for row in example.values if row[0] in PLAN_REASON_LABELS}
    assert set(examples) == set(PLAN_REASON_LABELS)
    assert all(isinstance(text,str) and text.strip() and text != label for label,text in examples.items())

    with pytest.raises(ValueError, match='没有可读取的数据行'):
        parse_file(response.content, '计划导入模板.xlsx', kind='plan')
    row = ['00045', '滤芯', 7, None, '预计用量有变化', '十二月补货', None]
    for col, value in enumerate(row, 1):
        entry.cell(2, col, value)
    workbook.move_sheet(example, offset=-workbook.index(example))
    workbook.active = 0
    content = BytesIO()
    workbook.save(content)
    workbook.close()

    batch = post(planner, '/batches', {'warehouse': 'UK_MAIN', 'period': '2026-12', 'title': '模板导入'})
    assert batch.status_code == 200, batch.text
    version_path = P+'/versions/'+batch.json()['current_id']
    draft = planner.get(version_path).json()
    job = upload(planner, 'plan', content.getvalue(), name='十二月计划.xlsx')
    assert job['state'] == 'DONE' and job['rows'] == 1 and not job['issues'], job
    commit = post(planner, '/imports/'+job['id']+'/commit', {'version_id': draft['id'], 'revision': draft['revision']})
    assert commit.status_code == 200, commit.text
    item, = planner.get(version_path).json()['items']
    source = item['input']
    assert source['material_code'] == '00045' and source['material_name'] == '滤芯'
    assert (source['sea_plan_qty'], source['air_plan_qty']) == ('7', '0')
    assert (source['reason_code'], source['reason']) == ('市场需求变化', '十二月补货')
    assert (source['plan_source']['sheet'], source['plan_source']['row']) == ('计划明细', 2)

def test_new_and_legacy_reason_labels_import_to_same_codes():
    rows = ['物料号,海运计划,原因类别']
    expected = {}
    for index, (label, code) in enumerate(PLAN_REASON_LABELS.items(), 1):
        for material, text in [(f'NEW-{index}', label), (f'OLD-{index}', code)]:
            rows.append(f'{material},1,{text}')
            expected[material] = code
    rows.append('NO-REASON,1,')
    result = parse_file(csvfile(rows), '计划.csv', kind='plan')
    assert not result['issues']
    actual = {item['material_code']: item['reason_code'] for item in result['items']}
    assert not actual.pop('NO-REASON')
    assert actual == expected

def test_plan_import_rejects_unknown_without_mutating_and_duplicate_report(clients):
    p,r,a,s=clients;b,v=current(p)
    job=upload(p,'plan',csvfile(['物料号,海运计划,空运计划','UNKNOWN,4,0']))
    assert job['state']=='DONE'
    assert post(p,'/imports/'+job['id']+'/commit',{'version_id':v['id'],'revision':v['revision']}).status_code==422
    assert p.get(P+'/versions/'+v['id']).json()['items']==v['items']
    job=upload(p,'plan',csvfile(['物料号,海运计划,空运计划','DEMO-0001,4,0','DEMO-0001,5,0']))
    assert len(job['issues'])==2
    assert post(p,'/imports/'+job['id']+'/commit',{'version_id':v['id'],'revision':v['revision']}).status_code==422

def test_plan_import_preserves_snapshot_and_warns_on_invalid_quantity(clients):
    p,r,a,s=clients;b,v=current(p)
    job=upload(p,'plan',csvfile(['物料号,海运计划,空运计划,审核前净额','DEMO-0001,?,0,999999']))
    commit=post(p,'/imports/'+job['id']+'/commit',{'version_id':v['id'],'revision':v['revision']})
    assert commit.status_code==200,commit.text
    nv=p.get(P+'/versions/'+v['id']).json();assert len(nv['items'])==1
    assert nv['items'][0]['input']['net_supply_before_plan']==v['items'][0]['input']['net_supply_before_plan']
    assert nv['items'][0]['result']['data_status']=='ERROR'
    report=p.get(P+'/versions/'+v['id']+'/confirmation').json()
    assert report['error_rows']==1 and report['affected_count']==1
    assert post(p,'/versions/'+v['id']+'/submit',{'revision':nv['revision']}).status_code==200
    frozen=r.get(P+'/versions/'+v['id']).json()['items'][0]
    assert frozen['input']['sea_plan_qty']=='?' and frozen['result']['data_status']=='ERROR'
    assert frozen['result']['future_qty'] is None and frozen['submission_override']['issues']
    assert s.get(P+'/jobs/'+job['id']).status_code==403
    assert r.get(P+'/jobs/'+job['id']+'/download').status_code==403

def test_partial_sources_compute_net_once_preserve_targets_and_source(clients):
    p,r,a,s=clients
    content=csvfile(['物料号,物料名称,物料分类ABC,装车量,近三个月月均销量,近六个月月均销量,是否重点车型,稳态更换率,更换率目标库存,销量目标库存,在库数量,在途数量,在订数量,需求抵扣数量,审核前净额',
      'NEW-01,车灯,A,1200,10,8,是,0.02,80,100,50,10,20,5,999'])
    j=upload(a,'standard',content,mode='COMPONENTS')
    payload={'name':'分项快照','as_of':'2026-09-09','basis':'50+10+20-5=75，当前计划尚未包含'}
    response=post(a,'/imports/'+j['id']+'/commit',payload);assert response.status_code==200,response.text
    sid=response.json()['snapshot_id']
    with SessionLocal() as db:assert db.get(Snapshot,sid).items[0]['net_supply_before_plan']=='75'
    j2=upload(a,'inventory',csvfile(['物料号,在库数量','NEW-01,100']))
    result=post(a,'/imports/'+j2['id']+'/commit',{**payload,'base_snapshot_id':sid})
    assert result.status_code==200,result.text
    with SessionLocal() as db:
        snap=db.get(Snapshot,result.json()['snapshot_id']);assert snap.net_mode=='COMPONENTS'
        assert snap.items[0]['net_supply_before_plan']=='125'
        assert isinstance(snap.items[0]['source_update'],dict)
    j3=upload(a,'targets',csvfile(['物料号,销量目标库存','NEW-01,120']))
    result3=post(a,'/imports/'+j3['id']+'/commit',{**payload,'base_snapshot_id':result.json()['snapshot_id']})
    assert result3.status_code==200,result3.text
    with SessionLocal() as db:
        snap=db.get(Snapshot,result3.json()['snapshot_id']);assert snap.net_mode=='COMPONENTS'
        assert snap.items[0]['net_supply_before_plan']=='125' and snap.items[0]['sales_target']=='120'
        assert db.get(Snapshot,sid).items[0]['net_supply_before_plan']=='75'
    j4=upload(a,'onorder',csvfile(['物料号,在订数量','NEW-01,25']))
    assert post(a,'/imports/'+j4['id']+'/commit',{**payload,'base_snapshot_id':sid,'demand_already_deducted':True}).status_code==422

def test_legacy_bulk_import_has_688_materials_7_errors(clients):
    from synthetic_workbooks import legacy_inventory
    _, _, a, _ = clients
    j=upload(a,'legacy',legacy_inventory(),'合成旧版.xlsx')
    assert j['state']=='DONE',j
    assert j['rows']==688 and not j['issues']
    assert len({i['row'] for i in j['validation']})==7
    result=post(a,'/imports/'+j['id']+'/commit',{'name':'原表兼容','as_of':'2026-08-04','basis':'原T值，当前海空运未包含'})
    assert result.status_code==200,result.text
    with SessionLocal() as db:
        snapshot=db.get(Snapshot,result.json()['snapshot_id']);assert len(snapshot.items)==688
        assert snapshot.source_id==j['id']

def test_export_literal_text_and_audit_scope(clients):
    p,r,a,s=clients;b,v=current(p)
    row=v['items'][0]
    p.patch(P+'/versions/'+v['id']+'/items',json={'revision':v['revision'],'changes':[{'id':row['id'],'values':{'reason':'=HYPERLINK("https://invalid.example")'}}]})
    job=post(p,'/exports',{'version_id':v['id'],'scope':'filtered','q':'DEMO-0001','filter':'all'}).json()
    run_job(job['id']);done=p.get(P+'/jobs/'+job['id']).json();assert done.get('state')=='DONE',done;assert done['rows']==1
    data=p.get(done['download_url']);assert data.status_code==200
    assert s.get(done['download_url']).status_code==403
    wb=load_workbook(BytesIO(data.content));ws=wb['计划审核结果']
    assert ws.max_row==2 and ws['O2'].value.startswith('=HYPERLINK') and ws['O2'].data_type=='s'
    assert wb.active['A2'].data_type=='s' and ws['C2'].data_type=='f'
    assert dict(wb['版本与来源'].values)['导出范围']=='筛选结果'
    wb.close()

def test_job_claim_exclusive_and_expired_lease_recovery(clients):
    p,r,a,s=clients;b,v=current(p)
    jid=post(p,'/exports',{'version_id':v['id']}).json()['id']
    assert claim_job()==jid and claim_job() is None
    with SessionLocal.begin() as db:db.get(Job,jid).lease=1
    assert claim_job()==jid
    run_job(jid)
    assert p.get(P+'/jobs/'+jid).json()['attempts']==2

def test_adapter_empty_mapping_fallback_bad_formats_and_net_mode():
    r=parse_file(csvfile(['物料号,海运计划','001,4']),'a.csv',kind='plan',mapping={'material_code':''})
    assert r['items'][0]['material_code']=='001' and r['items'][0]['air_plan_qty']=='0'
    with pytest.raises(ValueError):parse_file(b'not excel','fake.xlsx')
    with pytest.raises(ValueError):parse_file(b'anything','a.xls')
    with pytest.raises(ValueError):parse_file(b'anything','a.xlsx',kind='legacy',net_mode='COMPONENTS')
