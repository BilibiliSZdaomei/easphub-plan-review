from copy import deepcopy
import csv
from io import StringIO

from sqlalchemy import func, select

from backend.comparison import compare_items
from backend.db import Audit, Notification, Rule, SessionLocal, Snapshot, User, Version, uid
from backend.rules import fingerprint
from test_api import P, clients, current, post, ready, claim
from test_data import upload, csvfile


def test_preview_is_read_only_and_matches_committed_basis(clients):
    planner, reviewer, _, spain = clients
    batch, version = current(planner)
    path = '/versions/' + version['id']
    with SessionLocal() as db:
        original = db.get(Snapshot, version['snapshot']['id'])
        rows = deepcopy(original.items)
        code = rows[0]['material_code']
        rows[0].update(net_supply_before_plan='1000', sea_plan_qty='999', reason='快照自带说明')
        replacement = Snapshot(id=uid(), name='新快照', warehouse=original.warehouse, as_of='2026-10-01',
                               net_mode=original.net_mode, basis=original.basis, creator=batch['owner'],
                               items=rows, digest=fingerprint(rows))
        published = db.get(Rule, version['rule']['id'])
        new_rule = Rule(id=uid(), name='本仓新版', scope='WAREHOUSE', scope_code=batch['warehouse'],
                        state='PUBLISHED', active=True, package=deepcopy(published.package), creator=batch['owner'])
        db.add_all([replacement, new_rule])
        db.flush()
        snapshot_id, rule_id = replacement.id, new_rule.id
        foreign_snapshot = db.scalar(select(Snapshot.id).where(Snapshot.warehouse=='ES_NSC'))
        db.commit()

    request = dict(revision=version['revision'], snapshot_id=snapshot_id, rule_id=rule_id)
    for action in ('/snapshot-preview', '/basis'):
        assert post(spain, path+action, request).status_code == 403
        assert post(reviewer, path+action, request).status_code == 403
        assert post(planner, path+action, {**request, 'snapshot_id':foreign_snapshot}).status_code == 422
        assert post(planner, path+action, {**request, 'revision':99}).status_code == 409

    with SessionLocal() as db:
        rows_before = deepcopy(db.get(Version, version['id']).items)
        audit_before = db.scalar(select(func.count()).select_from(Audit))
    response = post(planner, path+'/snapshot-preview', request)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['snapshot']['id'] == snapshot_id and preview['rule']['id'] == rule_id
    assert preview['affected_count'] == preview['quantity_changed_count'] == 1
    assert preview['items'][0]['material_code'] == code
    assert preview['items'][0]['result_fields']['quantity_status'] == {'before':'WITHIN','after':'ABOVE'}
    with SessionLocal() as db:
        stored = db.get(Version, version['id'])
        assert stored.items == rows_before and stored.revision == version['revision']
        assert (stored.snapshot_id, stored.rule_id) == (version['snapshot']['id'], version['rule']['id'])
        assert db.scalar(select(func.count()).select_from(Audit)) == audit_before
    accepted = post(planner, path+'/basis', {**request, 'revision':preview['revision']})
    assert accepted.status_code == 200 and accepted.json()['revision'] > preview['revision']
    with SessionLocal() as db:
        stored = db.get(Version, version['id'])
        assert (stored.snapshot_id, stored.rule_id) == (snapshot_id, rule_id)
        assert compare_items(rows_before, stored.items)['items'] == preview['items']
        assert stored.items[0]['input']['sea_plan_qty'] == rows_before[0]['input']['sea_plan_qty']
        assert stored.items[0]['input']['reason'] == rows_before[0]['input']['reason']
        assert db.scalar(select(func.count()).select_from(Audit).where(
            Audit.action=='切换计算依据', Audit.version_id==stored.id)) == 1
    assert post(planner, path+'/basis', request).status_code == 409


def test_diff_includes_zero_review_only_and_all_rows(clients):
    planner, _, _, spain = clients
    batch, version = current(planner)
    with SessionLocal() as db:
        first = db.get(Version, version['id'])
        old = deepcopy(first.items)
        old[0]['input']['sea_plan_qty'] = None
        first.items = old
        rows = deepcopy(old[:-1])
        rows[0]['input']['sea_plan_qty'] = 0
        rows[0]['result']['sea_feasible'] = False
        rows[1]['decision'] = {'status':'APPROVED','reason':'与需求一致','reviewer_name':'复审员'}
        rows[2]['submission_override'] = {'reason':'已核对例外','stage':'submit'}
        rows[3]['input']['source_values'] = {'source':{'file':'另一个文件.xlsx'}}
        rows[3]['input']['source_update'] = {'file':'同值更新.xlsx','row':30}
        for i in range(27):
            extra = deepcopy(old[-1])
            extra['id'] = uid()
            extra['input']['material_code'] = f'NEW-{i:04d}'
            rows.append(extra)
        later = Version(id=uid(), batch_id=batch['id'], seq=2, snapshot_id=first.snapshot_id,
                        rule_id=first.rule_id, items=rows)
        db.add(later)
        db.flush()
        later_id = later.id
        db.commit()
    url = P+'/versions/'+later_id+'/diff?against='+version['id']
    result = planner.get(url)
    assert result.status_code == 200, result.text
    diff = result.json()
    assert diff['summary']['total'] == 31 and len(diff['items']) == 31
    assert diff['summary']['added'] == 27 and diff['summary']['removed'] == 1
    assert diff['summary']['modified'] == 3 and diff['summary']['decision_changed'] == 2
    assert (diff['from_version']['seq'], diff['to_version']['seq']) == (1,2)
    assert not diff['rule_changed'] and not diff['snapshot_changed']
    by_code = {r['material_code']:r for r in diff['items']}
    assert by_code[old[0]['input']['material_code']]['fields']['sea_plan_qty'] == {'before':None, 'after':0}
    assert by_code[old[0]['input']['material_code']]['result_fields']['sea_feasible']['after'] is False
    assert by_code[old[1]['input']['material_code']]['decision_fields']['status']['after'] == 'APPROVED'
    assert by_code[old[2]['input']['material_code']]['override_fields']['reason']['after'] == '已核对例外'
    assert by_code[old[-1]['input']['material_code']]['change'] == '删除'
    assert by_code['NEW-0026']['change'] == '新增'
    assert spain.get(url).status_code == 403
    new_batch = post(planner,'/batches',{'warehouse':batch['warehouse'], 'title':'单独批次',
                                        'period':batch['period'], 'snapshot_id':version['snapshot']['id']})
    assert new_batch.status_code == 200, new_batch.text
    assert planner.get(P+'/versions/'+later_id+'/diff?against='+new_batch.json()['current_id']).status_code == 422


def test_switch_in_returned_draft_preserves_history_and_plan_source(clients):
    planner, reviewer, _, _ = clients
    _, version = ready(planner)
    old_path = '/versions/'+version['id']
    with SessionLocal() as db:
        draft = db.get(Version,version['id'])
        items = deepcopy(draft.items)
        items[0]['input']['plan_source'] = {'file':'海运.csv','sheet':'计划','row':2}
        items[0]['input']['plan_source_formulas'] = {'sea_plan_qty':{'formula':'=30+5','cached':'35'}}
        draft.items = items
        db.commit()
    revision = planner.get(P+old_path).json()['revision']
    assert post(planner,old_path+'/submit',{'revision':revision}).status_code == 200
    pending = claim(reviewer,old_path)
    reviewed = post(reviewer,old_path+'/reviews',{'revision':pending['revision'],'ids':[items[0]['id']],'decision':'APPROVED'})
    assert reviewed.status_code == 200 and reviewed.json()['count'] == 1
    returned = post(reviewer,old_path+'/return',{'revision':reviewed.json()['revision'],'ids':[items[1]['id']],'reason':'更新快照'})
    assert returned.status_code == 200
    new_path = '/versions/'+returned.json()['version_id']
    draft = planner.get(P+new_path).json()
    history = planner.get(P+old_path).json()
    with SessionLocal() as db:
        snapshot = db.get(Snapshot,draft['snapshot']['id'])
        def save_snapshot(rows):
            candidate=Snapshot(id=uid(),warehouse=snapshot.warehouse,name='快照',as_of='2026-10-02',
                               net_mode=snapshot.net_mode,basis=snapshot.basis,items=rows,
                               digest=fingerprint(rows),creator=snapshot.creator)
            db.add(candidate)
            return candidate.id
        inputs = deepcopy(snapshot.items)
        inputs[0]['net_supply_before_plan'] = '900'
        new_id = save_snapshot(inputs)
        incomplete_id = save_snapshot(inputs[1:])
        db.commit()
    for action in ('/snapshot-preview','/basis'):
        assert post(planner,old_path+action,{'snapshot_id':new_id,'revision':history['revision']}).status_code == 409
        assert post(planner,new_path+action,{'snapshot_id':incomplete_id,'revision':draft['revision']}).status_code == 422
    body = {'snapshot_id':new_id,'revision':draft['revision']}
    preview = post(planner,new_path+'/snapshot-preview',body)
    assert preview.status_code == 200 and preview.json()['affected_count'] == 1
    assert post(planner,new_path+'/basis',body).status_code == 200
    row = planner.get(P+new_path+'/items/'+items[0]['id']).json()
    assert row['input']['plan_source'] == items[0]['input']['plan_source']
    assert row['input']['plan_source_formulas'] == items[0]['input']['plan_source_formulas']
    assert row['input']['net_supply_before_plan'] == '900'
    assert planner.get(P+old_path).json() == history
    changed = planner.get(P+new_path+'/diff?against='+version['id']).json()
    assert changed['snapshot_changed'] and not changed['rule_changed']
    assert changed['items'][0]['decision_fields']['status'] == {'before':'APPROVED','after':None}


def test_item_lookup_and_notifications_visibility(clients):
    planner, reviewer, _, spain = clients
    batch, version = current(planner)
    row = version['items'][-1]
    url = P+'/versions/'+version['id']+'/items/'
    assert planner.get(url+row['id']).json() == row
    assert reviewer.get(url+row['id']).json() == row
    assert planner.get(url+'missing').status_code == 404
    assert spain.get(url+row['id']).status_code == 403

    with SessionLocal() as db:
        reviewer_id = db.scalar(select(User.id).where(User.username=='test_reviewer'))
        db.add_all([Notification(user_id=batch['owner'],warehouse=batch['warehouse'],batch_id=batch['id'],
                                 text='待办 '+str(i)) for i in range(105)])
        db.add_all([Notification(user_id=batch['owner'],warehouse='ES_NSC',batch_id=batch['id'],text='仓库不可见'),
                    Notification(user_id=reviewer_id,warehouse=batch['warehouse'],batch_id=batch['id'],text='其他收件人')])
        db.commit()
    assert len(planner.get(P+'/notifications').json()) == 100
    all_visible = planner.get(P+'/notifications?all=true').json()
    assert len(all_visible) == 105 and all(n['text'].startswith('待办 ') for n in all_visible)
    assert not spain.get(P+'/notifications?all=true').json()


def test_import_empty_and_complete_issue_download(clients):
    planner, _, _, spain = clients
    empty = upload(planner,'plan',csvfile(['物料号,海运计划,空运计划']))
    assert empty['state']=='FAILED' and '没有可读取的数据行' in empty['error']
    rows = ['物料号,海运计划,空运计划']+['DUP,?,0']*105
    checked = upload(planner,'plan',csvfile(rows))
    assert checked['state']=='DONE' and checked['rows']==105 and checked['sheet']=='CSV'
    assert checked['issues_total']==105 and len(checked['issues'])==100
    assert checked['validation_total']==105 and len(checked['validation'])==100
    url=P+'/imports/'+checked['id']+'/errors'
    downloaded=planner.get(url)
    assert downloaded.status_code==200
    issues=list(csv.DictReader(StringIO(downloaded.content.decode('utf-8-sig'))))
    assert len(issues)==210
    assert all(e['物料号']=='DUP' and e['文件']=='data.csv' and e['工作表']=='CSV' for e in issues)
    assert {e['字段'] for e in issues if e['行号']=='106'}=={'material_code','sea_plan_qty'}
    assert spain.get(url).status_code==403

