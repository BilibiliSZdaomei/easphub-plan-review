from backend.db import SessionLocal, User, audit
from test_api import P, clients, current, post, ready, claim


def test_copy_selected_version_and_read_only_its_activity(clients):
    planner, reviewer, _, spain = clients
    batch, old = ready(planner)
    original = old['items'][0]
    route = '/versions/' + old['id']
    assert post(planner, route+'/submit', {'revision':old['revision']}).status_code == 200
    report = claim(reviewer,route)
    returned = post(reviewer, route+'/return', {'revision':report['revision'], 'reason':'补充本次订货量', 'ids':[original['id']]})
    assert returned.status_code == 200, returned.text
    new_id = returned.json()['version_id']
    new_route = '/versions/'+new_id
    updated = planner.get(P+new_route).json()
    count = original['input']['sea_plan_qty']
    row_id = updated['items'][0]['id']
    assert planner.patch(P+new_route+'/items',json={'revision':updated['revision'],'changes':[{'id':row_id,'values':{'sea_plan_qty':int(count)+5}}]}).status_code == 200
    old_now = planner.get(P+route).json()
    params = {'version_id':old['id'],'revision':old_now['revision'],'title':'跨周补货','period':'2027-W01'}
    copy_url='/batches/'+batch['id']+'/copy'
    created = post(planner,copy_url,params,'one-copy')
    assert created.status_code == 200, created.text
    assert post(planner,copy_url,params,'one-copy').json()['id'] == created.json()['id']
    assert created.json()['period']=='2027-W01' and created.json()['title']=='跨周补货'
    copy_route = '/versions/'+created.json()['current_id']
    copied = planner.get(P+copy_route).json()
    assert copied['items'][0]['input']==original['input'] and copied['snapshot']['id']==old['snapshot']['id']
    assert copied['items'][0]['id']!=original['id'] and copied['items'][0]['decision'] is None
    assert not any(key in copied['items'][0] for key in ('return_requested','previous_decision','adjustment','submission_override'))
    copy_event=planner.get(P+copy_route+'/activity').json()['items'][0]
    assert copy_event['detail']=={'source_number':batch['number'],'source_seq':1}
    assert '退回修改' in {e['action'] for e in planner.get(P+route+'/activity').json()['items']}
    assert '退回修改' not in {e['action'] for e in planner.get(P+new_route+'/activity').json()['items']}
    assert spain.get(P+route+'/activity').status_code==403
    assert post(planner,copy_url,{**params,'revision':old_now['revision']-1}).status_code==409
    before=planner.get(P+'/batches').json()
    assert post(planner,copy_url,{**params,'rule_id':'retired-rule'}).status_code==409
    assert len(planner.get(P+'/batches').json())==len(before)
    assert post(planner,copy_url,{**params,'version_id':copied['id']}).status_code==422
    lean=planner.get(P+'/batches/'+batch['id']+'?include_events=false').json()
    assert len(lean['events'])==1 and lean['events'][0]['detail']['new_version']==new_id


def test_activity_pagination_and_summary(clients):
    planner, *_ = clients
    batch, version = current(planner)
    with SessionLocal.begin() as db:
        owner=db.get(User,batch['owner'])
        for n in range(25):
            audit(db,owner,'修改计划',batch['warehouse'],batch['id'],version['id'],changes=[{'id':str(n)}])
    path=P+'/versions/'+version['id']+'/activity'
    first=planner.get(path).json()
    last=planner.get(path+'?page=900').json()
    assert first['total']>=25 and len(first['items'])==12 and last['page']==3
    assert not ({e['id'] for e in first['items']} & {e['id'] for e in last['items']})
    assert first['items'][0]['detail']=={'count':1}
