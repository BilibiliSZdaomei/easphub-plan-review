from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api import app
from backend.db import Audit, Idempotency, SessionLocal, User
from test_api import P, clients, post


HEADER = '账号\t姓名\t初始密码\t角色\t授权仓库\n'
SECRET = 'Test initial PW, 2026'


def test_password_length_across_account_flows(clients):
    _, _, admin, _ = clients
    account = {"username":"length-test","name":"长度测试","roles":["PLANNER"],"warehouses":["UK_MAIN"]}
    for password in ("abcde","x"*201," "*6):
        assert post(admin,"/users",{**account,"password":password}).status_code == 422
    assert post(admin,"/users",{**account,"password":"abc123"}).status_code == 200
    preview = post(admin,"/users/bulk/preview",{"table":HEADER+"bulk-length\t长度测试\tabc123\t计划员\tUK_MAIN"})
    assert preview.status_code == 200 and not preview.json()["rows"][0]["issues"]
    with TestClient(app) as user:
        login = user.post(P+"/sessions",json={"username":"length-test","password":"abc123"})
        user.headers["X-CSRF-Token"] = login.json()["csrf"]
        assert post(user,"/password",{"current_password":"abc123","password":"长"*200}).status_code == 200
        assert user.post(P+"/sessions",json={"username":"length-test","password":"长"*200}).status_code == 200


def test_personal_password_change_retires_initial_account_password(clients):
    _, _, admin, _ = clients
    username = 'test-employee-402'
    changed = 'An isolated synthetic test password'
    payload = {'username': username, 'password': username, 'name': 'Test Employee',
               'roles': ['PLANNER'], 'warehouses': ['UK_MAIN']}
    assert post(admin, '/users', payload).status_code == 200
    with TestClient(app) as user, TestClient(app) as other_session:
        def sign_in(client, password):
            return client.post(P+'/sessions', json={'username': username, 'password': password})
        started = sign_in(user, username)
        assert started.status_code == 200 and sign_in(other_session, username).status_code == 200
        user.headers['X-CSRF-Token'] = started.json()['csrf']
        assert post(user, '/password', {'current_password': username, 'password': username}).status_code == 422
        assert post(user, '/password', {'current_password': 'wrong', 'password': changed}).status_code == 403
        assert post(user, '/password', {'current_password': username, 'password': changed}).status_code == 200
        assert other_session.get(P+'/me').status_code == 401
        assert user.get(P+'/me').status_code == 401
        assert sign_in(user, username).status_code == 401
        started = sign_in(user, changed)
        assert started.status_code == 200
        user.headers['X-CSRF-Token'] = started.json()['csrf']
        for invalid in (username, changed):
            assert post(user, '/password', {'current_password': changed, 'password': invalid}).status_code == 422


def test_bulk_preview_and_commit(clients):
    _, _, admin, _ = clients
    table = HEADER + f'a-plan\t计划人员\t{SECRET}\t计划员\t荷兰中心仓、DE_NSC\n' + \
                     f'a-review\t复审人员\t{SECRET}\t复审员\tDE_NSC'
    body = {'table':table}
    preview = post(admin,'/users/bulk/preview',body)
    assert preview.status_code == 200 and SECRET not in preview.text
    assert [r['issues'] for r in preview.json()['rows']]==[[],[]]
    assert preview.json()['rows'][0]['warehouses']==['NL_MAIN','DE_NSC']
    assert 'a-plan' not in [u['username'] for u in admin.get(P+'/users').json()]
    result = post(admin,'/users/bulk',body,key='account-batch-key')
    assert result.status_code==200 and result.json()=={'created':2}
    assert post(admin,'/users/bulk',body,key='account-batch-key').json()=={'created':2}
    assert post(admin,'/users/bulk',{'table':table.replace(SECRET,'A different value')},key='account-batch-key').status_code==409
    with TestClient(app) as new_user:
        login=new_user.post(P+'/sessions',json={'username':'a-plan','password':SECRET})
        assert login.status_code==200 and login.json()['user']['roles']==['PLANNER']
        new_user.headers['X-CSRF-Token']=login.json()['csrf']
        assert post(new_user,'/password',{'current_password':SECRET,'password':'short'}).status_code==422
        account=login.json()['user']
        reset=admin.patch(P+'/users/'+account['id'],json={**account,'password':'x'*201})
        assert reset.status_code==422
        assert {w['code'] for w in new_user.get(P+'/warehouses').json()}=={'NL_MAIN','DE_NSC'}
    with SessionLocal() as db:
        person=db.scalar(select(User).where(User.username=='a-plan'))
        assert person.password_hash.startswith('$argon2') and SECRET not in person.password_hash
        events=db.scalars(select(Audit).where(Audit.action=='创建用户')).all()
        assert len(events)==2 and SECRET not in str([a.detail for a in events])
        records=db.scalars(select(Idempotency)).all()
        assert SECRET not in str([(r.digest,r.response) for r in records])


def test_invalid_rows_no_partial_creation(clients):
    planner, _, admin, _ = clients
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.username=='test_steward')).warehouses=['UK_MAIN']
    data={'table':HEADER + '\n'.join([
        f'can-add\t有效\t{SECRET}\t计划员\tUK_MAIN',
        f'planner\t重复\t{SECRET}\t复审\tES_NSC',
        f'dup\t重复一\t{SECRET}\tUNKNOWN\tUK_MAIN',
        'dup\t重复二\t123\t计划员\tUK_MAIN',
        '一行只有一列'
    ])}
    assert post(planner,'/users/bulk/preview',data).status_code==403
    assert post(planner,'/users/bulk',data).status_code==403
    preview=post(admin,'/users/bulk/preview',data)
    rows=preview.json()['rows']
    assert [(r['line'],len(r['issues'])) for r in rows]==[(2,0),(3,2),(4,2),(5,2),(6,1)]
    result=post(admin,'/users/bulk',data)
    assert result.status_code==422 and result.json()['detail']['rows']==rows
    assert SECRET not in result.text and SECRET not in preview.text
    with SessionLocal() as db:
        assert not db.scalar(select(User).where(User.username=='can-add'))
    assert post(admin,'/users/bulk/preview',{'table':'\ufeff\n'}).status_code==422


def test_csv_with_quoted_fields_and_header_order(clients):
    _, _, admin, _ = clients
    table=f'\ufeff姓名,初始密码,账号,授权仓库,角色\r\n"Lin, Mei","{SECRET}",lin.mei,UK_MAIN,REVIEWER'
    preview=post(admin,'/users/bulk/preview',{'table':table})
    assert preview.status_code==200
    assert preview.json()['rows']==[{'line':2,'username':'lin.mei','name':'Lin, Mei',
                                     'roles':['REVIEWER'],'warehouses':['UK_MAIN'],'issues':[]}]

def test_unassigned_planner_access_and_later_grant(clients):
    planner, _, admin, _ = clients
    snapshot = planner.get(P+'/snapshots').json()[0]
    initial = {'username':'awaiting-warehouse','password':SECRET,'name':'Warehouse assignment pending',
               'roles':['PLANNER'],'warehouses':[]}
    created = post(admin, '/users', initial)
    assert created.status_code == 200 and created.json()['warehouses'] == []
    profile = created.json()
    endpoint = P+'/users/'+profile['id']
    def sign_in(client):
        response = client.post(P+'/sessions', json={'username':initial['username'],'password':SECRET})
        assert response.status_code == 200
        client.headers['X-CSRF-Token'] = response.json()['csrf']
        return response.json()['user']
    with TestClient(app) as user:
        assert sign_in(user)['warehouses'] == []
        for path in ['/warehouses','/batches','/snapshots']:
            assert user.get(P+path).json() == []
        assert user.get(P+'/notification-inbox').json()['total'] == 0
        assert user.get(P+'/snapshots/'+snapshot['id']+'/materials').status_code == 403
        plan = {'warehouse':'UK_MAIN','period':'2026-12','title':'Assignment test'}
        assert post(user,'/batches',plan).status_code == 403
        assert admin.patch(endpoint,json={**profile,'warehouses':['UK_MAIN']}).status_code == 200
        assert user.get(P+'/me').status_code == 401
        assert sign_in(user)['warehouses'] == ['UK_MAIN']
        batch = post(user,'/batches',plan)
        assert batch.status_code == 200
        link = P+'/batches/'+batch.json()['id']
        assert user.get(link).status_code == 200
        assert admin.patch(endpoint,json=profile).status_code == 200
        assert user.get(P+'/me').status_code == 401
        assert sign_in(user)['warehouses'] == []
        assert user.get(P+'/batches').json() == [] and user.get(link).status_code == 403


def test_bulk_unassigned_rows_and_warehouse_validation(clients):
    _, _, admin, _ = clients
    pending = HEADER + f'pending-a\tPerson A\t{SECRET}\t计划员\t\npending-b\tPerson B\t{SECRET}\t计划员'
    preview = post(admin, '/users/bulk/preview', {'table':pending}).json()['rows']
    assert [(r['issues'],r['warehouses']) for r in preview] == [([],[]),([],[])]
    four = 'Role,Username,Initial password,Name\nPLANNER,pending-c,pending-secret,Person C'
    four_row = post(admin,'/users/bulk/preview',{'table':four}).json()['rows'][0]
    assert four_row['username'] == 'pending-c' and not four_row['issues'] and not four_row['warehouses']
    assert post(admin,'/users/bulk',{'table':pending}).json() == {'created':2}
    users = [u for u in admin.get(P+'/users').json() if u['username'] in ('pending-a','pending-b')]
    assert len(users) == 2 and all(u['roles'] == ['PLANNER'] and u['warehouses'] == [] for u in users)
    for grant in ('NOT_A_WAREHOUSE', '；'):
        body = {'table':HEADER + f'invalid-grant\tPerson D\t{SECRET}\t计划员\t{grant}'}
        assert post(admin,'/users/bulk/preview',body).json()['rows'][0]['issues']
        assert post(admin,'/users/bulk',body).status_code == 422
