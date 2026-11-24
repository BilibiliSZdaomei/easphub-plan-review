from sqlalchemy import delete

from backend.db import SessionLocal, Snapshot
from backend.demo import DEMO_PASSWORD
from test_api import P, clients, post
from test_data import csvfile, upload


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def assert_pending(row):
    result = row['result']
    assert result['data_status'] == 'PENDING'
    assert result['review_mode'] == 'MANUAL'
    assert result['quantity_status'] == 'UNAVAILABLE'
    for field in ('lower', 'upper', 'future_qty', 'suggested_sea_qty'):
        assert result[field] is None
    assert row['input'].get('net_supply_before_plan') is None


def test_new_warehouse_can_plan_and_complete_manual_review(clients):
    uk, reviewer, _, planner = clients
    warehouse = 'DE_NSC'
    with SessionLocal.begin() as db:
        db.execute(delete(Snapshot).where(Snapshot.warehouse == warehouse))
    request = {'warehouse': warehouse, 'title': '首月补货', 'period': '2026-12'}
    assert post(uk, '/batches', request).status_code == 403
    session = ok(planner.post(P+'/sessions', json={'username': 'europe_planner', 'password': DEMO_PASSWORD}))
    planner.headers['X-CSRF-Token'] = session['csrf']
    snapshots = P+'/snapshots?warehouse='+warehouse
    assert ok(planner.get(snapshots)) == []

    batch = ok(post(planner, '/batches', request))
    path = '/versions/'+batch['current_id']
    draft = ok(planner.get(P+path))
    assert draft['state'] == 'DRAFT' and draft['snapshot'] is None and draft['items'] == []
    assert post(planner, path+'/submit', {'revision': draft['revision']}).status_code == 422
    plan_item = {'material_code': '00045', 'material_name': '前照灯', 'sea_plan_qty': '3', 'air_plan_qty': '1'}
    ok(post(planner, path+'/items', {'revision': draft['revision'], 'items': [plan_item]}))
    draft = ok(planner.get(P+path))
    row, = draft['items']
    assert {key: row['input'][key] for key in plan_item} == plan_item
    assert_pending(row)

    warnings = ok(planner.get(P+path+'/confirmation'))
    assert warnings['affected_count'] == 1 and warnings['rows'][0]['issues']
    ok(post(planner, path+'/submit', {'revision': draft['revision'], 'issue_hash': warnings['issue_hash']}))
    submitted = ok(reviewer.get(P+path))
    assert submitted['snapshot'] is None
    assert_pending(submitted['items'][0])
    assert submitted['items'][0]['submission_override']['issue_hash'] == warnings['issue_hash']
    decision = ok(post(reviewer, path+'/reviews', {'revision': submitted['revision'], 'ids': [row['id']],
                  'decision': 'EXCEPTION_APPROVED', 'reason': '已人工核实需求'}))
    final_warnings = ok(reviewer.get(P+path+'/confirmation?stage=finalize'))
    approved = ok(post(reviewer, path+'/finalize',
                  {'revision': decision['revision'], 'issue_hash': final_warnings['issue_hash']}))
    assert approved['state'] == 'APPROVED'
    frozen = ok(planner.get(P+path))['items'][0]
    assert_pending(frozen)
    assert frozen['decision']['status'] == 'EXCEPTION_APPROVED'
    assert ok(planner.get(snapshots)) == []


def test_import_plan_first_and_attach_published_basis_without_reentry(clients):
    planner, _, steward, spain = clients
    request = {'warehouse': 'UK_MAIN', 'title': '后补依据', 'period': '2026-12', 'snapshot_id': None}
    batch = ok(post(planner, '/batches', request))
    path = '/versions/'+batch['current_id']
    draft = ok(planner.get(P+path))
    plan = upload(planner, 'plan', csvfile(['物料号,物料名称,海运计划,空运计划,审核前净额', '00045,前照灯,7,2,99999']))
    ok(post(planner, '/imports/'+plan['id']+'/commit', {'revision': draft['revision'], 'version_id': draft['id']}))
    draft = ok(planner.get(P+path))
    row, = draft['items']
    assert row['input']['material_code'] == '00045'
    assert_pending(row)
    foreign = ok(spain.get(P+'/snapshots?warehouse=ES_NSC'))[0]
    assert post(planner, path+'/basis', {'revision': draft['revision'], 'snapshot_id': foreign['id']}).status_code == 422

    source = csvfile(['物料号,物料名称,物料分类ABC,装车量,近三个月月均销量,近六个月月均销量,是否重点车型,稳态更换率,更换率目标库存,销量目标库存,审核前净额',
                      '00045,前照灯总成,A,1200,10,8,是,0.02,80,100,50'])
    job = upload(steward, 'standard', source)
    published = ok(post(steward, '/imports/'+job['id']+'/commit',
                        {'name': '本月业务数据', 'as_of': '2026-11-24', 'basis': '审核前净额已扣需求'}))
    body = {'revision': draft['revision'], 'snapshot_id': published['snapshot_id']}
    preview = ok(post(planner, path+'/snapshot-preview', body))
    assert preview['affected_count'] == 1
    assert ok(planner.get(P+path))['snapshot'] is None
    ok(post(planner, path+'/basis', body))
    assert post(planner, path+'/basis', body).status_code == 409
    bound = ok(planner.get(P+path))
    assert bound['snapshot']['id'] == published['snapshot_id']
    matched, = bound['items']
    assert matched['id'] == row['id']
    assert matched['input']['plan_source'] == row['input']['plan_source']
    assert (matched['input']['material_name'], matched['input']['net_supply_before_plan']) == ('前照灯总成', '50')
    assert (matched['input']['sea_plan_qty'], matched['input']['air_plan_qty']) == ('7', '2')
    assert matched['result']['data_status'] != 'PENDING'
    assert matched['result']['future_qty'] == '59'
