from io import BytesIO
from copy import deepcopy
from openpyxl import Workbook
import pytest
from sqlalchemy.exc import IntegrityError
from test_api import clients,P,post,current,ready,claim
from backend.adapters import parse_file
from backend.rules import calculate
from backend.db import SessionLocal,Rule,NotificationEvent,Notification
from backend.jobs import deliver_notifications

def test_uncached_formula_is_not_zero_and_duplicates_rejected():
    wb=Workbook(write_only=True);ws=wb.create_sheet('上游输出');ws.append(['物料号','海运计划']);ws.append(['F001','=1+1']);out=BytesIO();wb.save(out);wb.close()
    result=parse_file(out.getvalue(),'source.xlsx',kind='plan');i=result['items'][0]
    assert '公式没有缓存' in i['sea_plan_qty'] and i['source_formulas']['sea_plan_qty']['formula']=='=1+1'
    assert any(e['field']=='sea_plan_qty' for e in calculate(i)['errors'])
    with pytest.raises(ValueError,match='重名'):parse_file('物料号,海运计划,海运计划\nA,1,2'.encode(),'dup.csv',kind='plan')

def test_disabled_account_sessions_fail_immediately(clients):
    p,r,a,s=clients
    users=a.get(P+'/users').json();target=next(u for u in users if u['username']=='planner')
    disabled=a.patch(P+'/users/'+target['id'],json={'roles':target['roles'],'warehouses':target['warehouses'],'active':False})
    assert disabled.status_code==200
    assert p.get(P+'/batches').status_code==401
    assert p.get(P+'/session-state').json()['user'] is None

def test_review_allows_optional_category_and_summary_of_selected_only(clients):
    p,r,a,s=clients;b,v=ready(p);post(p,'/versions/'+v['id']+'/submit',{'revision':v['revision']})
    v=claim(r,'/versions/'+v['id']);first=next(i['id'] for i in v['items'] if i['input']['material_code']=='DEMO-0001')
    meta=post(r,'/versions/'+v['id']+'/review-summary',{'ids':[first]}).json()
    assert meta=={'flags':[],'exception':False,'count':1}
    result=post(r,'/versions/'+v['id']+'/reviews',{'revision':v['revision'],'ids':[first],'decision':'EXCEPTION_APPROVED'})
    assert result.status_code==200 and result.json()['count']==1

def test_notification_failure_retries_without_reverting_business(clients,monkeypatch):
    import backend.jobs as jobs
    p,r,a,s=clients;b,v=ready(p);post(p,'/versions/'+v['id']+'/submit',{'revision':v['revision']})
    def broken(*a,**k):raise RuntimeError('simulated delivery failure')
    original=jobs.Notification;monkeypatch.setattr(jobs,'Notification',broken)
    assert deliver_notifications() is False
    assert p.get(P+'/batches/'+b['id']).json()['state']=='SUBMITTED'
    monkeypatch.setattr(jobs,'Notification',original)
    with SessionLocal.begin() as db:
        event=db.query(NotificationEvent).first();eid=event.id;event.lease=0
    assert deliver_notifications() is True
    with SessionLocal.begin() as db:
        before=db.query(Notification).count();db.get(NotificationEvent,eid).state='QUEUED'
    assert deliver_notifications() is True
    with SessionLocal() as db:assert db.query(Notification).count()==before

def test_one_active_rule_per_scope_and_invalid_trial_warehouse(clients):
    p,r,a,s=clients;original=r.get(P+'/rules').json()['items'][0]
    copied=post(r,'/rules',{'source_id':original['id'],'name':'UK only','scope':'WAREHOUSE','scope_code':'UK_MAIN'}).json()
    wrong=next(x for x in r.get(P+'/snapshots').json() if x['warehouse']=='ES_NSC')
    assert post(r,'/rules/'+copied['id']+'/dry-run',{'revision':copied['revision'],'snapshot_id':wrong['id']}).status_code==422
    with pytest.raises(IntegrityError):
        with SessionLocal.begin() as db:
            db.add(Rule(name='Duplicate active',scope='DEFAULT',scope_code=original['scope_code'],state='PUBLISHED',active=True,package=deepcopy(original['package']),creator='test'))
