from backend.demo import DEMO_PASSWORD
from test_api import P, clients, post


CUSTOM = {
    'hair': 'Mohawk', 'facialHair': 'Shadow', 'body': 'Hoodie', 'eyes': 'Hearts',
    'mouth': 'Whistle', 'nose': 'Button', 'accessories': 'Earring',
    'skinColor': 'ffdfc4', 'hairColor': '123456', 'facialHairColor': '654321',
    'bodyColor': 'abcdef', 'accessoriesColor': '0a1b2c', 'bgColor': '010203',
}


def test_custom_avatar_round_trip_and_restore_preset(clients):
    planner, reviewer, admin, _ = clients
    endpoint = P + '/profile/avatar'
    ident = planner.get(P + '/me').json()['user']['id']
    saved = planner.patch(endpoint, json={'avatar_config': CUSTOM})
    assert saved.status_code == 200, saved.text
    user = saved.json()
    expected = {k: v.upper() if k.endswith('Color') else v for k, v in CUSTOM.items()}
    assert user['avatar_config'] == {**expected,'skin':'Skin','head':'Head'}
    assert user['avatar_source'] == 'draftbit-personas' and user['avatar_revision'] == '7b5234c44b3cef49d483b1462398bc9ea07bfa12'
    assert {row['id']: row for row in admin.get(P + '/users').json()}[ident] == user
    assert reviewer.get(P + '/session-state').json()['user']['avatar_config'] is None
    assert planner.delete(P + '/sessions/current').status_code == 200
    signed_in = planner.post(P + '/sessions', json={'username': user['username'], 'password': DEMO_PASSWORD}).json()
    assert signed_in['user'] == user
    planner.headers['X-CSRF-Token'] = signed_in['csrf']
    reset = planner.patch(endpoint, json={'avatar_preset':'parts'})
    assert reset.status_code == 200 and reset.json()['avatar_config'] is None and reset.json()['avatar_preset'] == 'parts'
    assert planner.get(P + '/session-state').json()['user'] == reset.json()


def test_avatar_validates_config_and_suspended_accounts(clients):
    planner, reviewer, admin, _ = clients
    endpoint = P + '/profile/avatar'
    before = planner.get(P + '/session-state').json()['user']
    other = reviewer.get(P + '/session-state').json()['user']
    for config in ({}, dict(CUSTOM,hair='unknown'), dict(CUSTOM,head='test'), dict(CUSTOM,skinColor='ABC'),
                   dict(CUSTOM,hairColor='#123456'), dict(CUSTOM,bgColor='<svg/>'), dict(CUSTOM,url='file:///'),
                   dict(CUSTOM,src='data:image/svg+xml;base64,...'), dict(CUSTOM,bodyColor=123456)):
        assert planner.patch(endpoint, json={'avatar_config':config}).status_code == 422
    assert planner.patch(endpoint, json={'avatar_config':CUSTOM,'avatar_preset':'plan'}).status_code == 422
    assert planner.patch(endpoint, json={'avatar_config':CUSTOM,'user_id':other['id']}).status_code == 422
    assert planner.patch(endpoint, json={'avatar_config':CUSTOM},headers={'X-CSRF-Token':'wrong'}).status_code == 403
    assert planner.get(P + '/session-state').json()['user'] == before
    update = admin.patch(P + '/users/' + before['id'], json={'roles':before['roles'],'warehouses':before['warehouses'],'active':False})
    assert update.status_code == 200
    assert planner.patch(endpoint,json={'avatar_config':CUSTOM}).status_code == 401
    assert reviewer.get(P + '/session-state').json()['user'] == other


def test_avatar_is_per_account_and_survives_new_login(clients):
    planner, reviewer, admin, _ = clients
    endpoint = P + '/profile/avatar'
    original = planner.get(P + '/me').json()['user']
    assert original['avatar_preset'] == 'blank'
    for preset in ('plan', 'parts', 'order', 'order'):
        saved = planner.patch(endpoint, json={'avatar_preset': preset})
        assert saved.status_code == 200 and saved.json() == {**original, 'avatar_preset': preset}
    assert reviewer.get(P + '/me').json()['user']['avatar_preset'] == 'blank'
    listed = {row['id']: row for row in admin.get(P + '/users').json()}
    assert listed[original['id']]['avatar_preset'] == 'order'
    assert planner.delete(P + '/sessions/current').status_code == 200
    assert planner.patch(endpoint, json={'avatar_preset': 'plan'}).status_code == 401
    login = planner.post(P + '/sessions', json={'username': original['username'], 'password': DEMO_PASSWORD})
    assert login.json()['user']['avatar_preset'] == 'order'
    assert planner.get(P + '/session-state').json()['user'] == {**original, 'avatar_preset': 'order'}


def test_default_and_restore_blank_in_self_and_user_management(clients):
    from backend.db import SessionLocal, UserAvatar
    planner, reviewer, admin, _ = clients
    endpoint = P + '/profile/avatar'
    user = planner.get(P + '/me').json()['user']
    assert user['avatar_preset'] == 'blank' and user['avatar_config'] is None
    created = post(admin, '/users', {'username':'blank-test','name':'Blank Test', 'roles':['PLANNER'],
                                    'warehouses':[], 'password':DEMO_PASSWORD})
    assert created.status_code == 200, created.text
    assert created.json()['avatar_preset'] == 'blank' and created.json()['avatar_config'] is None
    review_avatar = reviewer.patch(endpoint, json={'avatar_preset':'order'}).json()
    for design in ({'avatar_preset':'plan'}, {'avatar_config':CUSTOM}, {'avatar_preset':'blank'}):
        assert planner.patch(endpoint, json=design).status_code == 200
        cleared = planner.patch(endpoint, json={'avatar_preset':'blank'})
        assert cleared.status_code == 200 and cleared.json() == user
        with SessionLocal() as db:
            assert db.get(UserAvatar,user['id']) is None
    listed = {row['id']: row for row in admin.get(P + '/users').json()}
    assert listed[user['id']] == user and listed[review_avatar['id']] == review_avatar
    assert listed[created.json()['id']] == created.json()
    assert planner.delete(P + '/sessions/current').status_code == 200
    signed_in = planner.post(P + '/sessions',json={'username':user['username'],'password':DEMO_PASSWORD})
    assert signed_in.json()['user'] == user
    assert planner.get(P + '/session-state').json()['user'] == user


def test_avatar_rejects_unlisted_choices_and_changes_to_other_profiles(clients):
    planner, reviewer, _, _ = clients
    endpoint = P + '/profile/avatar'
    user = planner.get(P + '/me').json()['user']
    other = reviewer.get(P + '/me').json()['user']
    for payload in ({}, {'avatar_preset': None}, {'avatar_preset': 'undefined'},
                    {'avatar_preset': 'parts', 'id': other['id']}, {'avatar_preset': 'parts', 'roles': ['ADMIN']}):
        assert planner.patch(endpoint,json=payload).status_code == 422
    planner.headers.pop('X-CSRF-Token')
    assert planner.patch(endpoint, json={'avatar_preset': 'order'}).status_code == 403
    assert planner.get(P + '/session-state').json()['user'] == user
    assert reviewer.get(P + '/session-state').json()['user'] == other
