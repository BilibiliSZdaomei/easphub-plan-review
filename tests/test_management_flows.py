from copy import deepcopy

from backend.db import Rule, SessionLocal, Snapshot, uid
from backend.rules import fingerprint
from test_api import P, clients, current, post


def test_create_custom_rule_inherits_scope_and_preserves_existing_plans(clients):
    planner, publisher, _, _ = clients
    batch, plan = current(planner)
    catalog = publisher.get(P+'/rules').json()
    source = next(rule for rule in catalog['items'] if rule['id'] == catalog['coverage'][batch['warehouse']])
    assert source['id'] == plan['rule']['id']
    custom = deepcopy(source['package'])
    custom['params']['delay_on_hand_months'] = 5
    custom['keywords']['manual'].append('专用检测架')
    custom['overrides']['TEST-RACK'] = 'manual'
    request = {'name':'自定义补货标准', 'source_id':source['id'], 'source_revision':source['revision'],
               'package':custom, 'note':'调整周转月数和专用检测架分类'}
    response = post(publisher, '/rules', request, key='save-custom-rule')
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['id'] != source['id']
    assert (draft['scope'], draft['scope_code']) == (source['scope'], source['scope_code'])
    assert draft['name'] == request['name'] and draft['note'] == request['note']
    assert draft['state'] == 'DRAFT' and not draft['active'] and draft['proof'] is None
    assert draft['package'] == custom
    assert post(publisher, '/rules', request, key='save-custom-rule').json() == draft
    saved = publisher.get(P+'/rules').json()
    assert saved['coverage'] == catalog['coverage']
    assert len(saved['items']) == len(catalog['items']) + 1
    assert next(rule for rule in saved['items'] if rule['id'] == source['id']) == source

    route = '/rules/'+draft['id']
    trial = post(publisher, route+'/dry-run', {'revision':draft['revision'], 'snapshot_id':plan['snapshot']['id']})
    assert trial.status_code == 200, trial.text
    publish = post(publisher, route+'/publish', {'revision':trial.json()['revision'], 'reason':'试算已核对'})
    assert publish.status_code == 200, publish.text
    assert publisher.get(P+'/rules').json()['coverage'][batch['warehouse']] == draft['id']
    previous_plan = planner.get(P+'/versions/'+plan['id']).json()
    assert previous_plan['rule'] == plan['rule']
    assert previous_plan['items'] == plan['items']
    inherited = post(publisher, '/rules', {'source_id':draft['id'], 'name':'下一版草稿'})
    assert inherited.status_code == 200, inherited.text
    assert inherited.json()['package'] == custom


def test_failed_custom_rule_creation_leaves_catalog_unchanged(clients):
    planner, publisher, _, _ = clients
    catalog = publisher.get(P+'/rules').json()
    source = next(rule for rule in catalog['items'] if rule['active'])
    request = {'name':'自定义标准', 'source_id':source['id'], 'source_revision':source['revision'],
               'package':deepcopy(source['package'])}
    assert post(planner, '/rules', request).status_code == 403
    assert post(publisher, '/rules', {**request, 'source_revision':source['revision']+1}).status_code == 409
    request['package']['params']['delay_on_hand_months'] = 0
    assert post(publisher, '/rules', request).status_code == 422
    request['package']['params'] = []
    assert post(publisher, '/rules', request).status_code == 422
    assert publisher.get(P+'/rules').json()['items'] == catalog['items']


def test_trial_impact_includes_flags_and_rows_beyond_the_first_hundred(clients):
    planner, reviewer, _, _ = clients
    batch, version = current(planner)
    with SessionLocal.begin() as db:
        base = db.get(Snapshot, version['snapshot']['id'])
        rows = [{**deepcopy(base.items[0]), 'material_code':f'TRIAL-{i:03}', 'material_name':f'试算配件{i}'} for i in range(121)]
        snapshot = Snapshot(id=uid(), warehouse=base.warehouse, name='试算固定输入', as_of=base.as_of,
                            net_mode=base.net_mode, basis=base.basis, items=rows, digest=fingerprint(rows), creator=batch['owner'])
        db.add(snapshot)
        snapshot_id = snapshot.id
    draft = post(reviewer, '/rules', {'name':'本仓试算', 'scope':'WAREHOUSE','scope_code':batch['warehouse'],
                                      'source_id':version['rule']['id']}).json()
    path = '/rules/'+draft['id']
    draft['package']['keywords']['manual'].append('试算配件')
    edited=reviewer.patch(P+path,json={'revision':draft['revision'],'package':draft['package']}).json()
    trial=post(reviewer,path+'/dry-run',{'revision':edited['revision'],'snapshot_id':snapshot_id}).json()['proof']
    assert trial['changed']==121 and len(trial['changes'])==100
    report=reviewer.get(P+path+'/trial-impacts',params={'page':7,'at':trial['at']}).json()
    assert report['total']==report['recorded']==121 and len(report['items'])==1
    last=report['items'][0]
    assert last['material_code']=='TRIAL-120'
    assert last['before']['review_mode']=='AUTO' and last['after']['review_mode']=='MANUAL'
    assert 'MANUAL' in last['after']['flags']
    assert reviewer.get(P+path+'/trial-impacts',params={'q':'配件120'}).json()['items']==[last]
    assert reviewer.get(P+path+'/trial-impacts',params={'at':'old'}).status_code==409
    with SessionLocal.begin() as db:
        rule=db.get(Rule,draft['id'])
        # Older releases stored only a sample. The response must distinguish its size from the total.
        rule.proof={**rule.proof,'changes':rule.proof['changes'][:100]}
    legacy=reviewer.get(P+path+'/trial-impacts').json()
    assert (legacy['recorded'],legacy['changed'])==(100,121)


def test_unchanged_authorization_keeps_session_and_standard_template_is_identifiable(clients):
    planner, _, admin, _ = clients
    target=next(u for u in admin.get(P+'/users').json() if u['username']=='planner')
    body={key:target[key] for key in ('roles','warehouses','active')}
    assert admin.patch(P+'/users/'+target['id'],json=body).status_code==200
    assert planner.get(P+'/session-state').json()['user']['id']==target['id']
    template=admin.get(P+'/template?kind=standard')
    assert 'standard-data-template.csv' in template.headers['content-disposition'] and '物料号' in template.text
