"""Initialize a migrated installation or extend its market catalog."""
import argparse,getpass,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.db import transaction,User,Rule,uid,now,audit
from backend.rules import MODEL_V3, default_package, upgrade_to_v3
from backend.auth import hasher, valid_password
from backend.markets import EUROPE, EUROPE_V3_RULE_NAME, LEGACY_DEFAULT, applies_to, register_markets, warehouse_config
from argon2.exceptions import VerificationError

def bootstrap(username,name,password,warehouses):
    if not valid_password(password):raise ValueError('初始密码需为 6–200 位')
    if not username.strip() or not name.strip():raise ValueError('请填写账号与姓名')
    with transaction() as db:
        if db.query(User).first():raise ValueError('数据库已有账号，不能重复初始化，请使用人员管理页面')
        registered, _ = register_markets(db,warehouses)
        admin=User(id=uid(),username=username,name=name,password_hash=hasher.hash(password),roles=['ADMIN'],warehouses=[w.code for w in registered]);db.add(admin)
        scopes = {EUROPE if applies_to('DEFAULT', EUROPE, w) else LEGACY_DEFAULT for w in registered}
        for code in scopes:
            db.add(Rule(id=uid(),name=EUROPE_V3_RULE_NAME if code==EUROPE else '通用标准 · V3',scope='DEFAULT',scope_code=code,
                        state='PUBLISHED',active=True,package=default_package(MODEL_V3),note='未来库存＝在库数量＋审核前净额＋海运计划',
                        creator=admin.id,publisher=admin.id,published_at=now()))
        audit(db,admin,'初始化正式环境',warehouses=admin.warehouses)
    return {'initialized':True,'admin':username,'warehouses':len(warehouses),'demo_data_created':False}


def extend_markets(username, password, warehouses):
    with transaction() as db:
        admin=db.query(User).filter_by(username=username,active=True).with_for_update().first()
        try:
            if not admin or 'ADMIN' not in admin.roles or not hasher.verify(admin.password_hash,password):
                raise ValueError('需要有效的管理账号和密码')
        except VerificationError as exc:
            raise ValueError('需要有效的管理账号和密码') from exc
        registered, added = register_markets(db, warehouses)
        if added:
            admin.warehouses = list(dict.fromkeys([*admin.warehouses,*added]))
        defaults=db.query(Rule).filter_by(scope='DEFAULT')
        european=defaults.filter_by(scope_code=EUROPE,active=True).first()
        if european is None and any(applies_to('DEFAULT',EUROPE,w) for w in registered):
            european=defaults.filter_by(scope_code=EUROPE,state='DRAFT',name=EUROPE_V3_RULE_NAME).first()
            if european is None:
                legacy=defaults.filter_by(scope_code=LEGACY_DEFAULT,active=True).first()
                european=Rule(id=uid(),name=EUROPE_V3_RULE_NAME,scope='DEFAULT',scope_code=EUROPE,state='DRAFT',active=False,
                              package=upgrade_to_v3(legacy.package) if legacy else default_package(MODEL_V3),creator=admin.id,
                              note='欧洲市场共用 V3，未来库存＝在库数量＋审核前净额＋海运计划。')
                db.add(european)
                audit(db,admin,'创建欧洲通用标准草稿',rule_id=european.id)
        if added:
            audit(db,admin,'扩展计划审核市场',warehouses=added)
        return {'added':added,'warehouses':[w.code for w in registered],
                'europe_rule_state':european.state if european else None}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--admin',required=True);p.add_argument('--name');p.add_argument('--warehouses',required=True)
    p.add_argument('--extend-markets',action='store_true');args=p.parse_args()
    if not args.extend_markets and not args.name:p.error('初始化需要 --name')
    try:
        config=warehouse_config(args.warehouses)
        if args.extend_markets:
            result=extend_markets(args.admin,getpass.getpass('现有管理账号密码（不回显）: '),config)
        else:
            password=getpass.getpass('初始管理密码（6–200 位，不回显）: ')
            if password!=getpass.getpass('再输入一次: '):sys.exit('两次密码不一致')
            result=bootstrap(args.admin,args.name,password,config)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as e:sys.exit(str(e))
