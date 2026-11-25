import csv
from io import StringIO
from copy import deepcopy
from fastapi import APIRouter, Body, Depends, Request, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import Response
from .master_import import read_master, MASTER_ENGLISH
from .adapters import MAX_BYTES
from .governance import MASTER_FIELDS, effective_input
from typing import Any
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from .db import *
from .api_common import context, once
from .auth import role, scope, hasher, public_user, password_change, valid_password
from .rules import MODEL_V2, MODEL_V3, DELAY_DEFAULTS, TURNOVER_DEFAULTS, upgrade_to_v2, upgrade_to_v3, validate_package, calculate, fingerprint, PARAM_LABELS, FLAG_LABELS
from . import services as svc
from .markets import EUROPE, LEGACY_DEFAULT, applies_to, rule_scopes, superseded_codes
from .account_import import ROLE_NAMES, inspect_accounts
from .account_email import normalize_email
from .workflow_outbox import refresh_recipient_email

router=APIRouter()

def check_master_scope(package,kind,code):
    master=package.get('master_data')
    svc.demand(master is None or (kind=='WAREHOUSE' and master['warehouse']==code),'物料主数据只能用于所属仓库的标准')

@router.get('/rules/master-template')
def master_template(ctx=Depends(context,scope="function"),lang:str='zh'):
    _,user=ctx;role(user,'REVIEWER')
    labels = ['Material number',*(MASTER_ENGLISH[key] for key in MASTER_FIELDS)] if lang=='en' else ['物料号',*MASTER_FIELDS.values()]
    buf=StringIO()
    csv.writer(buf).writerow(labels)
    content='\ufeff'+buf.getvalue()
    return Response(content,media_type='text/csv',headers={'Content-Disposition':'attachment; filename=material-master.csv'})

@router.post('/rules/master-preview')
def master_preview(warehouse:str=Form(...),file:UploadFile=File(...),ctx=Depends(context,scope="function")):
    _,user=ctx;role(user,'REVIEWER');scope(user,warehouse)
    try:
        items=read_master(file.file.read(MAX_BYTES+1),file.filename or '')
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'warehouse':warehouse,'items':items}

def rule_access(db,user,rule_id):
    r=db.get(Rule,rule_id);svc.demand(r is not None,'规则不存在',404)
    if r.scope=='WAREHOUSE':scope(user,r.scope_code)
    elif r.scope=='MARKET':
        svc.demand(bool(db.scalar(select(Warehouse).where(Warehouse.code.in_(user.warehouses),Warehouse.market==r.scope_code))),'没有该市场规则权限',403)
    elif r.scope=='DEFAULT' and r.scope_code==EUROPE:
        allowed = db.scalars(select(Warehouse).where(Warehouse.code.in_(user.warehouses)))
        svc.demand(any(applies_to('DEFAULT', EUROPE, w) for w in allowed),'没有欧洲市场的规则权限',403)
    return r
def editable_scope(db,user,kind,code):
    affected={w.code for w in db.scalars(select(Warehouse)) if applies_to(kind,code,w)}
    svc.demand(affected and affected<=set(user.warehouses),'只能维护已获全部仓库授权的标准',403)

def rule_json(r, proof_visible=True):
    proof=r.proof if proof_visible else None
    if proof:
        proof={**proof,'changes':proof.get('changes',[])[:100]}
    return {'id':r.id,'name':r.name,'scope':r.scope,'scope_code':r.scope_code,'state':r.state,'active':r.active,'package':r.package,
            'revision':r.revision,'note':r.note,'proof':proof,'created_at':r.created_at,'published_at':r.published_at}

@router.get('/rules')
def rules(ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER')
    out=[]
    visible_snapshots=set(db.scalars(select(Snapshot.id).where(Snapshot.warehouse.in_(user.warehouses))))
    for r in db.scalars(select(Rule).order_by(Rule.created_at.desc())):
        try:
            rule_access(db,user,r.id)
            out.append(rule_json(r,bool(r.proof and r.proof['snapshot_id'] in visible_snapshots)))
        except HTTPException:continue
    active={(r['scope'],r['scope_code']):r for r in out if r['active'] and r['state']=='PUBLISHED'}
    coverage={}
    for w in db.scalars(select(Warehouse).where(Warehouse.code.in_(user.warehouses))):
        current=next((active[key] for key in rule_scopes(w) if key in active),None)
        coverage[w.code]=current['id'] if current else None
    return {'items':out,'labels':PARAM_LABELS,'flags':FLAG_LABELS,'coverage':coverage,'v2_defaults':DELAY_DEFAULTS,'v3_defaults':TURNOVER_DEFAULTS}

@router.post('/rules')
def clone_rule(data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER')
    def do():
        source_id=data.get('source_id')
        svc.demand(isinstance(source_id,str) and source_id.strip(),'请选择基础标准')
        source=rule_access(db,user,source_id)
        if 'source_revision' in data:
            svc.demand(type(data['source_revision']) is int and source.revision==data['source_revision'],
                       '基础标准已更新，请重新选择',409)
        # Old clients can specify a warehouse by code alone. With neither field,
        # inherit the complete scope of the source.
        kind=data.get('scope','WAREHOUSE' if 'scope_code' in data else source.scope)
        code=data.get('scope_code',source.scope_code if kind==source.scope else None)
        svc.demand(kind in ('WAREHOUSE','MARKET','DEFAULT'),'请选择规则适用范围')
        if kind!='DEFAULT':
            svc.demand(isinstance(code,str) and code.strip(),'请选择具体的适用范围')
        if kind=='WAREHOUSE':scope(user,code)
        elif kind=='MARKET':svc.demand(bool(db.scalar(select(Warehouse).where(Warehouse.code.in_(user.warehouses),Warehouse.market==code))),'没有该市场权限',403)
        else:
            svc.demand(code in (None,'',EUROPE,LEGACY_DEFAULT),'请选择欧洲通用范围')
            allowed=db.scalars(select(Warehouse).where(Warehouse.code.in_(user.warehouses)))
            svc.demand(any(applies_to('DEFAULT', EUROPE, w) for w in allowed),'没有欧洲市场的规则权限',403)
            code=EUROPE
        editable_scope(db,user,kind,code)
        source_model=source.package.get('model','0804')
        model=data.get('model',source_model)
        allowed = ('0804', MODEL_V2, MODEL_V3)
        svc.demand(model in allowed[allowed.index(source_model):], '请选择基础标准的模型或更新的版本')
        if 'package' in data:
            package=data['package']
            errors=validate_package(package)
            svc.demand(not errors,{'message':'参数检查未通过','issues':errors})
            svc.demand(package.get('model','0804')==model,'自定义参数与所选审核模型不一致')
        else:
            package=deepcopy(source.package)
            if model != source_model:
                package = upgrade_to_v3(package) if model == MODEL_V3 else upgrade_to_v2(package)
            if package.get('master_data') and (kind!='WAREHOUSE' or code!=package['master_data']['warehouse']):
                package.pop('master_data')
        if model == MODEL_V3:
            package = upgrade_to_v3(package)
        check_master_scope(package,kind,code)
        name=data.get('name',(source.name+' · 新版本')[:100])
        note=data.get('note','')
        svc.demand(isinstance(name,str) and 0<len(name.strip())<=100,'标准名称需为 1 至 100 个字符')
        svc.demand(isinstance(note,str) and len(note)<=2000,'修改说明最长 2000 字')
        r=Rule(id=uid(),name=name.strip(),scope=kind,scope_code=code,package=package,creator=user.id,note=note.strip())
        db.add(r)
        audit(db,user,'创建规则草稿',rule_id=r.id,source=source.id,source_revision=source.revision,hash=fingerprint(package))
        db.flush();return rule_json(r)
    return once(db,user,request,data,do)

@router.patch('/rules/{rule_id}')
def update_rule(rule_id:str,data:dict,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER');r=rule_access(db,user,rule_id)
    svc.demand(r.state=='DRAFT','已发布规则不可修改，请复制为新版本',409)
    svc.demand(r.revision==data.get('revision'),'规则已更新，请刷新',409)
    editable_scope(db,user,r.scope,r.scope_code)
    package=data.get('package');svc.demand(isinstance(package,dict),'规则参数格式有误')
    errors=validate_package(package);svc.demand(not errors,{'message':'参数检查未通过','issues':errors})
    if package.get('model') == MODEL_V3:
        package = upgrade_to_v3(package)
    check_master_scope(package,r.scope,r.scope_code)
    r.package=deepcopy(package);r.note=str(data.get('note',''))[:2000];r.proof=None
    audit(db,user,'修改规则草稿',rule_id=r.id,hash=fingerprint(package));db.flush();return rule_json(r)

@router.post('/rules/{rule_id}/dry-run')
def dry_run(rule_id:str,data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER');r=rule_access(db,user,rule_id)
    def do():
        svc.demand(r.state=='DRAFT','请对草稿规则进行试算')
        svc.demand(data.get('revision')==r.revision,'规则已更新，请刷新',409)
        snap=db.get(Snapshot,data.get('snapshot_id'));svc.demand(snap is not None,'请选择测试快照');scope(user,snap.warehouse)
        warehouse=db.get(Warehouse,snap.warehouse)
        if r.scope=='DEFAULT' and r.scope_code==LEGACY_DEFAULT:
            r.scope_code=EUROPE
        editable_scope(db,user,r.scope,r.scope_code)
        svc.demand(applies_to(r.scope,r.scope_code,warehouse),'试算快照不属于此规则的适用范围')
        errors=validate_package(r.package);svc.demand(not errors,{'message':'参数检查未通过','issues':errors})
        baseline=svc.active_rule(db,snap.warehouse,required=False);changes=[];new_errors=[]
        def outcome(result,inp):
            values=effective_input({'input':inp,'result':result})
            return {**{key:values.get(key) for key in ('replacement_rate','replacement_target','sales_target')},
                    'lower':result['lower'],'upper':result['upper'],'status':result['quantity_status'],
                    'review_mode':result['review_mode'],'flags':result['manual_flags'],'data_status':result['data_status'],
                    'future_qty':result['future_qty'], 'turnover_warning':result.get('turnover_warning'),
                    'delay':result.get('delay_replenishment') is True}
        for inp in snap.items:
            before=outcome(calculate(inp,baseline.package),inp) if baseline else {}
            b=calculate(inp,r.package);after=outcome(b,inp)
            new_error=b['data_status']=='ERROR' and before.get('data_status')!='ERROR'
            if new_error:new_errors.append(inp['material_code'])
            if before!=after:
                row={'material_code':inp['material_code'],'material_name':inp.get('material_name'),'before':before,'after':after}
                if new_error:
                    row['new_error_messages']=[issue['message'] for issue in b['errors']]
                changes.append(row)
        r.proof={'package_hash':fingerprint(r.package),'snapshot_id':snap.id,'snapshot_name':snap.name,'baseline_rule_id':baseline.id if baseline else None,'baseline_name':baseline.name if baseline else '首次发布','rows':len(snap.items),'changed':len(changes),'changes':changes,'new_errors':new_errors,'at':now()}
        audit(db,user,'规则试算',snap.warehouse,rule_id=r.id,changed=len(changes),new_errors=len(new_errors));db.flush();return rule_json(r)
    return once(db,user,request,data,do)

@router.get('/rules/{rule_id}/trial-impacts')
def trial_impacts(rule_id:str,q:str='',page:int=Query(1,ge=1),at:str='',errors_only:bool=False,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER')
    rule=rule_access(db,user,rule_id);proof=rule.proof
    svc.demand(proof,'尚无试算记录',404)
    warehouse=db.scalar(select(Snapshot.warehouse).where(Snapshot.id==proof['snapshot_id']))
    scope(user,warehouse)
    svc.demand(not at or proof['at']==at,'试算记录已更新，请刷新',409)
    recorded=proof.get('changes',[])
    rows=recorded
    if errors_only:
        by_code={row['material_code']:row for row in recorded}
        rows=[by_code.get(code,{'material_code':code,'before':{},'after':{}}) for code in proof['new_errors']]
    query=q.strip().casefold()
    matches=[row for row in rows if query in (row['material_code']+' '+(row.get('material_name') or '')).casefold()] if query else rows
    size=20
    return {'items':matches[(page-1)*size:page*size],'total':len(matches),'recorded':len(recorded),'changed':proof['changed'],'page_size':size}

@router.post('/rules/{rule_id}/publish')
def publish_rule(rule_id:str,data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER');r=rule_access(db,user,rule_id)
    def do():
        svc.demand(r.state=='DRAFT','此规则已发布',409);svc.demand(r.revision==data.get('revision'),'规则内容已变更，请刷新',409)
        svc.demand(r.proof and r.proof['package_hash']==fingerprint(r.package) and not r.proof['new_errors'],'请先完成试算并解决新增数据或区间错误')
        svc.demand(str(data.get('reason') or '').strip(),'请填写发布说明')
        affected=db.scalars(select(Warehouse)).all()
        svc.demand(r.scope!='DEFAULT' or r.scope_code==EUROPE,'请按欧洲适用范围重新试算',409)
        codes={w.code for w in affected if applies_to(r.scope,r.scope_code,w)}
        svc.demand(codes<=set(user.warehouses),'没有全部受影响仓库的规则发布权限',403)
        # Serialize overlapping publications on the warehouse rows, including first publication.
        list(db.scalars(select(Warehouse).where(Warehouse.code.in_(codes)).order_by(Warehouse.code).with_for_update()))
        trial_snapshot=db.get(Snapshot,r.proof['snapshot_id'])
        baseline=svc.active_rule(db,trial_snapshot.warehouse,required=False)
        svc.demand(r.proof.get('baseline_rule_id')==(baseline.id if baseline else None),'试算后现行规则已更新，请重新试算',409)
        for old in db.scalars(select(Rule).where(Rule.scope==r.scope,Rule.scope_code.in_(superseded_codes(r.scope,r.scope_code,affected)),Rule.active.is_(True)).with_for_update()):old.active=False
        db.flush()
        r.state='PUBLISHED';r.active=True;r.published_at=now();r.publisher=user.id;r.note=data['reason']
        audit(db,user,'发布规则',rule_id=r.id,scope=r.scope,scope_code=r.scope_code,reason=r.note);db.flush();return rule_json(r)
    return once(db,user,request,data,do)

@router.get('/users')
def users(ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'ADMIN')
    accounts=db.scalars(select(User).options(selectinload(User.avatar)).order_by(User.created_at))
    return [public_user(u) for u in accounts if set(u.warehouses)<=set(user.warehouses)]

@router.post('/users')
def create_user(data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'ADMIN')
    def do():
        validate_user(data,user)
        svc.demand(data.get('username') and data.get('name'),'请填写账号和姓名')
        u=add_user(db,user,data)
        db.flush()
        return public_user(u)
    return once(db,user,request,data,do)

def add_user(db,admin,data):
    password=data.get('password')
    svc.demand(valid_password(password),'初始密码需为 6–200 位')
    account=User(id=uid(),username=data['username'],name=data['name'],roles=data['roles'],email=account_email(data.get('email')),
                 warehouses=data['warehouses'],password_hash=hasher.hash(password))
    db.add(account)
    audit(db,admin,'创建用户',target=account.id,roles=account.roles,warehouses=account.warehouses)
    return account

def account_email(value):
    try:
        return normalize_email(value)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None

@router.post('/users/bulk/preview')
def preview_users(data:Any=Body(...),ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'ADMIN')
    table=data.get('table') if isinstance(data,dict) else None
    preview,_=inspect_accounts(db,user,table)
    return {'rows':preview}

@router.post('/users/bulk')
def create_users(request:Request,data:Any=Body(...),ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'ADMIN')
    table=data.get('table') if isinstance(data,dict) else None
    svc.demand(isinstance(table,str) and len(table)<=256_000,'请提供有效的账号表')
    def do():
        preview,accounts=inspect_accounts(db,user,table)
        svc.demand(len(accounts)==len(preview),{'message':'请核对标记行后重新提交','rows':preview})
        for account in accounts:
            add_user(db,user,account)
        db.flush()
        return {'created':len(accounts)}
    # The random request key salts the stored digest, which covers the entire import including passwords.
    return once(db,user,request,{'table':table,'nonce':request.headers.get('Idempotency-Key')},do)

def validate_user(data,user):
    roles=data.get('roles')
    svc.demand(isinstance(roles,list) and len(roles)==1 and isinstance(roles[0],str) and roles[0] in ROLE_NAMES,
               '请选择一个角色：计划员、复审员或管理员')
    svc.demand(isinstance(data.get('warehouses'),list) and set(data['warehouses'])<=set(user.warehouses),'不能授予当前管理范围以外的仓库权限',403)

@router.patch('/users/{user_id}')
def edit_user(user_id:str,data:dict,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'ADMIN');target=db.get(User,user_id);svc.demand(target is not None,'账号不存在',404)
    svc.demand(set(target.warehouses)<=set(user.warehouses),'不在当前管理范围',403)
    roles=data.get('roles',target.roles)
    warehouses=data.get('warehouses',target.warehouses)
    if 'roles' in data or 'warehouses' in data:
        validate_user({'roles':roles,'warehouses':warehouses},user)
    active=bool(data.get('active',target.active))
    if target.id==user.id:
        svc.demand(active and 'ADMIN' in roles,'不能停用自己的管理权限')
    if 'email' in data:
        email=account_email(data['email'])
        if email!=target.email:
            target.email=email
            refresh_recipient_email(db,target)
            audit(db,user,'修改通知邮箱',target=target.id)
    if data.get('password') or set(target.roles)!=set(roles) or set(target.warehouses)!=set(warehouses) or target.active!=active:
        target.roles=roles;target.warehouses=warehouses;target.active=active
        if data.get('password'):password_change(db,target,data['password'])
        db.execute(delete(LoginSession).where(LoginSession.user_id==target.id))
        audit(db,user,'修改用户授权',target=target.id,roles=target.roles,warehouses=target.warehouses,active=target.active)
    return public_user(target)

@router.post('/password')
def change_password(data:dict,ctx=Depends(context,scope="function")):
    db,user=ctx
    from argon2.exceptions import VerificationError
    current=data.get('current_password')
    try:valid=isinstance(current,str) and hasher.verify(user.password_hash,current)
    except VerificationError:valid=False
    svc.demand(valid,'当前密码不正确',403)
    new_password=data.get('password')
    svc.demand(new_password!=user.username,'新密码不能与登录账号相同')
    svc.demand(new_password!=current,'新密码与当前密码相同')
    password_change(db,user,new_password)
    audit(db,user,'修改密码')
    return {'ok':True}
