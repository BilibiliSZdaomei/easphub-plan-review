from test_api import clients,P,post,ready
from backend.demo import DEMO_PASSWORD

def test_combined_planner_and_reviewer_still_cannot_self_approve(clients):
    p,r,a,s=clients
    target=next(u for u in a.get(P+'/users').json() if u['username']=='planner')
    assert a.patch(P+'/users/'+target['id'],json={'roles':['PLANNER','REVIEWER'],'warehouses':target['warehouses'],'active':True}).status_code==200
    login=p.post(P+'/sessions',json={'username':'planner','password':DEMO_PASSWORD});p.headers['X-CSRF-Token']=login.json()['csrf']
    b,v=ready(p);assert post(p,'/versions/'+v['id']+'/submit',{'revision':v['revision']}).status_code==200
    v=p.get(P+'/versions/'+v['id']).json()
    assert post(p,'/versions/'+v['id']+'/reviews',{'revision':v['revision'],'ids':[v['items'][0]['id']],'decision':'APPROVED'}).status_code==403
    assert post(p,'/versions/'+v['id']+'/finalize',{'revision':v['revision']}).status_code==403
    assert post(p,'/versions/'+v['id']+'/return',{'revision':v['revision'],'reason':'自审退回'}).status_code==403
