import mimetypes
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import os
import time
import uuid
from fastapi import FastAPI, Depends, Request, Response, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete, text, func
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import IntegrityError
from .db import *
from .auth import login, public_user, authenticate, hash_token, role, scope, password_change
from .personas import SOURCE as AVATAR_SOURCE, REVISION as AVATAR_REVISION, PresetChoice, CustomChoice
from .api_common import context, once
from .roles import has_role
from .demo import seed_demo
from .jobs import start_workers, FILES
from .governance import apply_governance
from . import services as svc
from .table_query import query_items, table_item, COLUMNS
from .adapters import MAX_ROWS
from .exceptions import approval_status, confirmation
from .settings import BASE_PATH, API_PREFIX, DEPLOY_ENV
from .health import readiness, UI_DIR
from .markets import EUROPE, MARKET_NAMES, market_key

DEMO=os.environ.get('PLAN_REVIEW_DEMO','0')=='1'
if DEMO and DEPLOY_ENV!='local':
    raise RuntimeError('部署环境不允许载入测试账号或样例数据')
@asynccontextmanager
async def lifespan(app):
    init_db()
    if DEMO:
        with transaction() as db:seed_demo(db)
    workers=start_workers() if os.environ.get('PLAN_REVIEW_WORKER','1')=='1' else None
    yield
    if workers:
        workers[0].set()
        for t in workers[1]:t.join(timeout=2)

app=FastAPI(title='计划审核',version='2.3.0',lifespan=lifespan,docs_url=BASE_PATH+'/api/docs' if DEPLOY_ENV=='local' else None,openapi_url=BASE_PATH+'/api/openapi.json',redoc_url=None)
PREFIX=API_PREFIX

@app.middleware('http')
async def guards(request,call_next):
    rid=uuid.uuid4().hex[:12]
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc!=request.headers.get('host'):
                return JSONResponse({'detail':'不允许跨站请求'},403)
    length=request.headers.get('content-length')
    if length:
        if not length.isdigit():return JSONResponse({'detail':'请求长度无效'},400)
        if int(length)>21*1024*1024:return JSONResponse({'detail':'请求超过文件大小限制'},413)
    token=REQUEST_ID.set(rid)
    try:
        response=await call_next(request)
    except Exception as exc:
        import logging
        logging.getLogger('uvicorn.error').error('request=%s method=%s path=%s failure=%s',rid,request.method,request.url.path,type(exc).__name__)
        response=JSONResponse({'detail':'服务处理失败，请联系管理员并提供请求编号 '+rid},500)
    finally:REQUEST_ID.reset(token)
    response.headers['X-Request-ID']=rid
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    if '/api/' in request.url.path:response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(StaleDataError)
async def stale(request,exc):return JSONResponse({'detail':'内容已被其他操作更新，请刷新后重试'},409)
@app.exception_handler(IntegrityError)
async def conflict(request,exc):return JSONResponse({'detail':'该记录或操作已存在，请刷新后核对'},409)
@app.exception_handler(HTTPException)
async def business_error(request,exc):
    import logging
    detail=exc.detail
    reason=detail if isinstance(detail,str) else detail.get('message','业务校验未通过') if isinstance(detail,dict) else '请求参数校验失败'
    logging.getLogger('uvicorn.error').warning('request=%s path=%s status=%s reason=%s',REQUEST_ID.get(),request.url.path,exc.status_code,str(reason)[:240])
    return JSONResponse({'detail':detail},status_code=exc.status_code,headers=exc.headers)

@app.get(PREFIX+'/health')
def health():
    ready=readiness()
    return JSONResponse({'status':'ok' if ready else 'not_ready','app':'plan-review','version':'2.3.0','demo':DEMO,'database':engine.dialect.name},status_code=200 if ready else 503)

@app.get('/health/live')
def health_live():return {'status':'ok','app':'plan-review'}

@app.get('/health/ready')
def health_ready():
    ready=readiness()
    return JSONResponse({'status':'ok' if ready else 'not_ready','app':'plan-review'},status_code=200 if ready else 503)

@app.get(PREFIX+'/session-state')
def session_state(request:Request):
    with transaction() as db:
        try:user,session=authenticate(db,request)
        except HTTPException as exc:
            if exc.status_code!=401:raise
            return {'user':None,'csrf':'','demo':DEMO}
        return {'user':public_user(user),'csrf':session.csrf,'demo':DEMO}

class LoginBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=200)
attempts=defaultdict(list)

@app.post(PREFIX+'/sessions')
def sessions(body:LoginBody,request:Request,response:Response):
    key=(request.client.host if request.client else '',body.username)
    attempts[key]=[t for t in attempts[key] if t>time.time()-600]
    if len(attempts[key])>=8:raise HTTPException(429,'登录尝试过多，请十分钟后再试')
    attempts[key].append(time.time())
    with transaction() as db:
        user,token,csrf=login(db,body.username,body.password)
        audit(db,user,'登录')
        desktop_http=(DEPLOY_ENV=='local' and os.environ.get('PLAN_REVIEW_DESKTOP_LOOPBACK')=='1'
                      and request.url.scheme=='http' and request.client and request.client.host in ('127.0.0.1','::1'))
        response.set_cookie('plan_session',token,httponly=True,samesite='strict',secure=not (DEMO or desktop_http),max_age=28800,path=BASE_PATH)
        attempts.pop(key,None)
        return {'user':public_user(user),'csrf':csrf}

@app.get(PREFIX+'/me')
def me(request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;_,session=authenticate(db,request)
    return {'user':public_user(user),'csrf':session.csrf,'demo':DEMO}

@app.patch(PREFIX+'/profile/avatar')
def update_avatar(choice:PresetChoice|CustomChoice,ctx=Depends(context,scope="function")):
    db,user=ctx
    if isinstance(choice,PresetChoice) and choice.avatar_preset=='blank':
        db.execute(delete(UserAvatar).where(UserAvatar.user_id==user.id))
        db.expire(user,['avatar'])
        return public_user(user)
    if isinstance(choice,CustomChoice):
        preset,config='plan',choice.avatar_config.model_dump()
    else:
        preset,config=choice.avatar_preset,None
    values={'preset':preset,'source':AVATAR_SOURCE,'revision':AVATAR_REVISION,'config':config}
    # A single upsert keeps simultaneous first saves from creating duplicate preferences.
    if db.get_bind().dialect.name=='mysql':
        statement=mysql_insert(UserAvatar).values(user_id=user.id,**values).on_duplicate_key_update(**values)
    else:
        statement=sqlite_insert(UserAvatar).values(user_id=user.id,**values).on_conflict_do_update(
            index_elements=[UserAvatar.user_id],set_=values)
    db.execute(statement)
    return public_user(user)

@app.delete(PREFIX+'/sessions/current')
def logout(request:Request,response:Response,ctx=Depends(context,scope="function")):
    db,user=ctx;db.execute(delete(LoginSession).where(LoginSession.token_hash==hash_token(request.cookies.get('plan_session',''))))
    response.delete_cookie('plan_session',path=BASE_PATH);return {'ok':True}

@app.get(PREFIX+'/warehouses')
def warehouses(ctx=Depends(context,scope="function")):
    db,user=ctx
    allowed = db.scalars(select(Warehouse).where(Warehouse.code.in_(user.warehouses)).order_by(Warehouse.code)).all()
    order = {code: index for index, code in enumerate(MARKET_NAMES)}
    return [{'code': w.code, 'name': w.name, 'market': w.market,
             'market_name': MARKET_NAMES.get(market_key(w.market), w.market),
             'region': EUROPE if market_key(w.market) in MARKET_NAMES else None}
            for w in sorted(allowed, key=lambda w: order.get(market_key(w.market), len(order)))]

@app.get(PREFIX+'/batches')
def batches(ctx=Depends(context,scope="function")):
    db,user=ctx
    return [svc.batch_json(db,b) for b in db.scalars(select(Batch).where(svc.visible_batch_filter(db,user)).order_by(Batch.updated_at.desc()))]

@app.post(PREFIX+'/batches')
def create_batch(data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx
    return once(db,user,request,data,lambda:svc.batch_json(db,svc.new_batch(db,user,data)),
                on_replay=lambda:scope(user,data.get('warehouse')))

@app.get(PREFIX+'/batches/{batch_id}')
def get_batch(batch_id:str,include_events:bool=True,ctx=Depends(context,scope="function")):
    db,user=ctx;batch=svc.batch_access(db,user,batch_id)
    result=svc.batch_json(db,batch)
    versions=select(Version.id,Version.seq,Version.state,Version.created_at,Version.submitted_at,Version.finalized_at)
    result['versions']=[dict(row) for row in db.execute(versions.where(Version.batch_id==batch.id).order_by(Version.seq.desc())).mappings()]
    events=select(Audit,User.name).outerjoin(User,User.id==Audit.user_id).where(Audit.batch_id==batch.id).order_by(Audit.created_at.desc(),Audit.id.desc())
    if not include_events:
        events=events.where(Audit.action=='退回修改').limit(1)
    result['events']=[{'action':a.action,'detail':a.detail,'at':a.created_at,'actor':actor or '系统','version_id':a.version_id}
                      for a,actor in db.execute(events)] if include_events or batch.state=='RETURNED' else []
    return result

@app.get(PREFIX+'/versions/{version_id}/activity')
def version_activity(version_id:str,page:int=1,ctx=Depends(context,scope="function")):
    db,user=ctx
    batch,version=svc.version_access(db,user,version_id,lock=False)
    scope_filter=(Audit.batch_id==batch.id, Audit.version_id==version.id)
    total=db.scalar(select(func.count(Audit.id)).where(*scope_filter)) or 0
    size=12
    page=min(max(page,1),max(1,(total+size-1)//size))
    events=(select(Audit,User.name).outerjoin(User,User.id==Audit.user_id).where(*scope_filter)
            .order_by(Audit.created_at.desc(),Audit.id.desc()).offset((page-1)*size).limit(size))
    items=[]
    for event,actor in db.execute(events):
        detail=event.detail or {}
        record={key:detail[key] for key in ('operation','reason','decision','rows','count','outcome','approved','rejected',
                'reviewed_approved','reviewed_rejected','reviewed_exception','unreviewed','batch_approved','exception_approved',
                'warning_rows','filtered','source_number','source_seq','material_codes','reviewer_name','from_reviewer_name') if key in detail}
        if 'changes' in detail:record['count']=len(detail['changes'])
        if 'ids' in detail:record['selected_count']=len(detail['ids'])
        if detail.get('override'):record['reason']=detail['override'].get('reason')
        items.append({'id':event.id,'action':event.action,'at':event.created_at,'actor':actor or '系统','detail':record})
    return {'items':items,'total':total,'page':page,'page_size':size}

@app.get(PREFIX+'/versions/{version_id}')
def get_version(version_id:str,q:str='',filter:str='all',page:int=1,page_size:int=30,column_filters:str='{}',sort_key:str='',sort_direction:str='asc',include_batch_context:bool=False,table_view:bool=False,ctx=Depends(context,scope="function")):
    db,user=ctx;batch,ver=svc.version_access(db,user,version_id,lock=False)
    facets={key:set() for key,_,kind in COLUMNS if kind=='enum'}
    rows=query_items(ver.items,q,filter,column_filters,sort_key,sort_direction,reviewing=has_role(user,'REVIEWER') and ver.state in ('SUBMITTED','IN_REVIEW'),version_state=ver.state,facets=facets)
    page_size=max(1,min(page_size,MAX_ROWS));page=max(page,1)
    rule=db.get(Rule,ver.rule_id);snap=db.get(Snapshot,ver.snapshot_id) if ver.snapshot_id else None;latest_rule=svc.active_rule(db,batch.warehouse)
    return {'id':ver.id,'seq':ver.seq,'revision':ver.revision,'state':ver.state,'batch_id':batch.id,'owner':batch.owner,
            **svc.assignment(db,batch,ver),
            **svc.plan_undo.hints(db,user,batch,ver),
            **({'batch_current_id':batch.current_id,'batch_state':batch.state,'batch_updated_at':batch.updated_at} if include_batch_context else {}),
            'items':[table_item(r,ver.state,table_view,rule.package) for r in rows[(page-1)*page_size:page*page_size]],'total':len(rows),'summary':svc.summary(ver.items),
            'columns':[{'key':k,'label':label,'type':t} for k,label,t in COLUMNS],'column_options':{key:sorted(values) for key,values in facets.items()},
            'page':page,'page_size':page_size,'snapshot':{'id':snap.id,'name':snap.name,'as_of':snap.as_of,'basis':snap.basis,'net_mode':snap.net_mode} if snap else None,
            'rule':{'id':rule.id,'name':rule.name,'published_at':rule.published_at,'params':rule.package['params'],'model':rule.package.get('model','0804'),'v3_revision':rule.package.get('v3_revision'),'has_material_basis':bool(rule.package.get('master_data') or rule.package.get('target_policy'))},
            'latest_rule_id':latest_rule.id,'latest_rule_name':latest_rule.name}

def filter_items(items,q='',filter='all'):
    return query_items(items,q,filter)

@app.get(PREFIX+'/versions/{version_id}/material-basis')
def material_basis(version_id:str,code:str,ctx=Depends(context,scope="function")):
    db,user=ctx
    _,version=svc.version_access(db,user,version_id,lock=False)
    svc.demand(0<len(code.strip())<=120,'请输入有效物料号')
    _,basis=apply_governance({'material_code':code.strip()},db.get(Rule,version.rule_id).package)
    return {'code':code.strip(),'basis':basis}

@app.get(PREFIX+'/versions/{version_id}/items/{row_id}')
def get_version_item(version_id:str,row_id:str,ctx=Depends(context,scope="function")):
    db,user=ctx
    _,version=svc.version_access(db,user,version_id,lock=False)
    row=next((item for item in version.items if item['id']==row_id),None)
    svc.demand(row is not None,'本版本没有这条计划行',404)
    return table_item(row,version.state,package=db.get(Rule,version.rule_id).package)

@app.get(PREFIX+'/versions/{version_id}/selection')
def select_rows(version_id:str,q:str='',filter:str='all',column_filters:str='{}',sort_key:str='',sort_direction:str='asc',ctx=Depends(context,scope="function")):
    db,user=ctx;batch,ver=svc.version_access(db,user,version_id,lock=False)
    return {'ids':[r['id'] for r in query_items(ver.items,q,filter,column_filters,sort_key,sort_direction,reviewing=has_role(user,'REVIEWER') and ver.state in ('SUBMITTED','IN_REVIEW'),version_state=ver.state)]}

@app.post(PREFIX+'/versions/{version_id}/issue-preview')
def preview_draft_issues(version_id:str,data:dict,ctx=Depends(context,scope="function")):
    from .plan_issues import issue_preview
    db,user=ctx
    batch,version=svc.version_access(db,user,version_id,lock=False)
    svc.editable(user,batch,version,data.get('revision'))
    return issue_preview(version,db.get(Rule,version.rule_id),data.get('edits',{}),data.get('group','all'),data.get('page',1))

@app.get(PREFIX+'/versions/{version_id}/confirmation')
def get_confirmation(version_id:str,stage:str='submit',all:bool=False,ctx=Depends(context,scope="function")):
    db,user=ctx;batch,ver=svc.version_access(db,user,version_id,lock=False)
    svc.demand(stage in ('submit','finalize'),'确认阶段无效')
    if stage=='submit':svc.editable(user,batch,ver,ver.revision)
    else:
        role(user,'REVIEWER');svc.demand(user.id!=batch.owner,'不能审批自己的计划',403)
        svc.demand(ver.state in ('SUBMITTED','IN_REVIEW'),'当前版本不在复审中',409)
    rows=ver.items
    if stage=='submit':
        rule=db.get(Rule,ver.rule_id)
        svc.check_submission_inputs(rows, rule.package)
        rows=[{**r,'result':svc.plan_result(r['input'],rule,ver.snapshot_id)} for r in rows]
    return confirmation(rows,stage,ver.revision,all_rows=all)

@app.patch(PREFIX+'/versions/{version_id}/items')
def edit_rows(version_id:str,data:dict,ctx=Depends(context,scope="function")):
    return svc.patch_items(*ctx,version_id,data)

@app.post(PREFIX+'/versions/{version_id}/review-summary')
def review_summary(version_id:str,data:dict,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER');batch,ver=svc.version_access(db,user,version_id,lock=False)
    ids=set(data.get('ids',[]));svc.demand(ids and ids<={r['id'] for r in ver.items},'请选择当前版本的记录')
    selected=[r for r in ver.items if r['id'] in ids]
    rows=[r for r in selected if not r.get('decision')] if data.get('only_pending') is True else selected
    exceptions=sum(approval_status(r['result'])=='EXCEPTION_APPROVED' for r in rows)
    summary={'flags':sorted({flag for r in rows for flag in r['result']['manual_flags']}),'exception':bool(exceptions),
             'exception_count':exceptions,'count':len(rows)}
    if data.get('only_pending') is True:
        summary.update(preserved=len(selected)-len(rows), errors=sum(r['result']['data_status']=='ERROR' for r in rows),
                       delayed=sum(r['result'].get('delay_replenishment') is True for r in rows))
    return summary

@app.get(PREFIX+'/versions/{version_id}/reviewers')
def review_candidates(version_id:str,ctx=Depends(context,scope="function")):
    db,user=ctx
    role(user,'REVIEWER')
    batch,ver=svc.version_access(db,user,version_id,lock=False)
    svc.demand(ver.state in svc.ACTIVE_REVIEW_STATES and batch.current_id==ver.id,'当前版本不在复审中',409)
    svc.demand(svc.eligible_reviewer(user,batch),'没有本计划的复审权限',403)
    candidates=db.scalars(select(User).where(User.active.is_(True)).order_by(User.name,User.username))
    return [{'id':u.id,'name':u.name,'username':u.username} for u in candidates
            if u.id!=ver.reviewer_id and svc.eligible_reviewer(u,batch)]

@app.post(PREFIX+'/versions/{version_id}/items')
def append_rows(version_id:str,data:dict,ctx=Depends(context,scope="function")):
    return svc.add_items(*ctx,version_id,data)
@app.delete(PREFIX+'/versions/{version_id}/items')
def remove_rows(version_id:str,data:dict,ctx=Depends(context,scope="function")):
    return svc.delete_items(*ctx,version_id,data)
@app.post(PREFIX+'/versions/{version_id}/basis')
def change_basis(version_id:str,data:dict,ctx=Depends(context,scope="function")):
    return svc.switch_basis(*ctx,version_id,data)

@app.post(PREFIX+'/versions/{version_id}/snapshot-preview')
def preview_snapshot(version_id:str,data:dict,ctx=Depends(context,scope="function")):
    return svc.preview_basis(*ctx,version_id,data)

def action_route(action):
    def endpoint(version_id:str,data:dict,request:Request,ctx=Depends(context,scope="function")):
        db,user=ctx
        def perform():
            result = action(db,user,version_id,data)
            if action in (svc.submit,svc.claim,svc.transfer,svc.finalize,svc.return_batch):
                svc.plan_undo.forget(db,version_id)
            return result
        return once(db,user,request,data,perform,replay_conflicts=action in (svc.plan_undo.undo,svc.plan_undo.redo),
                    on_replay=lambda:svc.version_access(db,user,version_id,lock=False))
    return endpoint
for name,fn in [('undo',svc.plan_undo.undo),('redo',svc.plan_undo.redo),('submit',svc.submit),('claim',svc.claim),('transfer',svc.transfer),('reviews',svc.review),('finalize',svc.finalize),('return',svc.return_batch)]:
    app.add_api_route(PREFIX+'/versions/{version_id}/'+name,action_route(fn),methods=['POST'])

@app.post(PREFIX+'/batches/{batch_id}/copy')
def copy_batch(batch_id:str,data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;old=svc.batch_access(db,user,batch_id)
    def do_copy():
        role(user,'PLANNER')
        _,v=svc.version_access(db,user,data.get('version_id',old.current_id))
        svc.demand(v.batch_id==old.id,'请选择本计划的来源版本')
        if 'revision' in data:svc.demand(data['revision']==v.revision,'来源计划已更新，请重新打开后复制',409)
        new=svc.new_batch(db,user,{'warehouse':old.warehouse,'snapshot_id':v.snapshot_id,'title':data.get('title',old.title[:115]+' · 副本'),'period':data.get('period',old.period)},
                          copied_from={'source_number':old.number,'source_seq':v.seq,'source_version_id':v.id})
        nv=db.get(Version,new.current_id)
        if 'rule_id' in data:svc.demand(nv.rule_id==data['rule_id'],'生效标准已更新，请刷新计划后重试',409)
        rule=db.get(Rule,nv.rule_id)
        rows=[]
        for old_row in v.items:
            inp=deepcopy(old_row['input'])
            rows.append({'id':uid(),'input':inp,'result':svc.plan_result(inp,rule,nv.snapshot_id),'decision':None})
        nv.items=rows;db.flush();return svc.batch_json(db,new)
    return once(db,user,request,data,do_copy)

@app.post(PREFIX+'/batches/{batch_id}/void')
def void_batch(batch_id:str,data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;batch=svc.batch_access(db,user,batch_id);ver=db.get(Version,batch.current_id)
    def do_void():
        svc.editable(user,batch,ver,data.get('revision'))
        reason=str(data.get('reason') or '').strip()
        svc.demand(len(reason)<=2000,'作废备注最多2000字')
        svc.plan_undo.forget(db,ver.id)
        batch.state='VOID';ver.state='VOID';batch.updated_at=now();audit(db,user,'作废计划',batch.warehouse,batch.id,ver.id,reason=reason)
        return {'state':'VOID'}
    return once(db,user,request,data,do_void)

@app.get(PREFIX+'/notifications')
def notifications(all:bool=False,ctx=Depends(context,scope="function")):
    from .notification_inbox import accessible, display_notice
    db,user=ctx
    query=select(Notification,Batch.state).join(Batch,Batch.id==Notification.batch_id).where(*accessible(db,user)).order_by(Notification.created_at.desc(),Notification.id.desc())
    return [{'id':n.id,'batch_id':n.batch_id,'text':display_notice(n.text,n.kind,state),'seen':n.seen,'at':n.created_at} for n,state in db.execute(query if all else query.limit(100))]

@app.get(PREFIX+'/notification-inbox')
def notification_inbox(tab:str='all',warehouse:str='',kind:str='',page:int=1,size:int=20,ctx=Depends(context,scope="function")):
    from .notification_inbox import inbox
    svc.demand(1<=size<=100,'通知页大小无效')
    return inbox(*ctx,tab,warehouse,kind,page,size)

@app.post(PREFIX+'/notification-inbox/seen')
def mark_filtered_notifications(data:dict,ctx=Depends(context,scope="function")):
    from .notification_inbox import mark_filtered
    return mark_filtered(*ctx,data.get('tab','all'),data.get('warehouse',''),data.get('kind',''),data.get('before'))

@app.post(PREFIX+'/notifications/{note_id}/seen')
def mark_seen(note_id:str,ctx=Depends(context,scope="function")):
    from .notification_inbox import mark
    return mark(*ctx,note_id)

@app.get(PREFIX+'/versions/{version_id}/diff')
def diff_versions(version_id:str,against:str,ctx=Depends(context,scope="function")):
    db,user=ctx;batch,v=svc.version_access(db,user,version_id,lock=False);other,old=svc.version_access(db,user,against,lock=False)
    svc.demand(batch.id==other.id,'只能比较同一批次的版本')
    from .comparison import compare_items
    changes=compare_items(old.items,v.items)
    return {**changes,'rule_changed':v.rule_id!=old.rule_id,'snapshot_changed':v.snapshot_id!=old.snapshot_id,
            'from_version':{'id':old.id,'seq':old.seq},'to_version':{'id':v.id,'seq':v.seq}}

from .routes_data import router as data_router
from .routes_rules import router as rules_router
from .usage import router as usage_router
from .mail_delivery import router as mail_router
app.include_router(data_router,prefix=PREFIX);app.include_router(rules_router,prefix=PREFIX)
app.include_router(usage_router,prefix=PREFIX)
app.include_router(mail_router,prefix=PREFIX)

@app.get('/')
@app.get(BASE_PATH)
def root(request:Request):
    query=request.scope.get('query_string',b'').decode('latin-1')
    return RedirectResponse(BASE_PATH+'/'+('?' + query if query else ''),status_code=307)
# Windows may register .svg as image/svg, which browsers reject with nosniff.
mimetypes.add_type('image/svg+xml', '.svg')
dist=UI_DIR
if (dist/'assets').exists():app.mount(BASE_PATH+'/assets',StaticFiles(directory=dist/'assets'),name='assets')
@app.get(BASE_PATH+'/favicon.svg')
def favicon():return FileResponse(dist/'favicon.svg',media_type='image/svg+xml')
@app.get(BASE_PATH+'/{path:path}')
def frontend(path:str):
    if path.startswith('api/'):raise HTTPException(404,'接口不存在')
    if not (dist/'index.html').exists():raise HTTPException(503,'前端尚未构建，请运行初始化脚本')
    return FileResponse(dist/'index.html',headers={'Cache-Control':'no-cache'})
