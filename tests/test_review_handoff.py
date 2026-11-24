from test_api import P, clients, post, ready
from test_data import csvfile, upload


def test_bulk_review_preserves_individual_decisions_and_audits_applied_ids(clients):
    planner, reviewer, _, _ = clients
    batch, draft = ready(planner)
    path = '/versions/' + draft['id']
    assert post(planner, path+'/submit', {'revision':draft['revision']}).status_code == 200
    version = reviewer.get(P+path).json()
    ordinary = [r['id'] for r in version['items'] if r['result']['quantity_status']=='WITHIN'
                and not r['result']['manual_flags'] and r['result']['data_status']!='ERROR']
    first, second = ordinary[:2]
    saved = post(reviewer, path+'/reviews', {'revision':version['revision'],'ids':[first],
                 'decision':'EXCEPTION_APPROVED','reason_code':'特殊物料','reason':'复核后保留特殊订单'})
    assert saved.status_code == 200
    decision = reviewer.get(P+path+'/items/'+first).json()['decision']
    meta = post(reviewer, path+'/review-summary', {'ids':[first,second],'only_pending':True}).json()
    assert meta['count']==1 and meta['preserved']==1
    bulk = post(reviewer, path+'/reviews', {'revision':saved.json()['revision'],'ids':[first,second],
                 'decision':'APPROVED','only_pending':True}).json()
    assert bulk['count']==1 and bulk['preserved']==1 and not bulk['skipped']
    assert reviewer.get(P+path+'/items/'+first).json()['decision']==decision
    event = next(event for event in reviewer.get(P+'/batches/'+batch['id']).json()['events']
                 if event['action']=='保存行复审')
    assert event['detail']['ids']==[second]
    repeat = post(reviewer, path+'/reviews', {'revision':bulk['revision'],'ids':[first],
                  'decision':'APPROVED','only_pending':True}).json()
    assert repeat['count']==0 and repeat['preserved']==1 and repeat['revision']==bulk['revision']


def test_targeted_return_carries_only_this_round_through_plan_reimport(clients):
    planner, reviewer, _, spain = clients
    batch, draft = ready(planner)
    path = '/versions/'+draft['id']
    assert post(planner, path+'/submit', {'revision':draft['revision']}).status_code == 200
    version = reviewer.get(P+path).json()
    marked = next(row for row in version['items'] if row['input']['material_code']=='DEMO-0001')
    other = next(row for row in version['items'] if row['input']['material_code']=='DEMO-0002')
    payload = {'revision':version['revision'],'reason':'请核对指定物料的补货节奏'}
    assert post(reviewer,path+'/return',{**payload,'ids':['wrong-row']}).status_code==422
    assert reviewer.get(P+path).json()['state']=='SUBMITTED'
    returned = post(reviewer,path+'/return',{**payload,'ids':[marked['id']]}).json()
    current = '/versions/'+returned['version_id']
    selected = planner.get(P+current+'?filter=returned').json()
    assert selected['summary']['return_requested']==1
    assert selected['items'][0]['id']==marked['id'] and selected['items'][0]['decision'] is None
    assert planner.get(P+current+'/selection?filter=returned').json()['ids']==[marked['id']]
    assert spain.get(P+current+'/selection?filter=returned').status_code==403
    previous = planner.get(P+path+'/items/'+marked['id']).json()
    assert not previous.get('return_requested')
    event = planner.get(P+'/batches/'+batch['id']).json()['events'][0]
    assert event['detail']['material_codes']==['DEMO-0001']
    job = upload(planner,'plan',csvfile(['物料号,海运计划,空运计划','DEMO-0001,35,0','DEMO-0002,35,0']))
    assert post(planner,'/imports/'+job['id']+'/commit',{'version_id':returned['version_id'],
                'revision':selected['revision']}).status_code==200
    assert planner.get(P+current+'/selection?filter=returned').json()['ids']==[marked['id']]
    result = planner.get(P+current+'/confirmation').json()
    submitted = post(planner,current+'/submit',{'revision':result['revision'],'force':True,
                     'accept_issues':True,'reason':'核实后重新提交','issue_hash':result['issue_hash']})
    assert submitted.status_code==200
    again = post(reviewer,current+'/return',{'revision':submitted.json()['revision'],'ids':[other['id']],
                 'reason':'请核对另一项'}).json()
    assert planner.get(P+'/versions/'+again['version_id']+'/selection?filter=returned').json()['ids']==[other['id']]
    assert planner.get(P+current+'/items/'+marked['id']).json()['return_requested']

