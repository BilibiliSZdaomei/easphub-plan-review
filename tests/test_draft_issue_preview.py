from copy import deepcopy

from backend.db import SessionLocal, Version
from test_api import P, clients, current, post


def test_preview_uses_submit_rules_even_for_old_results_and_never_saves_edits(clients):
    planner, reviewer, _, foreign = clients
    _, version = current(planner)
    path = '/versions/' + version['id']
    request = {'revision': version['revision'], 'edits': {}}
    row_id = version['items'][0]['id']
    with SessionLocal() as db:
        draft = db.get(Version, version['id'])
        rows = deepcopy(draft.items)
        rows[0]['result']['errors'].append({'field':'old', 'message':'旧缓存提示'})
        draft.items = rows
        db.commit()
        request['revision'] = draft.revision
    confirmed = planner.get(P + path + '/confirmation?all=true').json()
    response = post(planner, path + '/issue-preview', request)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['affected'] == confirmed['affected_count']
    assert '旧缓存提示' not in response.text
    assert preview['counts']['advisory'] == confirmed['affected_count']
    for page in range(1, preview['pages'] + 1):
        result = post(planner, path + '/issue-preview', {**request, 'page':page}).json()
        assert len(result['rows']) <= 8
        for item in result['rows']:
            warning = next(row for row in confirmed['rows'] if row['id'] == item['id'])
            assert item['messages'] == list(dict.fromkeys(issue['message'] for issue in warning['issues']))
    edited = post(planner, path + '/issue-preview', {**request, 'edits':{row_id:{'sea_plan_qty':'-1'}}})
    assert edited.status_code == 200
    assert post(planner, path + '/issue-preview', {**request, 'edits':{'other':{}}}).status_code == 409
    assert post(planner, path + '/issue-preview', {**request, 'revision':-2}).status_code == 409
    for account in (reviewer, foreign):
        assert post(account, path + '/issue-preview', request).status_code == 403
    with SessionLocal() as db:
        draft = db.get(Version, version['id'])
        assert draft.items == rows and draft.revision == request['revision']
