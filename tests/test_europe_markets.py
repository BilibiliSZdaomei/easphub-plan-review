from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest
from sqlalchemy import select

from backend.api import app
from backend.db import Audit, Base, Batch, Rule, SessionLocal, Snapshot, User, Version, Warehouse, engine
from backend.demo import DEMO_PASSWORD, seed_demo
from backend.jobs import run_job
from backend.markets import EUROPE, EUROPE_RULE_NAME, MARKET_NAMES, register_markets, warehouse_config
from scripts.bootstrap import bootstrap, extend_markets
from test_api import P, clients, post, claim


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def results_file(client, version):
    job = ok(post(client, '/exports', {'version_id':version}))
    run_job(job['id'])
    done = ok(client.get(P+'/jobs/'+job['id']))
    assert done['state']=='DONE', done
    return load_workbook(BytesIO(client.get(done['download_url']).content), data_only=True), done['filename']


def test_v2_workflow_for_all_ten_markets(clients):
    uk, reviewer, steward, spain = clients
    with TestClient(app) as planner:
        auth = ok(planner.post(P+'/sessions', json={'username':'europe_planner','password':DEMO_PASSWORD}))
        planner.headers['X-CSRF-Token'] = auth['csrf']
        warehouses = ok(planner.get(P+'/warehouses'))
        assert [w['market'] for w in warehouses] == ['NL','UK','DE','IT','FR','ES','PL','CH','SE','UZ']
        assert {w['market_name'] for w in warehouses} == set(MARKET_NAMES.values())
        book = load_workbook(BytesIO(steward.get(P+'/template?kind=v2').content))
        sheet = book['审核表']
        for col,value in {'A':'M-001','B':'车门总成','C':'车身件','F':'A','H':50,'I':10000,
                          'M':1,'N':1,'O':1,'P':1,'Q':1,'R':1,'U':5,'W':2,'X':3}.items():
            sheet[col+'2'] = value
        for index,warehouse in enumerate(warehouses):
            code = warehouse['code']
            net = 10+index
            sheet['V2'],sheet['Z2'],sheet['AA2'] = net,net+5,net+6
            buf = BytesIO(); book.save(buf)
            jid = ok(steward.post(P+'/imports', files={'file':('本仓计划.xlsx',buf.getvalue())},
                                  data={'warehouse':code,'kind':'v2'}))['id']
            run_job(jid)
            preview = ok(steward.get(P+'/jobs/'+jid))
            assert preview['state']=='DONE' and preview['rows']==1 and not preview['validation']
            snapshot = ok(post(steward,'/imports/'+jid+'/commit',
                               {'name':'同名快照','as_of':'2026-11-23','basis':'本仓审核前净额'}))['snapshot_id']
            payload = {'warehouse':code,'snapshot_id':snapshot,'title':'同名补货计划','period':'2026-11','use_snapshot_plan':True}
            other = warehouses[(index+1)%len(warehouses)]['code']
            assert post(planner,'/batches',{**payload,'warehouse':other}).status_code==422
            batch = ok(post(planner,'/batches',payload))
            path = '/versions/'+batch['current_id']
            version = ok(planner.get(P+path))
            row = version['items'][0]
            assert version['rule']['name']==EUROPE_RULE_NAME and version['rule']['model']=='V2'
            assert row['input']['material_code']=='M-001' and row['result']['future_qty']==str(net+5)
            assert row['result']['advice']=='备货合理；建议延迟补货'
            for restricted,permitted in [(uk,'UK_MAIN'),(spain,'ES_NSC')]:
                if code!=permitted:
                    assert restricted.get(P+path).status_code==403
            edited=ok(planner.patch(P+path+'/items',json={'revision':version['revision'],'changes':[
                {'id':row['id'],'values':{'air_reason':'合成测试急件'}}]}))
            ok(post(planner,path+'/submit',{'revision':edited['revision']}))
            submitted=claim(reviewer,path)
            review=ok(post(reviewer,path+'/reviews',{'revision':submitted['revision'],'ids':[row['id']],
                      'decision':'APPROVED','reason':'已核对急件及本仓补货时间','air_confirmed':True,
                      'ack_flags':[flag for flag in row['result']['manual_flags'] if flag!='AIR']}))
            assert review['count']==1 and not review['skipped'], review
            reviewed=ok(reviewer.get(P+path))
            ok(post(reviewer,path+'/finalize',{'revision':reviewed['revision']}))
            assert ok(planner.get(P+path))['state']=='APPROVED'
            output,filename=results_file(planner,version['id'])
            meta=dict(output['版本与来源'].values)
            assert (meta['市场'],meta['仓库编码'])==(warehouse['market_name'],code)
            assert output['计划审核结果']['F2'].value==net+5 and warehouse['market'] in filename
            output.close()
        book.close()


def test_market_and_warehouse_rule_override(clients):
    _, reviewer, _, _ = clients
    initial=ok(reviewer.get(P+'/rules'))
    source=next(r for r in initial['items'] if r['scope_code']==EUROPE and r['active'])
    sid=ok(reviewer.get(P+'/snapshots?warehouse=DE_NSC'))[0]['id']
    for scope,code in [('MARKET','DE'),('WAREHOUSE','DE_NSC')]:
        rule=ok(post(reviewer,'/rules',{'source_id':source['id'],'scope':scope,'scope_code':code,'name':code+' 本地标准'}))
        path='/rules/'+rule['id']
        trial=ok(post(reviewer,path+'/dry-run',{'snapshot_id':sid,'revision':rule['revision']}))
        ok(post(reviewer,path+'/publish',{'revision':trial['revision'],'reason':'本地试算核对'}))
        coverage=ok(reviewer.get(P+'/rules'))['coverage']
        assert coverage=={**initial['coverage'],'DE_NSC':rule['id']}


def test_europe_publication_requires_all_ten_warehouses_and_excludes_other_markets(clients):
    _, reviewer, _, _ = clients
    with SessionLocal.begin() as db:
        db.add(Warehouse(code='EXTERNAL',name='区域外测试仓',market='EXT'))
    source=next(r for r in ok(reviewer.get(P+'/rules'))['items'] if r['active'])
    draft=ok(post(reviewer,'/rules',{'source_id':source['id'],'scope':'DEFAULT','name':'区域试算'}))
    path='/rules/'+draft['id']
    sid=ok(reviewer.get(P+'/snapshots?warehouse=NL_MAIN'))[0]['id']
    trial=ok(post(reviewer,path+'/dry-run',{'snapshot_id':sid,'revision':draft['revision']}))
    publish={'revision':trial['revision'],'reason':'已复核区域范围'}
    with SessionLocal.begin() as db:
        account=db.scalar(select(User).where(User.username=='test_reviewer'))
        full=list(account.warehouses)
        account.warehouses=[w for w in full if w!='UZ_NSC']
    assert post(reviewer,path+'/publish',publish).status_code==403
    with SessionLocal.begin() as db:
        db.get(User,account.id).warehouses=full
    assert ok(post(reviewer,path+'/publish',publish))['active']
    with SessionLocal.begin() as db:
        db.get(User,account.id).warehouses=['EXTERNAL']
    outside=ok(reviewer.get(P+'/rules'))
    assert outside['coverage']=={'EXTERNAL':None} and not outside['items']


def test_existing_demo_upgrade_preserves_history_and_restricted_users(clients):
    with SessionLocal.begin() as db:
        marker=db.get(Audit,'demo-europe-markets-v2')
        db.delete(marker)
        old=db.scalar(select(Rule).where(Rule.active.is_(True)))
        old.scope_code='UK';old.name='英国默认标准 · V2'
        saved={v.id:(v.rule_id,v.items,v.revision) for v in db.scalars(select(Version))}
        reviewer=db.scalar(select(User).where(User.username=='test_reviewer'))
        reviewer.warehouses=['UK_MAIN']
    with SessionLocal.begin() as db:
        seed_demo(db)
    with SessionLocal.begin() as db:
        seed_demo(db)
        assert db.query(Batch).count()==2 and db.query(Snapshot).count()==10
        assert db.get(User,reviewer.id).warehouses==['UK_MAIN']
        assert db.query(Rule).filter_by(scope_code=EUROPE,active=True).count()==1
        assert not db.get(Rule,old.id).active
        assert saved=={v.id:(v.rule_id,v.items,v.revision) for v in db.scalars(select(Version))}


def test_existing_installation_extends_without_demo_records(test_database_path):
    assert Path(engine.url.database).resolve()==test_database_path
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    password='Synthetic-administrator-2026'
    bootstrap('manager','管理员',password,[{'code':'UK-CUSTOM','name':'现有英国仓','market':'GB'}])
    with SessionLocal.begin() as db:
        old=db.query(Rule).one()
        old.scope_code='UK';old.name='先前默认标准'
    with pytest.raises(ValueError):
        extend_markets('manager','wrong',warehouse_config())
    first=extend_markets('manager',password,warehouse_config())
    second=extend_markets('manager',password,warehouse_config())
    assert len(first['added'])==9 and second['added']==[]
    assert second['europe_rule_state']=='DRAFT'
    with SessionLocal.begin() as db:
        assert db.query(Warehouse).count()==10 and db.get(Warehouse,'UK_MAIN') is None
        assert db.get(Warehouse,'UK-CUSTOM').name=='现有英国仓'
        assert db.query(User).count()==1 and db.query(Snapshot).count()==0 and db.query(Batch).count()==0
        assert db.query(Rule).count()==2 and db.query(Rule).filter_by(active=True).one().scope_code=='UK'
        with pytest.raises(ValueError,match='其他市场'):
            register_markets(db,[{'code':'UK-CUSTOM','name':'冲突','market':'FR'}])
