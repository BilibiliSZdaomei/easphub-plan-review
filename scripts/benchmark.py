"""Local reproducible performance gate; synthetic data only, isolated SQLite."""
import os,tempfile,time,json,sys,uuid
from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['PLAN_REVIEW_DATA']=tempfile.mkdtemp(prefix='plan-review-perf-')
os.environ.pop('PLAN_REVIEW_DATABASE_URL',None)
os.environ['PLAN_REVIEW_DEMO']='1';os.environ['PLAN_REVIEW_WORKER']='0'
from backend.api import app
from backend.db import SessionLocal,Snapshot,Version,uid
from backend.rules import calculate,default_package
from backend.adapters import parse_file,FIELDS
from backend.demo import DEMO_PASSWORD
from fastapi.testclient import TestClient
from openpyxl import Workbook
from backend.jobs import run_job
P='/plan-review/api/v1'

def main():
    metrics={'environment':'Windows / Python 3.12 / isolated SQLite; synthetic inputs; ASGI concurrency'}
    with TestClient(app) as admin:
        login=admin.post(P+'/sessions',json={'username':'test_steward','password':DEMO_PASSWORD}).json();admin.headers['X-CSRF-Token']=login['csrf']
        with SessionLocal() as db:base=db.query(Snapshot).first().items[0]
        package=default_package()
        for n in (1000,10000):
            items=[{**base,'material_code':f'PERF-{i:05d}'} for i in range(n)]
            start=time.perf_counter();results=[calculate(i,package) for i in items];metrics[f'calculate_{n}_seconds']=round(time.perf_counter()-start,3)
            wb=Workbook(write_only=True);ws=wb.create_sheet('标准数据');ws.append(list(FIELDS.values()))
            for i in items:ws.append([i.get(k) for k in FIELDS])
            stream=BytesIO();wb.save(stream);wb.close()
            start=time.perf_counter();j=admin.post(P+'/imports',files={'file':('perf.xlsx',stream.getvalue())},data={'warehouse':'UK_MAIN','kind':'standard'}).json();run_job(j['id'])
            job=admin.get(P+'/jobs/'+j['id']).json();assert job['state']=='DONE',job
            response=admin.post(P+'/imports/'+j['id']+'/commit',json={'name':f'PERF-{n}','as_of':'2026-09-09','basis':'Synthetic supplied net; new plans excluded'},headers={'Idempotency-Key':uuid.uuid4().hex});assert response.status_code==200,response.text
            metrics[f'import_{n}_seconds']=round(time.perf_counter()-start,3)
            if n==1000:snapshot_id=response.json()['snapshot_id']
        sessions=[];batches=[]
        for i in range(20):
            c=TestClient(app);login=c.post(P+'/sessions',json={'username':'planner','password':DEMO_PASSWORD});assert login.status_code==200
            c.headers['X-CSRF-Token']=login.json()['csrf'];sessions.append(c)
            if i<5:
                b=c.post(P+'/batches',json={'warehouse':'UK_MAIN','snapshot_id':snapshot_id,'title':f'PERF-{i}','period':'2026-09','use_snapshot_plan':True},headers={'Idempotency-Key':uuid.uuid4().hex});assert b.status_code==200,b.text;batches.append(b.json())
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=20) as pool:responses=list(pool.map(lambda c:c.get(P+'/batches'),sessions))
        metrics['twenty_sessions_read_seconds']=round(time.perf_counter()-start,3);assert all(r.status_code==200 for r in responses)
        def edit(i):
            c=sessions[i];v=c.get(P+'/versions/'+batches[i]['current_id']).json()
            return c.patch(P+'/versions/'+v['id']+'/items',json={'revision':v['revision'],'changes':[{'id':row['id'],'values':{'sea_plan_qty':'36'}} for row in v['items']]})
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=5) as pool:responses=list(pool.map(edit,range(5)))
        metrics['five_parallel_draft_saves_seconds']=round(time.perf_counter()-start,3);assert all(r.status_code==200 for r in responses),[r.text[:100] for r in responses]
        metrics['concurrent_sessions_passed']=20;metrics['concurrent_saves_passed']=5
        # Capture request latency for the PRD's normal-page / one-row-save gate.
        read_times=[];save_times=[];c=sessions[0];version_id=batches[0]['current_id']
        for sample in range(30):
            started=time.perf_counter();response=c.get(P+'/versions/'+version_id);read_times.append(time.perf_counter()-started)
            assert response.status_code==200;v=response.json();assert len(v['items'])<=30
            started=time.perf_counter();response=c.patch(P+'/versions/'+version_id+'/items',json={'revision':v['revision'],'changes':[{'id':v['items'][0]['id'],'values':{'sea_plan_qty':str(36+sample%2)}}]});save_times.append(time.perf_counter()-started)
            assert response.status_code==200,response.text
        metrics['latency_samples_per_action']=30
        metrics['page_read_p95_ms']=round(sorted(read_times)[28]*1000,1)
        metrics['single_row_save_p95_ms']=round(sorted(save_times)[28]*1000,1)
        for c in sessions:c.close()
    metrics['gates_passed']=metrics['calculate_1000_seconds']<=2 and metrics['calculate_10000_seconds']<=20 and metrics['import_1000_seconds']<=15 and metrics['import_10000_seconds']<=60 and metrics['page_read_p95_ms']<=800 and metrics['single_row_save_p95_ms']<=800
    (ROOT/'output').mkdir(exist_ok=True);(ROOT/'output'/'performance.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(metrics,ensure_ascii=False,indent=2))
    return metrics['gates_passed']
if __name__=='__main__':sys.exit(not main())
