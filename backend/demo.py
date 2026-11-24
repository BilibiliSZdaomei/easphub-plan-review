from copy import deepcopy
from sqlalchemy import select
from .db import User, Warehouse, Rule, Snapshot, Batch, Version, Audit, uid, now
from .rules import calculate, default_package, fingerprint, upgrade_to_v2
from .auth import hasher
from .markets import EUROPE, LEGACY_DEFAULT, EUROPE_RULE_NAME, MARKET_NAMES, market_key, register_markets, warehouse_config, superseded_codes

from secrets import token_urlsafe

# Random test-fixture login scoped to the isolated process.
DEMO_PASSWORD = token_urlsafe(24)
def demo_items():
    base={"material_type":"车身件","material_abc":"A","local_abc":"B","is_key_model":True,"fleet_qty":"5926",
          "avg_sales_3m":"10","avg_sales_6m":"8","replacement_rate":"0.00149","replacement_target":"100","sales_target":"80",
          "net_supply_before_plan":"50","sea_plan_qty":"35","air_plan_qty":"0","uom":"PCS","quantity_step":"1",
          "on_hand_qty":"40","in_transit_qty":"20","on_order_qty":"10","demand_deduction_qty":"20","reason":"","reason_code":"","air_reason":""}
    specs=[('前保险杠总成',{}),('左前门外板',{'sea_plan_qty':'10'}),('后视镜总成',{'sea_plan_qty':'70'}),
           ('动力电池总成',{'fleet_qty':'8000','net_supply_before_plan':'5','sea_plan_qty':'6'}),
           ('前制动盘',{'net_supply_before_plan':'80','sea_plan_qty':'45'}),
           ('固定螺栓',{'sea_plan_qty':'500'}),('诊断工具套装',{'sea_plan_qty':'8'}),
           ('尾灯总成',{'net_supply_before_plan':'30','sea_plan_qty':'5','replacement_target':'28','sales_target':'27'}),
           ('补胎液',{'fleet_qty':'3960','avg_sales_3m':'0','avg_sales_6m':'0','net_supply_before_plan':'1','sea_plan_qty':'210'}),
           ('前轮毂',{'sea_plan_qty':'35','air_plan_qty':'2'}),
           ('空调压缩机',{'replacement_rate':None,'replacement_target':'0','sales_target':'66','sea_plan_qty':'10'}),
           ('子午线轮胎',{'net_supply_before_plan':'0','sea_plan_qty':'0'}),
           ('车门装饰条',{'avg_sales_3m':'0','avg_sales_6m':'0','fleet_qty':'500','replacement_target':'5','net_supply_before_plan':'2','sea_plan_qty':'10'}),
           ('散热器总成',{}),('后轮轴承',{}),('前翼子板',{'sea_plan_qty':'25'}),('底部护罩',{}),('车窗升降器',{})]
    return [{**base,**kw,'material_code':f'DEMO-{n:04d}','material_name':name,'source':{'file':'脱敏演示数据','sheet':'示例','row':n+1,'adapter':'DEMO-v1'}} for n,(name,kw) in enumerate(specs,1)]

def seed_original_plans(db, users, rule):
    for warehouse,owner in [('UK_MAIN',users['planner']),('ES_NSC',users['spain'])]:
        inputs=demo_items()
        snap=Snapshot(id=uid(),warehouse=warehouse,name='脱敏演示快照 · 9月',as_of='2026-09-09',net_mode='NET_PROVIDED',basis='演示：净额已处理需求，本次海空运未计入',items=inputs,digest=fingerprint(inputs),creator=users['test_steward'].id)
        db.add(snap);db.flush()
        batch=Batch(id=uid(),number='PR-DEMO-'+warehouse,title='9月常规补货计划',warehouse=warehouse,period='2026-09',owner=owner.id,state='DRAFT')
        db.add(batch);db.flush()
        items=[{'id':uid(),'input':deepcopy(i),'result':calculate(i,rule.package),'decision':None} for i in inputs]
        ver=Version(id=uid(),batch_id=batch.id,seq=1,snapshot_id=snap.id,rule_id=rule.id,items=items)
        db.add(ver);batch.current_id=ver.id


def market_demo_snapshot(warehouse):
    items = demo_items()
    regular, small, air = items[0], items[5], items[9]
    regular.update(on_hand_qty='50', net_supply_before_plan='100')
    small.update(on_hand_qty='5', net_supply_before_plan='150', avg_sales_3m='0', avg_sales_6m='0', sea_plan_qty='5')
    items = [regular, small, air]
    market = MARKET_NAMES[market_key(warehouse.market)]
    for idx, item in enumerate(items, 2):
        item.update(vehicle_parc='12000', vehicle_model='示例车型',
                    source={'file':'V2 合成演示', 'sheet':market, 'row':idx, 'adapter':'DEMO-V2'})
    return Snapshot(id=uid(), warehouse=warehouse.code, name=market+' · V2 演示快照', as_of='2026-11-23',
                    net_mode='NET_PROVIDED', basis='合成演示数据，净库存已扣需求，本次海空运未计入。',
                    items=items, digest=fingerprint(items), creator='demo-bootstrap')


def seed_demo(db):
    marker = 'demo-europe-markets-v2'
    if db.get(Audit, marker):
        return
    fresh = db.scalar(select(User.id).limit(1)) is None
    users = {u.username:u for u in db.scalars(select(User).where(
        User.username.in_(['planner','spain','test_reviewer','test_steward','viewer','europe_planner'])))}
    if not fresh:
        original = db.scalar(select(Batch).where(Batch.number=='PR-DEMO-UK_MAIN'))
        if not original or 'planner' not in users or original.owner != users['planner'].id:
            return
    warehouses, added = register_markets(db, warehouse_config())
    codes = [w.code for w in warehouses]
    accounts = [('planner','计划员 · 英国',['PLANNER'],['UK_MAIN']),
                ('spain','计划员 · 西班牙',['PLANNER'],['ES_NSC']),('viewer','管理查看',['VIEWER'],['UK_MAIN']),
                ('test_reviewer','复审员',['REVIEWER','RULE_EDITOR','RULE_PUBLISHER'],codes),
                ('test_steward','数据维护员',['ADMIN','DATA_STEWARD','RULE_EDITOR'],codes),
                ('europe_planner','欧洲计划员',['PLANNER'],codes)]
    for username, name, roles, allowed in accounts:
        account = users.get(username)
        if fresh or (username=='europe_planner' and account is None):
            account = User(id=uid(), username=username, name=name, roles=roles, warehouses=allowed,
                           password_hash=hasher.hash(DEMO_PASSWORD))
            db.add(account)
            users[username] = account
        elif (account and account.active and username in ('test_reviewer','test_steward') and set(account.roles)==set(roles)
              and set(account.warehouses)=={'UK_MAIN','ES_NSC'}):
            account.warehouses = codes
    active = select(Rule).where(Rule.scope=='DEFAULT', Rule.active.is_(True), Rule.state=='PUBLISHED')
    rule = db.scalar(active.where(Rule.scope_code==EUROPE))
    previous = db.scalar(active.where(Rule.scope_code==LEGACY_DEFAULT))
    if rule is None:
        rule = Rule(id=uid(), name=EUROPE_RULE_NAME, scope='DEFAULT', scope_code=EUROPE, state='PUBLISHED',
                    active=True, package=upgrade_to_v2(previous.package) if previous else default_package(),
                    creator='demo-bootstrap', publisher='demo-bootstrap', published_at=now(), note='欧洲市场共用 V2，未来库存包含本次海运和空运。')
        db.add(rule)
        if previous and LEGACY_DEFAULT in superseded_codes('DEFAULT', EUROPE, db.scalars(select(Warehouse)).all()):
            previous.active = False
    db.flush()
    if fresh:
        seed_original_plans(db, users, rule)
    for warehouse in warehouses:
        if warehouse.code in added and warehouse.code not in ('UK_MAIN','ES_NSC'):
            db.add(market_demo_snapshot(warehouse))
    db.add(Audit(id=marker, user_id='demo-bootstrap', action='初始化欧洲演示市场',
                 detail={'warehouses':added,'rule_id':rule.id,'previous_default':previous.id if previous else None}))
