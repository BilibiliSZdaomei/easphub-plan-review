import pytest

from test_api import P, clients, post, claim, ready


def test_reviewers_can_maintain_warehouse_data_but_cannot_manage_users(clients):
    planner, reviewer, admin, _ = clients
    me=reviewer.get(P+'/me').json()['user']
    assert me['roles']==['REVIEWER']
    for path in ('/users','/users/bulk/preview','/users/bulk'):
        assert post(reviewer,path,{}).status_code==403
    assert reviewer.get(P+'/users').status_code==403
    assert reviewer.patch(P+'/users/'+me['id'],json={'roles':['ADMIN']}).status_code==403
    for member in (reviewer,admin):
        result=post(member,'/mappings',{'name':'欧洲测试映射','warehouse':'UK_MAIN','config':{}})
        assert result.status_code==200
        assert result.json()['id'] in {m['id'] for m in member.get(P+'/mappings').json()}
    assert post(reviewer,'/mappings',{'name':'其他仓','warehouse':'UNKNOWN','config':{}}).status_code==403
    assert post(planner,'/mappings',{'name':'计划员不可维护','warehouse':'UK_MAIN','config':{}}).status_code==403
    assert post(planner,'/rules',{}).status_code==403


def test_admin_can_submit_and_review_someone_elses_plan(clients):
    planner, _, admin, _ = clients
    _, draft=ready(planner)
    path='/versions/'+draft['id']
    assert post(planner,path+'/submit',{'revision':draft['revision']}).status_code==200
    review=claim(admin,path)
    completed=post(admin,path+'/finalize',{'revision':review['revision']})
    assert completed.status_code==200 and completed.json()['state']=='APPROVED'
    snapshot=draft['snapshot']['id']
    created=post(admin,'/batches',{'warehouse':'UK_MAIN','period':'2026-12','title':'管理人员计划',
                                    'snapshot_id':snapshot,'use_snapshot_plan':True})
    assert created.status_code==200
    own='/versions/'+created.json()['current_id']
    submitted=post(admin,own+'/submit',{'revision':created.json()['revision']})
    assert submitted.status_code==200
    assert post(admin,own+'/claim',{'revision':submitted.json()['revision']}).status_code==403


@pytest.mark.parametrize('invalid', [['VIEWER'], ['RULE_EDITOR'], ['DATA_STEWARD'], ['PLANNER','REVIEWER'], []])
def test_new_accounts_require_exactly_one_supported_role(clients,invalid):
    _, _, admin, _=clients
    body={'name':'测试','username':'role-test','password':'synthetic','warehouses':['UK_MAIN'],'roles':invalid}
    assert post(admin,'/users',body).status_code==422
    table='\t'.join(('bulk-test','测试','synthetic','、'.join(invalid),'UK_MAIN'))
    result=post(admin,'/users/bulk/preview',{'table':table})
    assert result.status_code==200 and result.json()['rows'][0]['issues']
    assert post(admin,'/users/bulk',{'table':table}).status_code==422
