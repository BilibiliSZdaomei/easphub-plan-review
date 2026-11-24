from copy import deepcopy
from datetime import datetime
from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select
from .db import Batch, Version, Rule, Snapshot, User, Notification, NotificationEvent,Warehouse, audit, uid, now
from .auth import role, scope
from .rules import calculate, pending_plan_result, submission_issues, fingerprint, validate_package
from .rules import canonical_reason, REASON_LABELS
from .periods import period_info
from .exceptions import business_warnings, confirmation, warning_record
from .markets import rule_scopes

def demand(condition,message,status=422):
    if not condition: raise HTTPException(status,message)

def active_rule(db,warehouse,required=True):
    w=db.get(Warehouse,warehouse)
    demand(w is not None,'仓库不存在',404)
    for kind,code in rule_scopes(w):
        rule=db.scalar(select(Rule).where(Rule.active.is_(True),Rule.state=='PUBLISHED',Rule.scope==kind,Rule.scope_code==code))
        if rule: return rule
    if required:
        raise HTTPException(422,'该仓库尚未配置已发布审核标准')
    return None

def batch_access(db,user,batch_id):
    batch=db.get(Batch,batch_id)
    demand(batch is not None,'计划不存在',404)
    scope(user,batch.warehouse)
    return batch

def version_access(db,user,version_id,lock=True):
    query=select(Version).where(Version.id==version_id)
    version=db.scalar(query.with_for_update() if lock else query)
    demand(version is not None,'版本不存在',404)
    batch=batch_access(db,user,version.batch_id)
    return batch,version

def editable(user,batch,version,revision):
    role(user,'PLANNER')
    demand(batch.owner==user.id,'只有该计划创建人可以修改',403)
    demand(version.state=='DRAFT' and batch.current_id==version.id,'已提交版本不可修改，请在退回后的新草稿中处理',409)
    demand(revision==version.revision,'计划已被其他页面更新，请刷新后比较修改',409)

def summary(items):
    c=Counter({'total':len(items),'WITHIN':0,'BELOW':0,'ABOVE':0,'ERROR':0,'PENDING':0,'MANUAL':0,'EXEMPT':0,'attention':0,'delay':0,'unexplained':0,'reviewed':0,'air':0,'return_requested':0})
    for row in items:
        r=row['result']
        if r.get('basis_pending'): c['PENDING']+=1
        if r['data_status']=='ERROR': c['ERROR']+=1
        elif r['review_mode']=='AUTO': c[r['quantity_status']]+=1
        else: c[r['review_mode']]+=1
        if r.get('delay_replenishment'): c['delay']+=1
        if business_warnings(row): c['attention']+=1
        if submission_issues(row['input'],r): c['unexplained']+=1
        if row.get('decision'): c['reviewed']+=1
        if row.get('return_requested'): c['return_requested']+=1
        if 'AIR' in r['manual_flags']: c['air']+=1
    return dict(c)

def batch_json(db,batch):
    version=db.get(Version,batch.current_id)
    owner=db.get(User,batch.owner)
    warehouse=db.get(Warehouse,batch.warehouse)
    return {'id':batch.id,'number':batch.number,'title':batch.title,'warehouse':batch.warehouse,'warehouse_name':warehouse.name,
            'period':batch.period,'period_info':period_info(batch.period,strict=False),'owner':batch.owner,'owner_name':owner.name,'state':batch.state,'current_id':batch.current_id,
            'version':version.seq,'revision':version.revision,'summary':summary(version.items),'created_at':batch.created_at,'updated_at':batch.updated_at}

def notify(db,batch,text,reviewers=False):
    db.add(NotificationEvent(id=uid(),payload={'warehouse':batch.warehouse,'batch_id':batch.id,'owner':batch.owner,'text':text,'reviewers':reviewers}))

def new_batch(db,user,data,*,copied_from=None):
    role(user,'PLANNER'); warehouse=data.get('warehouse'); scope(user,warehouse)
    snapshot_id=data.get('snapshot_id')
    snapshot=None
    if snapshot_id is not None:
        snapshot=db.get(Snapshot,snapshot_id)
        demand(snapshot is not None and snapshot.warehouse==warehouse,'请选择本仓有效数据快照')
    title=str(data.get('title') or '').strip(); period=str(data.get('period') or '').strip()
    demand(bool(title) and len(title)<=120 and bool(period) and len(period)<=30,'请填写计划名称和周期')
    period_info(period)
    rule=active_rule(db,warehouse)
    batch=Batch(id=uid(),number='PR-'+datetime.now().strftime('%Y%m%d')+'-'+uid()[:6].upper(),title=title,warehouse=warehouse,period=period,owner=user.id)
    db.add(batch);db.flush()
    items=[]
    if snapshot is not None and data.get('use_snapshot_plan',False):
        items=[{'id':uid(),'input':deepcopy(i),'result':calculate(i,rule.package),'decision':None} for i in snapshot.items]
    ver=Version(id=uid(),batch_id=batch.id,seq=1,snapshot_id=snapshot_id,rule_id=rule.id,items=items)
    db.add(ver);db.flush();batch.current_id=ver.id
    audit(db,user,'复制为新计划' if copied_from else '新建计划',warehouse,batch.id,ver.id,title=title,**(copied_from or {}))
    warning_count=summary(items)['attention']
    if warning_count:notify(db,batch,f'{title} 有 {warning_count} 行审核提醒')
    return batch


PLAN_FIELDS = ('sea_plan_qty','air_plan_qty','reason','reason_code','air_reason')


def plan_sources(db, version):
    if version.snapshot_id is None:
        return None
    return {i['material_code']: i for i in db.get(Snapshot, version.snapshot_id).items}


def plan_input(plan, sources, *, replace_plan=False):
    code=plan.get('material_code')
    demand(isinstance(code,str) and bool(code.strip()),'请输入物料号')
    code=code.strip()
    if sources is None:
        inp={'material_code':code,'material_name':str(plan.get('material_name') or '').strip(),
             'sea_plan_qty':'0','air_plan_qty':'0'}
    else:
        demand(code in sources,'未在选定快照找到物料：'+code)
        inp=deepcopy(sources[code])
    inp.update({key:plan.get(key) for key in PLAN_FIELDS if replace_plan or key in plan})
    if 'reason_code' in inp:
        inp['reason_code'] = canonical_reason(inp['reason_code'])
    return inp


def plan_result(item,rule,snapshot_id):
    return pending_plan_result(item) if snapshot_id is None else calculate(item,rule.package)

def patch_items(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    rows=deepcopy(ver.items); by_id={r['id']:r for r in rows}; changes=data.get('changes',[])
    demand(isinstance(changes,list) and 0<len(changes)<=10000,'请选择要修改的计划行')
    allowed={'sea_plan_qty','air_plan_qty','reason','reason_code','air_reason'}
    for change in changes:
        row=by_id.get(change.get('id')); demand(row is not None,'计划行不存在',404)
        values=change.get('values',{})
        demand(set(values)<=allowed,'只能修改计划数量和说明；基础数据请更新快照')
        demand(all(len(str(v))<=2000 for v in values.values()),'说明文字过长')
        if 'reason_code' in values:
            values = {**values, 'reason_code': canonical_reason(values['reason_code'])}
        before={k:row['input'].get(k) for k in values};before_result=deepcopy(row['result'])
        row['input'].update(values);row['decision']=None;row.pop('submission_override',None)
        row['result']=plan_result(row['input'],db.get(Rule,ver.rule_id),ver.snapshot_id)
        row['adjustment']={'at':now(),'before':before,'after':deepcopy(values),'quantity_before':before_result['quantity_status'],'quantity_after':row['result']['quantity_status'],'review_reason':bool(row['input'].get('reason')) and any(k in values for k in ('sea_plan_qty','air_plan_qty'))}
    ver.items=rows; batch.updated_at=now()
    audit(db,user,'修改计划',batch.warehouse,batch.id,ver.id,changes=changes)
    db.flush();return {'revision':ver.revision,'summary':summary(rows)}

def add_items(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    sources=plan_sources(db,ver)
    codes={r['input']['material_code'] for r in ver.items};rows=deepcopy(ver.items)
    plans=data.get('items')
    demand(isinstance(plans,list) and plans and all(isinstance(i,dict) for i in plans),'请选择要添加的物料')
    demand(len(rows)+len(plans)<=10000,'单批最多10000行')
    rule=db.get(Rule,ver.rule_id)
    for plan in plans:
        inp=plan_input(plan,sources);code=inp['material_code']
        demand(code not in codes,'同一计划不能重复添加物料：'+code)
        rows.append({'id':uid(),'input':inp,'result':plan_result(inp,rule,ver.snapshot_id),'decision':None});codes.add(code)
    ver.items=rows;batch.updated_at=now();audit(db,user,'添加计划行',batch.warehouse,batch.id,ver.id,count=len(rows));db.flush()
    return {'revision':ver.revision,'summary':summary(rows)}

def delete_items(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    ids=set(data.get('ids',[])); demand(ids,'请选择计划行')
    ver.items=[r for r in ver.items if r['id'] not in ids];batch.updated_at=now()
    audit(db,user,'删除计划行',batch.warehouse,batch.id,ver.id,ids=list(ids));db.flush()
    return {'revision':ver.revision}

def submit(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    demand(bool(ver.items),'请先添加或导入计划')
    rows=deepcopy(ver.items)
    rule=db.get(Rule,ver.rule_id)
    demand(rule.state=='PUBLISHED','必须选择已发布审核标准')
    for row in rows:
        row['result']=plan_result(row['input'],rule,ver.snapshot_id)
        row.pop('submission_override',None)
    report=confirmation(rows,'submit',ver.revision,all_rows=True)
    at=now()
    record=warning_record(data,report,user,at)
    warnings={entry['id']:entry['issues'] for entry in report['rows']}
    for row in rows:
        if row['id'] in warnings:
            row['submission_override']={**record,'issues':warnings[row['id']]}
    ver.items=rows;ver.state='SUBMITTED';ver.submitted_at=at;batch.state='SUBMITTED';batch.updated_at=at
    audit(db,user,'提交复审',batch.warehouse,batch.id,ver.id,input_hash=fingerprint(rows),rule_id=ver.rule_id,
          snapshot_id=ver.snapshot_id,warning_rows=report['affected_count'],issue_hash=report['issue_hash'],reason=record['reason'])
    notify(db,batch,batch.title+' 已提交，等待复审',True);db.flush()
    return {'id':batch.id,'version_id':ver.id,'state':batch.state,'revision':ver.revision}

def review(db,user,version_id,data):
    role(user,'REVIEWER');batch,ver=version_access(db,user,version_id)
    demand(user.id!=batch.owner,'不能审批自己创建的计划',403)
    demand(ver.state in ('SUBMITTED','IN_REVIEW'),'当前版本不在复审中',409)
    demand(data.get('revision')==ver.revision,'复审内容已更新，请刷新后重试',409)
    ids=set(data.get('ids',[]));demand(ids,'请选择复审记录')
    demand(ids <= {r['id'] for r in ver.items},'所选记录不属于当前版本')
    action=data.get('decision','APPROVED');demand(action in ('APPROVED','EXCEPTION_APPROVED'),'无效审批动作')
    reason=str(data.get('reason') or '').strip()
    demand(len(reason)<=2000,'复审备注最多2000字')
    flags_input=data.get('ack_flags',[])
    demand(isinstance(flags_input,list) and all(isinstance(f,str) for f in flags_input),'关注项格式无效')
    ack=set(flags_input);air=data.get('air_confirmed') is True
    reason_code=canonical_reason(data.get('reason_code'))
    demand(not reason_code or (isinstance(reason_code,str) and reason_code in REASON_LABELS),'无效的复审原因类别')
    only_pending = len(ids)>1 or data.get('only_pending') is True
    rows=deepcopy(ver.items);processed=[];preserved=0
    for row in rows:
        if row['id'] not in ids: continue
        if only_pending and row.get('decision'):
            preserved+=1
            continue
        flags=set(row['result']['manual_flags'])
        row['decision']={'status':action,'reason':reason,'reason_code':reason_code,'reviewer_id':user.id,
                         'reviewer_name':user.name,'reviewed_at':now(),'ack_flags':sorted((flags-{'AIR'}) & ack),
                         'air_confirmed':'AIR' in flags and air}
        processed.append(row['id'])
    if processed:
        ver.items=rows;ver.state='IN_REVIEW';batch.state='IN_REVIEW';batch.updated_at=now()
        audit(db,user,'保存行复审',batch.warehouse,batch.id,ver.id,ids=processed,approved=len(processed),decision=action,reason=reason)
        db.flush()
    return {'count':len(processed),'preserved':preserved,'skipped':[],'revision':ver.revision,'summary':summary(rows)}

def finalize(db,user,version_id,data):
    role(user,'REVIEWER');batch,ver=version_access(db,user,version_id)
    demand(user.id!=batch.owner,'不能审批自己创建的计划',403)
    demand(ver.state in ('SUBMITTED','IN_REVIEW'),'当前版本不能完成终审',409)
    demand(data.get('revision')==ver.revision,'内容已更新，请刷新后重试',409)
    demand(bool(ver.items),'空白计划不能终审')
    report=confirmation(ver.items,'finalize',ver.revision)
    at=now()
    record=warning_record(data,report,user,at)
    if report['unreviewed']:
        rows=deepcopy(ver.items)
        for row in rows:
            if not row.get('decision'):
                row['decision']={'status':'BATCH_APPROVED','reviewer_id':user.id,'reviewer_name':user.name,
                                 'reviewed_at':at,'reason':record['reason'],'ack_flags':[],'air_confirmed':False}
        ver.items=rows
    ver.state='APPROVED';ver.finalized_at=at;batch.state='APPROVED';batch.updated_at=at
    audit(db,user,'完成终审',batch.warehouse,batch.id,ver.id,rows=len(ver.items),batch_approved=report['unreviewed'],
          warning_rows=report['affected_count'],issue_hash=report['issue_hash'],reason=record['reason'])
    notify(db,batch,batch.title+' 已通过终审');db.flush()
    return {'state':'APPROVED','revision':ver.revision}

def return_batch(db,user,version_id,data):
    role(user,'REVIEWER');batch,old=version_access(db,user,version_id)
    demand(user.id!=batch.owner,'不能处理自己提交的计划',403)
    demand(old.state in ('SUBMITTED','IN_REVIEW'),'只有待审计划可以退回',409)
    demand(data.get('revision')==old.revision,'内容已更新，请刷新',409)
    reason=str(data.get('reason') or '').strip();demand(reason,'请填写退回原因')
    requested=data.get('ids',[])
    demand(isinstance(requested,list) and all(isinstance(i,str) for i in requested),'请选择本版本物料')
    marked=set(requested)
    demand(marked<={row['id'] for row in old.items},'所选物料不属于本版本')
    codes=[row['input']['material_code'] for row in old.items if row['id'] in marked]
    old.state='RETURNED';rows=deepcopy(old.items)
    for row in rows:
        row['previous_decision']=row.get('decision');row['decision']=None;row.pop('submission_override',None)
        if row['id'] in marked:row['return_requested']=True
        else:row.pop('return_requested',None)
    ver=Version(id=uid(),batch_id=batch.id,seq=old.seq+1,snapshot_id=old.snapshot_id,rule_id=old.rule_id,items=rows)
    db.add(ver);db.flush();batch.current_id=ver.id;batch.state='RETURNED';batch.updated_at=now()
    audit(db,user,'退回修改',batch.warehouse,batch.id,old.id,reason=reason,new_version=ver.id,ids=sorted(marked),material_codes=codes)
    notify(db,batch,batch.title+' 已退回：'+reason)
    return {'state':'RETURNED','version_id':ver.id}

def basis_candidate(db,user,version_id,data,lock=False):
    """Prepare exactly the rows a basis change will save, without changing state."""
    batch,ver=version_access(db,user,version_id,lock=lock);editable(user,batch,ver,data.get('revision'))
    rule=db.get(Rule,data.get('rule_id',ver.rule_id))
    snapshot_id=data.get('snapshot_id',ver.snapshot_id)
    snapshot=db.get(Snapshot,snapshot_id) if snapshot_id else None
    demand(rule is not None and rule.state=='PUBLISHED','请选择已发布规则')
    allowed_rule=active_rule(db,batch.warehouse)
    demand(rule.id in (ver.rule_id,allowed_rule.id),'该规则没有绑定当前仓库')
    demand(snapshot is not None and snapshot.warehouse==batch.warehouse,'请选择本仓快照')
    sources={i['material_code']:i for i in snapshot.items};rows=deepcopy(ver.items)
    for row in rows:
        old=row['input'];demand(old['material_code'] in sources,'新快照缺少物料：'+old['material_code'])
        inp=deepcopy(sources[old['material_code']]);inp.update({k:old.get(k) for k in ('sea_plan_qty','air_plan_qty','reason','reason_code','air_reason')})
        for key in ('plan_source','plan_source_formulas'):
            if key in old:
                inp[key]=deepcopy(old[key])
        row['input']=inp;row['result']=calculate(inp,rule.package);row['decision']=None;row.pop('submission_override',None)
    return batch,ver,rule,snapshot,rows


def preview_basis(db,user,version_id,data):
    from .comparison import compare_items
    batch,ver,rule,snapshot,rows=basis_candidate(db,user,version_id,data)
    changes=compare_items(ver.items,rows)
    return {
        'revision':ver.revision,'snapshot':{'id':snapshot.id,'name':snapshot.name,'as_of':snapshot.as_of,'basis':snapshot.basis,'net_mode':snapshot.net_mode},
        'rule':{'id':rule.id,'name':rule.name},'total':len(rows),'affected_count':len(changes['items']),
        'quantity_changed_count':changes['summary']['quantity_changed'],'data_changed_count':changes['summary']['data_changed'],
        'before_summary':summary(ver.items),'after_summary':summary(rows),'items':changes['items'],
    }


def switch_basis(db,user,version_id,data):
    batch,ver,rule,snapshot,rows=basis_candidate(db,user,version_id,data,lock=True)
    audit(db,user,'切换计算依据',batch.warehouse,batch.id,ver.id,old_rule=ver.rule_id,new_rule=rule.id,old_snapshot=ver.snapshot_id,new_snapshot=snapshot.id)
    ver.items=rows;ver.rule_id=rule.id;ver.snapshot_id=snapshot.id;batch.updated_at=now()
    db.flush();return {'revision':ver.revision}
