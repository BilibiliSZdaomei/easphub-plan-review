from copy import deepcopy
from io import BytesIO

import pytest
from openpyxl import load_workbook

from backend.db import Batch, Job, SessionLocal, Version
from backend.exporting import execution_basis, export_workbook
from backend.jobs import FILES, run_job
from backend.rules import calculate, default_package
from test_api import P, clients, current, post
from test_rules import row


def sheet_rows(sheet):
    headers,*rows=sheet.values
    return [dict(zip((h.splitlines()[0] for h in headers),values)) for values in rows]


@pytest.mark.parametrize('model',['0804','V2','V3'])
def test_archive_and_executable_amounts_for_approved_filter_only(model):
    policy=default_package(model)
    items=[]
    for code,status in [('ACCEPT','EXCEPTION_APPROVED'),('DENY','REJECTED')]:
        source=row(material_code=code,sea_plan_qty=12,air_plan_qty=3,current_sales=0,shortage_qty=0)
        items.append({'id':code,'input':source,'result':calculate(source,policy),'decision':{'status':status}})
    for state,label in [('REJECTED','整单不批准'),('RETURNED','整单退回'),('PARTIALLY_APPROVED','历史结案（旧规则）'),
                        ('APPROVED','整单记录待核'),('IN_REVIEW','复审中')]:
        body={'items':items[:1],'rule_package':policy,'filtered':True,'metadata':{'版本状态':state},
              'execution':execution_basis(state,items,True)}
        book=load_workbook(BytesIO(export_workbook(body)),data_only=True)
        for sheet in [book.active,book['计划审核结果']]:
            [entry]=sheet_rows(sheet)
            assert entry['整单结论']==label
            assert entry['本版可执行海运量']==entry['本版可执行空运量']==0
            assert entry['海运计划']==12 and entry['空运计划']==3
            if state=='PARTIALLY_APPROVED':
                assert entry['历史核准海运量（旧规则）']==12 and entry['历史核准空运量（旧规则）']==3
            else:
                assert '历史核准海运量（旧规则）' not in entry
        assert dict(book['版本与来源'].values)['整单结论']==label
        book.close()

    for current_version,expected in [(True,12),(False,0)]:
        basis=execution_basis('APPROVED',items[:1],current_version)
        book=load_workbook(BytesIO(export_workbook({'items':items[:1],'metadata':{'版本状态':'APPROVED'},
                                                  'rule_package':policy,'execution':basis})),data_only=True)
        assert sheet_rows(book.active)[0]['本版可执行海运量']==expected
        assert sheet_rows(book.active)[0]['本版可执行空运量']==(3 if current_version else 0)
        book.close()


def test_filtered_archive_job_freezes_whole_version_and_preserves_old_download(clients):
    planner,*_=clients
    batch,version=current(planner)
    with SessionLocal.begin() as db:
        ver=db.get(Version,version['id'])
        rows=deepcopy(ver.items)
        for item in rows: item['decision']={'status':'APPROVED'}
        rows[-1]['decision']={'status':'REJECTED'}
        code=rows[0]['input']['material_code']
        expected=float(rows[0]['input']['sea_plan_qty'])
        ver.items=rows
        ver.state=db.get(Batch,batch['id']).state='PARTIALLY_APPROVED'
    job_id=post(planner,'/exports',{'version_id':version['id'],'scope':'filtered','q':code}).json()['id']
    run_job(job_id)
    job=planner.get(P+'/jobs/'+job_id).json()
    assert '历史结案（旧规则）' in job['filename']
    output=planner.get(job['download_url'])
    assert output.status_code==200
    book=load_workbook(BytesIO(output.content),data_only=True)
    [entry]=sheet_rows(book.active)
    assert entry['本版可执行海运量']==0 and entry['历史核准海运量（旧规则）']==expected
    book.close()
    with SessionLocal.begin() as db:
        cached=db.get(Job,job_id)
        old={**cached.result}
        old.pop('execution_format')
        cached.result=old
        stored=FILES/old['file_id']
    blocked=planner.get(job['download_url'])
    assert blocked.status_code==409 and '重新导出' in blocked.json()['detail']
    assert stored.read_bytes()==output.content
    # Published archives and current-version downloads have independent status and row snapshots.
    with SessionLocal.begin() as db:
        prior=db.get(Job,job_id)
        prior.payload={**prior.payload,'metadata':{**prior.payload['metadata'],'版本状态':'DRAFT'}}
    assert planner.get(job['download_url']).status_code==200


def test_pre_upgrade_approved_job_and_filtered_legacy_download(clients):
    planner,*_=clients
    batch,draft=current(planner)
    with SessionLocal.begin() as db:
        ver=db.get(Version,draft['id'])
        items=deepcopy(ver.items)
        for item in items: item['decision']={'status':'APPROVED'}
        code=items[0]['input']['material_code']
        requested=float(items[0]['input']['sea_plan_qty'])
        ver.items=items
        ver.state=db.get(Batch,batch['id']).state='APPROVED'
    job_id=post(planner,'/exports',{'version_id':draft['id'],'scope':'filtered','q':code}).json()['id']
    with SessionLocal.begin() as db:
        job=db.get(Job,job_id)
        legacy_payload=dict(job.payload)
        legacy_payload.pop('execution')
        job.payload=legacy_payload
    run_job(job_id)
    result=planner.get(P+'/jobs/'+job_id).json()
    content=planner.get(result['download_url'])
    assert content.status_code==200
    book=load_workbook(BytesIO(content.content),data_only=True)
    [entry]=sheet_rows(book.active)
    assert entry['整单结论']=='整单通过' and entry['本版可执行海运量']==requested
    book.close()
    with SessionLocal.begin() as db:
        job=db.get(Job,job_id)
        meta=dict(job.result)
        meta.pop('execution_format')
        job.result=meta
    assert planner.get(result['download_url']).status_code==200
    with SessionLocal.begin() as db:
        ver=db.get(Version,draft['id'])
        malformed=deepcopy(ver.items)
        malformed[-1]['decision']={'status':'REJECTED'}
        ver.items=malformed
    assert planner.get(result['download_url']).status_code==409
