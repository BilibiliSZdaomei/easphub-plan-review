from . import plan_undo
from .workflow_outbox import enqueue as enqueue_workflow_mail
from copy import deepcopy
from datetime import datetime
from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified, set_committed_value
from .db import Batch, Version, Rule, Snapshot, User, Notification, NotificationEvent,Warehouse, audit, uid, now
from .auth import role, scope
from .roles import has_role
from .plan_visibility import visible_batch_filter
from .governance import apply_governance, MASTER_FIELDS
from .rules import calculate, pending_plan_result, submission_issues, fingerprint, validate_package
from .rules import canonical_reason, REASON_LABELS, MODEL_V3, corrected_v3, sales_input_errors
from .periods import period_info
from .exceptions import approval_status, business_warnings, confirmation, warning_record
from .markets import rule_scopes
from .adapters import boolean, canonical, v2_sales
from .rules import number, serial

def demand(condition,message,status=422):
    if not condition: raise HTTPException(status,message)


def require_current_sales(item, package, line=None):
    if corrected_v3(package):
        errors = sales_input_errors(item)
        if errors:
            prefix = f"第 {line} 行 " if line is not None else ""
            raise HTTPException(422, prefix + str(item.get("material_code") or "") + " · " +
                                "；".join(error["message"] for error in errors))


def check_submission_inputs(rows, package):
    if package.get('model') != MODEL_V3:
        return
    demand(corrected_v3(package), '本草稿仍按旧版 V3 计算，请更换计算依据，选用现行标准并确认差异后再提交', 409)
    for line, row in enumerate(rows, 1):
        require_current_sales(row['input'], package, line)

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
    if batch.owner != user.id:
        allowed = db.scalar(select(Batch.id).where(Batch.id == batch.id, visible_batch_filter(db, user)))
        demand(allowed is not None, '没有该计划的访问权限', 403)
    return batch

def reopen_legacy_rejections(batch, version):
    """Older returned drafts carried the previous rejection as a current decision."""
    if version.state!='DRAFT' or batch.state!='RETURNED' or batch.current_id!=version.id:
        return
    if not any((row.get('decision') or {}).get('status') in ('REJECTED','RETURNED') for row in version.items):
        return
    rows=deepcopy(version.items)
    for row in rows:
        decision=row.get('decision') or {}
        if decision.get('status') in ('REJECTED','RETURNED'):
            row.update(previous_decision=decision,decision=None,return_requested=True,return_reason=decision.get('reason') or '')
    # Project the editable draft on read. The next saved edit or submission persists it.
    set_committed_value(version,'items',rows)


def version_access(db,user,version_id,lock=True):
    query=select(Version).where(Version.id==version_id)
    version=db.scalar(query.with_for_update() if lock else query)
    demand(version is not None,'版本不存在',404)
    batch=batch_access(db,user,version.batch_id)
    reopen_legacy_rejections(batch,version)
    return batch,version

def editable(user,batch,version,revision):
    role(user,'PLANNER')
    demand(batch.owner==user.id,'只有该计划创建人可以修改',403)
    demand(version.state=='DRAFT' and batch.current_id==version.id,'已提交版本不可修改，请在退回后的新草稿中处理',409)
    demand(revision==version.revision,'计划已被其他页面更新，请刷新后比较修改',409)

def summary(items):
    c=Counter({'total':len(items),'WITHIN':0,'BELOW':0,'ABOVE':0,'ERROR':0,'PENDING':0,'MANUAL':0,'EXEMPT':0,'attention':0,'delay':0,'unexplained':0,'reviewed':0,'air':0,'return_requested':0,'return_marked':0,'rejected':0})
    for row in items:
        r=row['result']
        if r.get('basis_pending'): c['PENDING']+=1
        if row['input'].get('reference_origin'): c['plan_reference']+=1
        if r['data_status']=='ERROR': c['ERROR']+=1
        elif r['review_mode']=='AUTO': c[r['quantity_status']]+=1
        else: c[r['review_mode']]+=1
        if r.get('delay_replenishment'): c['delay']+=1
        if r.get('turnover_warning'): c['turnover']+=1
        if business_warnings(row): c['attention']+=1
        if submission_issues(row['input'],r): c['unexplained']+=1
        if row.get('decision'): c['reviewed']+=1
        decision=(row.get('decision') or {}).get('status')
        if decision=='RETURNED': c['return_marked']+=1
        if decision=='REJECTED': c['rejected']+=1
        if row.get('return_requested'): c['return_requested']+=1
        if 'AIR' in r['manual_flags']: c['air']+=1
    return dict(c)

def batch_json(db,batch):
    version=db.get(Version,batch.current_id)
    reopen_legacy_rejections(batch,version)
    owner=db.get(User,batch.owner)
    warehouse=db.get(Warehouse,batch.warehouse)
    return {'id':batch.id,'number':batch.number,'title':batch.title,'warehouse':batch.warehouse,'warehouse_name':warehouse.name,
            'period':batch.period,'period_info':period_info(batch.period,strict=False),'owner':batch.owner,'owner_name':owner.name,'state':batch.state,'current_id':batch.current_id,
            **assignment(db,batch,version),
            'version':version.seq,'revision':version.revision,'summary':summary(version.items),'created_at':batch.created_at,'updated_at':batch.updated_at}

def notify(db,batch,text,reviewers=False,recipient=None,*,kind='GENERAL'):
    event=NotificationEvent(id=uid(),created_at=now(),payload={'warehouse':batch.warehouse,'batch_id':batch.id,'owner':batch.owner,'text':text,'reviewers':reviewers,'recipient':recipient,
        'kind':kind,'version_id':batch.current_id})
    db.add(event)
    return event

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
    if warning_count:notify(db,batch,f'{title} 有 {warning_count} 行审核提醒',kind='REMINDER')
    return batch


PLAN_FIELDS = ('sea_plan_qty','air_plan_qty','reason','reason_code','air_reason')
REFERENCE_FIELDS = {
    'material_name','material_type','vehicle_model','local_abc','material_abc','is_key_model',
    'fleet_qty','vehicle_parc','future_fleet_qty','large_value_flag','monthly_sales','current_sales',
    'shortage_qty','on_hand_qty','net_supply_before_plan','replacement_rate','replacement_target','sales_target',
}
SUPPLY_COMPONENTS = ('on_hand_qty','in_transit_qty','on_order_qty','demand_deduction_qty')


def reference_changes(item, edits, components=False):
    """Return only planner-owned inputs and any values derived from their edits."""
    allowed = REFERENCE_FIELDS | (set(SUPPLY_COMPONENTS) if components else set())
    demand(isinstance(edits,dict) and set(edits)<=allowed,'包含不可编辑的基础数据字段')
    changes = {}
    for key, raw in edits.items():
        if key == 'monthly_sales':
            demand(isinstance(raw,list) and len(raw)==6,'请按从早到晚提供六个月的销量')
            demand(all(v is None or isinstance(v,(int,float,str)) and len(str(v))<=80 for v in raw),'月销量格式无效')
            months = list(item.get('month_labels') or item.get('monthly_sales') or {})
            if len(months)!=6:
                months = [f'第{i}月销量' for i in range(1,7)]
            changes[key] = dict(zip(months,map(canonical,raw)))
            changes['month_labels'] = months
            changes['avg_sales_3m'],changes['avg_sales_6m'] = v2_sales(raw[-3:]),v2_sales(raw)
        else:
            demand(raw is None or isinstance(raw,(str,float,int)) and len(str(raw))<=300,'基础字段格式无效')
            if key == 'is_key_model':
                demand(raw in (None,'') or boolean(raw) is not None,'请选择是否为重点车型')
                changes[key] = boolean(raw)
            elif key == 'replacement_rate' and raw not in (None,''):
                try:
                    changes[key] = serial(number(raw))
                except ValueError as error:
                    raise HTTPException(422,'更换率：'+str(error)) from error
            else:
                changes[key] = canonical(raw) or None
    if components:
        demand('net_supply_before_plan' not in edits,'分项库存的净额由系统计算')
        if set(edits).intersection(SUPPLY_COMPONENTS):
            combined = {**item,**changes}
            try:
                parts = [number(combined.get(k)) for k in SUPPLY_COMPONENTS]
                changes['net_supply_before_plan'] = serial(parts[0]+parts[1]+parts[2]-parts[3]) if None not in parts else None
            except ValueError:
                changes['net_supply_before_plan'] = '分项数量无效'
    return changes


def plan_sources(db, version):
    if version.snapshot_id is None:
        return None
    return {i['material_code']: i for i in db.get(Snapshot, version.snapshot_id).items}


def plan_input(plan, sources, *, replace_plan=False, previous=None):
    code=plan.get('material_code')
    demand(isinstance(code,str) and bool(code.strip()),'请输入物料号')
    code=code.strip()
    if previous and (sources is None or previous.get('reference_origin')):
        inp=deepcopy(previous)
        if not previous.get('reference_origin') and plan.get('material_name'):
            inp['material_name']=str(plan['material_name']).strip()
    elif sources is None:
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
    if snapshot_id is not None or item.get('reference_origin'):
        return calculate(item,rule.package)
    result=pending_plan_result(item)
    _,basis=apply_governance(item,rule.package)
    if basis: result['master_basis']=basis
    return result

def patch_items(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    undo_before=plan_undo.capture(ver)
    rows=deepcopy(ver.items); by_id={r['id']:r for r in rows}; changes=data.get('changes',[])
    demand(isinstance(changes,list) and 0<len(changes)<=10000,'请选择要修改的计划行')
    rule=db.get(Rule,ver.rule_id)
    snapshot=db.get(Snapshot,ver.snapshot_id) if ver.snapshot_id else None
    applied=[]
    for change in changes:
        demand(isinstance(change,dict),'计划行修改格式无效')
        row=by_id.get(change.get('id')); demand(row is not None,'计划行不存在',404)
        values=change.get('values',{})
        demand(isinstance(values,dict) and set(values)<=set(PLAN_FIELDS),'包含不可编辑的计划字段')
        demand(all(len(str(v))<=2000 for v in values.values()),'说明文字过长')
        if 'reason_code' in values:
            values = {**values, 'reason_code': canonical_reason(values['reason_code'])}
        refs=reference_changes(row['input'],change.get('reference',{}),bool(snapshot and snapshot.net_mode=='COMPONENTS'))
        governed=set((row['result'].get('master_basis') or {}).get('values',{}))
        locked=governed.intersection(refs)
        demand(not locked,'这些字段由审核标准维护 · '+'、'.join(MASTER_FIELDS[k] for k in sorted(locked)))
        values={**values,**refs}
        different={k:v for k,v in values.items() if row['input'].get(k)!=v}
        for key in different.keys() & {'sea_plan_qty','air_plan_qty'}:
            old_value=row['input'].get(key)
            new_value=different[key]
            if '%' in str(old_value) or '%' in str(new_value):
                continue
            try:
                old_number=number(old_value)
                if old_number is not None and old_number>=0 and old_number==number(new_value):
                    del different[key]
            except ValueError:
                pass  # Keep invalid input visible to the quantity checks.
        candidate={**row['input'],**different}
        if different.keys() & refs.keys():
            candidate['reference_origin']='planner'
        if refs:
            require_current_sales(candidate, rule.package)
        if not different and 'reference' not in change:
            continue
        result=plan_result(candidate,rule,ver.snapshot_id)
        if not different and result==row['result']:
            continue
        applied.append(change)
        before={k:row['input'].get(k) for k in values};before_result=row['result']
        row['decision']=None
        row['input']=candidate
        row.pop('submission_override',None)
        row['result']=result
        row['adjustment']={'at':now(),'before':before,'after':deepcopy(values),'quantity_before':before_result['quantity_status'],'quantity_after':row['result']['quantity_status'],'review_reason':bool(row['input'].get('reason')) and any(k in values for k in ('sea_plan_qty','air_plan_qty'))}
    if not applied:
        return {'revision':ver.revision,'summary':summary(ver.items)}
    ver.items=rows; batch.updated_at=now()
    audit(db,user,'修改计划',batch.warehouse,batch.id,ver.id,changes=applied)
    db.flush()
    plan_undo.record(db,user,ver,undo_before,"修改计划明细")
    return {'revision':ver.revision,'summary':summary(rows)}

def add_items(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    undo_before=plan_undo.capture(ver)
    sources=plan_sources(db,ver)
    codes={r['input']['material_code'] for r in ver.items};rows=deepcopy(ver.items)
    plans=data.get('items')
    demand(isinstance(plans,list) and plans and all(isinstance(i,dict) for i in plans),'请选择要添加的物料')
    demand(len(rows)+len(plans)<=10000,'单批最多10000行')
    rule=db.get(Rule,ver.rule_id)
    snapshot=db.get(Snapshot,ver.snapshot_id) if ver.snapshot_id else None
    for plan in plans:
        inp=plan_input(plan,sources);code=inp['material_code']
        demand(code not in codes,'同一计划不能重复添加物料：'+code)
        if plan.get('reference'):
            inp.update(reference_changes(inp,plan['reference'],bool(snapshot and snapshot.net_mode=='COMPONENTS')))
            inp['reference_origin']='planner'
        require_current_sales(inp, rule.package)
        rows.append({'id':uid(),'input':inp,'result':plan_result(inp,rule,ver.snapshot_id),'decision':None});codes.add(code)
    ver.items=rows;batch.updated_at=now();audit(db,user,'添加计划行',batch.warehouse,batch.id,ver.id,count=len(rows));db.flush()
    plan_undo.record(db,user,ver,undo_before,"添加物料")
    return {'revision':ver.revision,'summary':summary(rows)}

def delete_items(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    undo_before=plan_undo.capture(ver)
    ids=set(data.get('ids',[])); demand(ids,'请选择计划行')
    demand(ids<={row['id'] for row in ver.items},'所选记录不属于当前版本')
    ver.items=[r for r in ver.items if r['id'] not in ids];batch.updated_at=now()
    audit(db,user,'删除计划行',batch.warehouse,batch.id,ver.id,ids=list(ids));db.flush()
    plan_undo.record(db,user,ver,undo_before,"删除物料")
    return {'revision':ver.revision}

def submit(db,user,version_id,data):
    batch,ver=version_access(db,user,version_id);editable(user,batch,ver,data.get('revision'))
    demand(bool(ver.items),'请先添加或导入计划')
    rows=deepcopy(ver.items)
    rule=db.get(Rule,ver.rule_id)
    demand(rule.state=='PUBLISHED','必须选择已发布审核标准')
    check_submission_inputs(rows, rule.package)
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
    # Freeze the projected legacy draft even when calculation reproduces it exactly.
    flag_modified(ver,'items')
    audit(db,user,'提交复审',batch.warehouse,batch.id,ver.id,input_hash=fingerprint(rows),rule_id=ver.rule_id,
          snapshot_id=ver.snapshot_id,warning_rows=report['affected_count'],issue_hash=report['issue_hash'],reason=record['reason'])
    event=notify(db,batch,batch.title+' 已提交，等待复审',True,kind='SUBMITTED')
    enqueue_workflow_mail(db,event,'RESUBMITTED' if ver.seq>1 else 'SUBMITTED',batch,ver,user)
    db.flush()
    return {'id':batch.id,'version_id':ver.id,'state':batch.state,'revision':ver.revision}

ACTIVE_REVIEW_STATES = ('SUBMITTED','IN_REVIEW')


def eligible_reviewer(user,batch):
    return bool(user and user.active and user.id!=batch.owner and has_role(user,'REVIEWER') and batch.warehouse in user.warehouses)


def assignment(db,batch,ver):
    # A disabled reviewer or a removed warehouse permission must not strand an active plan.
    if ver.reviewer_id and ver.state in ACTIVE_REVIEW_STATES and not eligible_reviewer(db.get(User,ver.reviewer_id),batch):
        return {'reviewer_id':None,'reviewer_name':None}
    return {'reviewer_id':ver.reviewer_id,'reviewer_name':ver.reviewer_name}


def review_access(db,user,version_id,revision,*,require_claim=True):
    role(user,'REVIEWER')
    batch,ver=version_access(db,user,version_id)
    demand(user.id!=batch.owner,'不能审批自己创建的计划',403)
    demand(ver.state in ACTIVE_REVIEW_STATES and batch.current_id==ver.id,'当前版本不在复审中',409)
    demand(revision==ver.revision,'复审内容已更新，请刷新后重试',409)
    if require_claim:
        demand(ver.reviewer_id==user.id,'请由当前领取人办理复审',403)
    return batch,ver


def claim(db,user,version_id,data):
    batch,ver=review_access(db,user,version_id,data.get('revision'),require_claim=False)
    demand(not assignment(db,batch,ver)['reviewer_id'],'计划已被领取，请刷新',409)
    old=ver.reviewer_id
    ver.reviewer_id=user.id
    ver.reviewer_name=user.name
    ver.state=batch.state='IN_REVIEW'
    batch.updated_at=now()
    event=notify(db,batch,f'{user.name} 已领取「{batch.title}」的复审',kind='CLAIMED')
    enqueue_workflow_mail(db,event,'CLAIMED',batch,ver,user)
    audit(db,user,'领取复审',batch.warehouse,batch.id,ver.id,previous_reviewer_id=old,reviewer_id=user.id,reviewer_name=user.name)
    db.flush()
    return {'revision':ver.revision,'reviewer_id':user.id,'reviewer_name':user.name}


def transfer(db,user,version_id,data):
    batch,ver=review_access(db,user,version_id,data.get('revision'))
    target_id=data.get('reviewer_id')
    demand(isinstance(target_id,str) and target_id!=user.id,'请选择其他复审人员')
    target=db.scalar(select(User).where(User.id==target_id).with_for_update())
    demand(eligible_reviewer(target,batch),'请选择本仓有效复审人员，且不能转给计划创建人')
    ver.reviewer_id=target.id
    ver.reviewer_name=target.name
    batch.updated_at=now()
    audit(db,user,'转交复审',batch.warehouse,batch.id,ver.id,from_reviewer_id=user.id,from_reviewer_name=user.name,
          reviewer_id=target.id,reviewer_name=target.name)
    event=notify(db,batch,f'{user.name} 将「{batch.title}」转交给你复审',reviewers=True,recipient=target.id,kind='TRANSFERRED')
    enqueue_workflow_mail(db,event,'TRANSFERRED',batch,ver,user,target=target)
    db.flush()
    return {'revision':ver.revision,'reviewer_id':target.id,'reviewer_name':target.name}


def review(db,user,version_id,data):
    batch,ver=review_access(db,user,version_id,data.get('revision'))
    undo_before=plan_undo.capture(ver)
    ids=set(data.get('ids',[]));demand(ids,'请选择复审记录')
    demand(ids <= {r['id'] for r in ver.items},'所选记录不属于当前版本')
    action=data.get('decision','APPROVED');demand(action in ('APPROVED','EXCEPTION_APPROVED','REJECTED','RETURNED'),'无效审批动作')
    reason=str(data.get('reason') or '').strip()
    demand(len(reason)<=2000,'复审备注最多2000字')
    approve=action in ('APPROVED','EXCEPTION_APPROVED')
    flags_input=data.get('ack_flags',[])
    demand(isinstance(flags_input,list) and all(isinstance(f,str) for f in flags_input),'关注项格式无效')
    ack=set(flags_input);air=data.get('air_confirmed') is True
    reason_code=canonical_reason(data.get('reason_code'))
    demand(not reason_code or (isinstance(reason_code,str) and reason_code in REASON_LABELS),'无效的复审原因类别')
    only_pending = len(ids)>1 or data.get('only_pending') is True
    rows=deepcopy(ver.items);processed=[];preserved=0;exceptions=0
    for row in rows:
        if row['id'] not in ids: continue
        if only_pending and row.get('decision'):
            preserved+=1
            continue
        flags=set(row['result']['manual_flags'])
        outcome=approval_status(row['result']) if approve else 'REJECTED'
        decision={'status':outcome,'reason':reason,'reason_code':reason_code,'reviewer_id':user.id,
                  'reviewer_name':user.name,'ack_flags':sorted((flags-{'AIR'}) & ack),
                  'air_confirmed':'AIR' in flags and air}
        previous={k:v for k,v in (row.get('decision') or {}).items() if k!='reviewed_at'}
        if previous==decision:
            preserved+=1
            continue
        exceptions+=outcome=='EXCEPTION_APPROVED'
        row['decision']={**decision,'reviewed_at':now()}
        processed.append(row['id'])
    if processed:
        ver.items=rows;ver.state='IN_REVIEW';batch.state='IN_REVIEW';batch.updated_at=now()
        audit(db,user,'保存行复审',batch.warehouse,batch.id,ver.id,ids=processed,count=len(processed),
              decision='APPROVED' if approve else 'REJECTED',exception_approved=exceptions,reason=reason)
        db.flush()
        plan_undo.record(db,user,ver,undo_before,"复审决定")
    return {'count':len(processed),'exception_count':exceptions,'preserved':preserved,'skipped':[],'revision':ver.revision,'summary':summary(rows)}

def finalize(db,user,version_id,data):
    batch,ver=review_access(db,user,version_id,data.get('revision'))
    demand(bool(ver.items),'空白计划不能终审')
    outcome=data.get('outcome','APPROVED')
    demand(outcome in ('APPROVED','REJECTED'),'请选择有效的整单终审结果')
    report=confirmation(ver.items,'finalize',ver.revision)
    if outcome=='REJECTED':
        demand(report['approval_blocked'],'当前没有不批准的物料，不能整单不批准')
    else:
        demand(not report['approval_blocked'],'存在不批准的物料，请退回计划，或选择整单不批准')
    at=now()
    record=warning_record(data,report,user,at)
    if outcome=='APPROVED' and report['unreviewed']:
        rows=deepcopy(ver.items)
        for row in rows:
            if not row.get('decision'):
                row['decision']={'status':approval_status(row['result']),'batch':True,'reviewer_id':user.id,'reviewer_name':user.name,
                                 'reviewed_at':at,'reason':record['reason'],'ack_flags':[],'air_confirmed':False}
        ver.items=rows
    approved=report['total'] if outcome=='APPROVED' else 0
    message=f"已通过终审，核准 {approved} 行" if approved else f"已整单不批准，{report['total']} 行均不执行"
    ver.state=batch.state=outcome
    ver.finalized_at=at;batch.updated_at=at
    audit(db,user,'完成终审',batch.warehouse,batch.id,ver.id,outcome=outcome,rows=report['total'],
          rejected=report['total']-approved,approved=approved,exception_approved=report['exception_approved'],
          reviewed_approved=report['reviewed_approved'],reviewed_exception=report['reviewed_exception'],
          reviewed_rejected=report['rejected'],unreviewed=report['unreviewed'],
          batch_approved=report['unreviewed'] if approved else 0,
          warning_rows=report['affected_count'],issue_hash=report['issue_hash'],reason=record['reason'])
    event=notify(db,batch,batch.title+' '+message,kind='FINALIZED')
    enqueue_workflow_mail(db,event,outcome,batch,ver,user,approved_count=approved,rejected_count=report['total']-approved,
                          reason=record['reason'])
    db.flush()
    return {'state':outcome,'revision':ver.revision}

def return_batch(db,user,version_id,data):
    batch,old=review_access(db,user,version_id,data.get('revision'))
    reason=str(data.get('reason') or '').strip()
    demand(len(reason)<=2000,'退回备注最多2000字')
    requested=data.get('ids',[])
    demand(isinstance(requested,list) and all(isinstance(i,str) for i in requested),'请选择本版本物料')
    requested=set(requested)
    demand(requested<={row['id'] for row in old.items},'所选物料不属于本版本')
    old.state='RETURNED'
    rows=deepcopy(old.items)
    flagged=[]
    for row in rows:
        previous=row.get('decision')
        row['previous_decision']=deepcopy(previous)
        row.pop('submission_override',None)
        row.pop('return_requested',None)
        row.pop('return_reason',None)
        if (previous or {}).get('status') in ('REJECTED','RETURNED') or row['id'] in requested:
            # ids is a compatibility hint from older clients. Preserve the frozen review.
            row.update(decision=None,return_requested=True,return_reason=(previous or {}).get('reason') or (reason if row['id'] in requested else ''))
            flagged.append(row)
    ver=Version(id=uid(),batch_id=batch.id,seq=old.seq+1,snapshot_id=old.snapshot_id,rule_id=old.rule_id,items=rows)
    db.add(ver);db.flush();batch.current_id=ver.id;batch.state='RETURNED';batch.updated_at=now()
    audit(db,user,'退回修改',batch.warehouse,batch.id,old.id,reason=reason,new_version=ver.id,
          ids=[r['id'] for r in flagged],material_codes=[r['input']['material_code'] for r in flagged])
    detail=f'，{len(flagged)} 行需修改' if flagged else ''
    event=notify(db,batch,f'{batch.title} 已整单退回{detail}',kind='RETURNED')
    enqueue_workflow_mail(db,event,'RETURNED',batch,ver,user,flagged_count=len(flagged),reason=reason)
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
    if snapshot_id is None or snapshot_id==ver.snapshot_id:
        demand(snapshot is not None or ver.snapshot_id is None,'请选择本仓快照')
        rows=deepcopy(ver.items)
        for row in rows:
            result=plan_result(row['input'],rule,ver.snapshot_id)
            if ver.rule_id==rule.id and row['result']==result:
                continue
            row['result']=result
            row['decision']=None
            row.pop('submission_override',None)
        return batch,ver,rule,snapshot,rows
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
        'revision':ver.revision,'snapshot':{'id':snapshot.id,'name':snapshot.name,'as_of':snapshot.as_of,'basis':snapshot.basis,'net_mode':snapshot.net_mode} if snapshot else None,
        'rule':{'id':rule.id,'name':rule.name},'total':len(rows),'affected_count':len(changes['items']),
        'quantity_changed_count':changes['summary']['quantity_changed'],'data_changed_count':changes['summary']['data_changed'],
        'before_summary':summary(ver.items),'after_summary':summary(rows),'items':changes['items'],
    }


def switch_basis(db,user,version_id,data):
    batch,ver,rule,snapshot,rows=basis_candidate(db,user,version_id,data,lock=True)
    undo_before=plan_undo.capture(ver)
    if ver.rule_id==rule.id and ver.snapshot_id==(snapshot.id if snapshot else None) and ver.items==rows:
        return {'revision':ver.revision}
    audit(db,user,'切换计算依据',batch.warehouse,batch.id,ver.id,old_rule=ver.rule_id,new_rule=rule.id,old_snapshot=ver.snapshot_id,new_snapshot=snapshot.id if snapshot else None)
    ver.items=rows;ver.rule_id=rule.id;ver.snapshot_id=snapshot.id if snapshot else None;batch.updated_at=now()
    db.flush()
    plan_undo.record(db,user,ver,undo_before,"更换计算依据")
    return {'revision':ver.revision}
