from pathlib import Path
from io import BytesIO
from copy import deepcopy
import json
import time
import threading
from sqlalchemy import select, or_, and_, update
from .db import SessionLocal, Job, Version, Rule, Snapshot, DATA, now,NotificationEvent,Notification,User
from .adapters import parse_file, FIELDS
from .rules import calculate, serial, number

FILES=DATA/'files'
FILES.mkdir(parents=True,exist_ok=True)

from .exporting import export_workbook

# Successful polling/processing progress, used only by the production probe.
WORKER_PROGRESS = {}

def file_validation(items,kind,package=None):
    problems=[]
    for item in items:
        if kind in ('standard','legacy','v2'):
            errors=calculate(item,package)['errors']
        elif kind=='plan':
            errors=[]
            for field in ('sea_plan_qty','air_plan_qty'):
                try:
                    value=number(item.get(field))
                    if value is None or value<0:
                        raise ValueError('请输入非负数量')
                except ValueError as exc:
                    errors.append({'field':field,'message':FIELDS[field]+'：'+str(exc)})
        else:
            continue
        for error in errors:
            problems.append({'file':item['source']['file'],'sheet':item['source']['sheet'],'row':item['source']['row'],
                             'material_code':item['material_code'],'repair_hint':'核对源文件后重新导入',**error})
    return problems


def run_job(job_id):
    with SessionLocal() as db:
        job=db.get(Job,job_id);payload=deepcopy(job.payload);kind=job.kind
        rule_id=payload.get('validation_rule_id') if kind=='import' else None
        rule=db.get(Rule,rule_id) if rule_id else None
        validation_package=rule.package if rule else None
    try:
        if kind=='import':
            result=parse_file((FILES/payload['file_id']).read_bytes(),payload['filename'],payload['kind'],payload.get('mapping'),payload['net_mode'],payload.get('sheet_name'))
            result['validation']=file_validation(result['items'],result['kind'],validation_package)
        elif kind=='export':
            content=export_workbook(payload)
            file_id=job_id+'.xlsx';tmp=FILES/(file_id+'.tmp');tmp.write_bytes(content);tmp.replace(FILES/file_id)
            result={'file_id':file_id,'filename':payload['filename'],'rows':len(payload['items'])}
        else:raise ValueError('未知任务类型')
        with SessionLocal.begin() as db:
            job=db.get(Job,job_id);job.result=result;job.state='DONE';job.finished_at=now();job.error=None
    except Exception as e:
        with SessionLocal.begin() as db:
            job=db.get(Job,job_id);job.state='FAILED';job.error=str(e)[:1000];job.finished_at=now()

def claim_job():
    with SessionLocal.begin() as db:
        candidate=db.scalar(select(Job).where(or_(Job.state=='QUEUED',and_(Job.state=='RUNNING',Job.lease<time.time()))).order_by(Job.created_at).with_for_update(skip_locked=True).limit(1))
        if not candidate:return None
        count=db.execute(update(Job).where(Job.id==candidate.id,or_(Job.state=='QUEUED',and_(Job.state=='RUNNING',Job.lease<time.time()))).values(state='RUNNING',lease=time.time()+300,attempts=Job.attempts+1)).rowcount
        return candidate.id if count else None

def worker_loop(stop):
    while not stop.is_set():
        try:
            deliver_notifications()
            job=claim_job()
            if job:run_job(job)
            else:stop.wait(.4)
            WORKER_PROGRESS[threading.get_ident()] = time.time()
        except Exception:
            stop.wait(1)

def deliver_notifications():
    import hashlib
    with SessionLocal.begin() as db:
        event=db.scalar(select(NotificationEvent).where(or_(NotificationEvent.state=='QUEUED',and_(NotificationEvent.state=='RUNNING',NotificationEvent.lease<time.time()))).order_by(NotificationEvent.created_at).with_for_update(skip_locked=True).limit(1))
        if event is None:return False
        eid=event.id
        won=db.execute(update(NotificationEvent).where(NotificationEvent.id==eid,or_(NotificationEvent.state=='QUEUED',and_(NotificationEvent.state=='RUNNING',NotificationEvent.lease<time.time()))).values(state='RUNNING',lease=time.time()+30,attempts=NotificationEvent.attempts+1)).rowcount
        if not won:return False
    try:
        with SessionLocal.begin() as db:
            event=db.get(NotificationEvent,eid);p=event.payload
            for u in db.scalars(select(User).where(User.active.is_(True))):
                if p['warehouse'] not in u.warehouses or not (('REVIEWER' in u.roles) if p['reviewers'] else u.id==p['owner']):continue
                nid=hashlib.sha256((eid+u.id).encode()).hexdigest()[:32]
                if not db.get(Notification,nid):db.add(Notification(id=nid,user_id=u.id,batch_id=p['batch_id'],warehouse=p['warehouse'],text=p['text']))
            event.state='DONE';event.error=None
        return True
    except Exception as e:
        with SessionLocal.begin() as db:
            event=db.get(NotificationEvent,eid);event.state='RUNNING';event.lease=time.time()+min(300,2**min(event.attempts,8));event.error=type(e).__name__
        return False

def start_workers(count=2):
    stop=threading.Event();threads=[]
    for _ in range(count):
        t=threading.Thread(target=worker_loop,args=(stop,),daemon=True);t.start();threads.append(t)
    return stop,threads

if __name__=='__main__':
    from .db import init_db
    init_db();stop,threads=start_workers()
    try:
        for thread in threads:thread.join()
    except KeyboardInterrupt:stop.set()
