from copy import deepcopy
from pathlib import Path
from datetime import date
from urllib.parse import quote
from decimal import Decimal
import json
import csv
from io import StringIO
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import defer
from .db import *
from .auth import role, scope
from .roles import has_role
from .api_common import context, once
from .jobs import FILES, parse_upload
from .adapters import FIELDS, ENGLISH_FIELDS, MAX_BYTES, PLAN_QUANTITIES, normalize
from .template_assets import WORKBOOK_TEMPLATES, dated_v3_template
from .workbook_language import english_workbook
from .periods import period_info
from .rules import fingerprint, number
from . import services as svc
from .markets import MARKET_NAMES, market_key

router=APIRouter()

def import_role(kind):
    return 'PLANNER' if kind=='plan' else 'REVIEWER'

@router.get('/fields')
def fields(ctx=Depends(context,scope="function")):return FIELDS

@router.get('/snapshots')
def snapshots(warehouse:str='',ctx=Depends(context,scope="function")):
    db,user=ctx
    query=select(Snapshot).where(Snapshot.warehouse.in_(user.warehouses)).options(defer(Snapshot.items)).order_by(Snapshot.created_at.desc())
    if warehouse:scope(user,warehouse);query=query.where(Snapshot.warehouse==warehouse)
    return [{'id':s.id,'name':s.name,'warehouse':s.warehouse,'as_of':s.as_of,'rows':len(s.items),'net_mode':s.net_mode,'basis':s.basis,'created_at':s.created_at,'source_id':s.source_id} for s in db.scalars(query)]

@router.get('/snapshots/{snapshot_id}/materials')
def materials(snapshot_id:str,q:str='',ctx=Depends(context,scope="function")):
    db,user=ctx;s=db.get(Snapshot,snapshot_id);svc.demand(s is not None,'快照不存在',404);scope(user,s.warehouse)
    return [{'material_code':i['material_code'],'material_name':i.get('material_name',''),'net_supply_before_plan':i.get('net_supply_before_plan'),
             'current_sales':i.get('current_sales'), 'shortage_qty':i.get('shortage_qty')} for i in s.items if q.casefold() in (i['material_code']+' '+(i.get('material_name') or '')).casefold()][:100]

@router.get('/mappings')
def mappings(ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER')
    return [{'id':m.id,'name':m.name,'warehouse':m.warehouse,'config':m.config} for m in db.scalars(select(Mapping).where(Mapping.warehouse.in_(user.warehouses)))]
@router.post('/mappings')
def create_mapping(data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;role(user,'REVIEWER');scope(user,data.get('warehouse'))
    def do():
        svc.demand(data.get('name'),'请填写映射名称');config=data.get('config',{})
        svc.demand(set(config)<=set(FIELDS),'映射包含未知字段')
        m=Mapping(id=uid(),name=data['name'],warehouse=data['warehouse'],config=config,creator=user.id);db.add(m)
        audit(db,user,'保存字段映射',m.warehouse,mapping_id=m.id,name=m.name)
        return {'id':m.id}
    return once(db,user,request,data,do)

@router.post('/imports')
async def upload(request:Request,file:UploadFile=File(...),warehouse:str=Form(...),kind:str=Form('standard'),net_mode:str=Form('NET_PROVIDED'),mapping:str=Form('{}'),sheet_name:str=Form(''),version_id:str=Form(''),ctx=Depends(context,scope="function")):
    db,user=ctx;scope(user,warehouse)
    role(user,import_role(kind))
    svc.demand(kind in ('v3','v2','legacy','standard','plan','inventory','transit','onorder','targets'),'不支持的数据类型')
    try:map_values=json.loads(mapping)
    except ValueError:raise HTTPException(422,'字段映射格式有误')
    svc.demand(isinstance(map_values,dict) and set(map_values)<=set(FIELDS),'字段映射包含未知字段')
    blob=await file.read(MAX_BYTES+1)
    svc.demand(len(blob)<=MAX_BYTES,'文件超过20MiB',413)
    if kind=='plan' and version_id:
        batch,ver=svc.version_access(db,user,version_id,lock=False)
        svc.editable(user,batch,ver,ver.revision)
        svc.demand(warehouse==batch.warehouse,'导入仓库与计划仓库不一致')
        validation_rule=db.get(Rule,ver.rule_id)
    else:
        validation_rule = svc.active_rule(db,warehouse,required=False) if kind in ('v3','v2','legacy','standard','plan') else None
    job_id=uid();file_id=job_id+Path(file.filename or '').suffix.lower()
    (FILES/file_id).write_bytes(blob)
    job=Job(id=job_id,kind='import',user_id=user.id,warehouse=warehouse,payload={'file_id':file_id,'filename':Path(file.filename or 'data.xlsx').name,'kind':kind,'net_mode':net_mode,'mapping':map_values,'sheet_name':sheet_name or None,
        'validation_rule_id':validation_rule.id if validation_rule else None,'version_id':version_id or None})
    db.add(job);audit(db,user,'上传数据',warehouse,job_id=job_id,filename=job.payload['filename'])
    return {'id':job_id,'state':'QUEUED'}

def job_access(db,user,job_id):
    j=db.get(Job,job_id);svc.demand(j is not None,'任务不存在',404);scope(user,j.warehouse)
    published=j.kind=='import' and j.payload.get('kind')!='plan' and j.committed_id and db.get(Snapshot,j.committed_id)
    may_read_published=bool(published and has_role(user,'REVIEWER'))
    svc.demand(j.user_id==user.id or has_role(user,'ADMIN') or may_read_published,'没有该文件任务权限',403)
    if j.kind == 'export' or j.payload.get('kind') == 'plan':
        batch_id = j.payload.get('batch_id')
        version_id = j.payload.get('version_id') or (j.committed_id if j.kind == 'import' else None)
        # Older exports can retain the batch number only.
        number = (j.payload.get('metadata') or {}).get('批次') if j.kind == 'export' else None
        if not batch_id and version_id:
            batch_id = db.scalar(select(Version.batch_id).where(Version.id == version_id))
        elif not batch_id and number:
            batch_id = db.scalar(select(Batch.id).where(Batch.number == number))
        if batch_id:
            svc.batch_access(db, user, batch_id)
        else:
            unbound_upload = j.kind == 'import' and not version_id
            svc.demand(unbound_upload and j.user_id == user.id, '无法确认该文件的计划权限', 403)
    return j

def checked_import_result(job):
    result = job.result
    if job.payload['kind'] == 'plan' and not job.committed_id and not result.get('plan_quantities_checked'):
        # Older previews defaulted both empty quantities to zero. Recover the actual cells from the upload.
        try:
            checked = parse_upload(job.payload)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(422, "请重新上传该计划文件以核对海运和空运数量") from exc
        job.result = {**result, **checked}
    return job.result

@router.get('/jobs/{job_id}')
def get_job(job_id:str,ctx=Depends(context,scope="function")):
    db,user=ctx;j=job_access(db,user,job_id);r=j.result or {}
    result={'id':j.id,'kind':j.kind,'state':j.state,'error':j.error,'attempts':j.attempts,'committed_id':j.committed_id}
    if j.kind=='import' and j.state=='DONE':
        r=checked_import_result(j)
        result.update({'rows':len(r['items']),'plan_format':r.get('plan_format'),'headers':r['headers'],'issues':r['issues'][:100],'issues_total':len(r['issues']),'validation':r.get('validation',[])[:100],
                       'preview':r['items'][:8],'net_mode':r['net_mode'],'filename':j.payload['filename'],'sheet':r['items'][0]['source']['sheet'],'validation_total':len(r.get('validation',[]))})
    if j.kind=='export' and j.state=='DONE':
        from .settings import API_PREFIX
        result.update({'filename':r['filename'],'rows':r['rows'],'download_url':f'{API_PREFIX}/jobs/{j.id}/download'})
    return result

@router.get('/jobs/{job_id}/download')
def download(job_id:str,ctx=Depends(context,scope="function")):
    db,user=ctx;j=job_access(db,user,job_id)
    svc.demand(j.state=='DONE','文件尚未准备好',409)
    if j.kind=='export':
        from .exporting import EXECUTION_FORMAT, old_export_requires_refresh
        old_approved=j.result.get('execution_format')!=EXECUTION_FORMAT and (j.payload.get('metadata') or {}).get('版本状态')=='APPROVED'
        version=db.get(Version,j.payload['version_id']) if old_approved and j.payload.get('version_id') else None
        svc.demand(not old_export_requires_refresh(j.payload,j.result,version),'此文件按旧规则生成，请在计划页重新导出。',409)
        file_id=j.result['file_id'];filename=j.result['filename']
    else:file_id=j.payload['file_id'];filename=j.payload['filename']
    file=FILES/file_id;svc.demand(file.is_file(),'文件缺失，请联系管理员',404)
    if j.kind=='export' and j.payload.get('version_id'):
        audit(db,user,'下载文件',j.warehouse,j.payload['batch_id'],j.payload['version_id'],job_id=j.id,rows=j.result['rows'],filtered=j.payload.get('filtered',False))
    else:
        audit(db,user,'下载文件',j.warehouse,job_id=j.id)
    return FileResponse(file,filename=filename)

@router.get('/imports/{job_id}/errors')
def import_errors(job_id:str,ctx=Depends(context,scope="function")):
    db,user=ctx;j=job_access(db,user,job_id);svc.demand(j.kind=='import','请选择导入文件');svc.demand(j.state=='DONE','请等待文件检查完成')
    buf=StringIO();w=csv.writer(buf);w.writerow(['文件','工作表','行号','物料号','字段','原因','修复提示'])
    result=checked_import_result(j)
    for e in (result.get('issues',[])+result.get('validation',[])):
        values=[str(e[k]) if e.get(k) is not None else '' for k in ('file','sheet','row','material_code','field','message','repair_hint')]
        w.writerow(["'"+v if v.lstrip().startswith(('=','+','-','@')) else v for v in values])
    return Response('\ufeff'+buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="import-errors.csv"'})

@router.post('/imports/{job_id}/commit')
def commit_import(job_id:str,data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;j=job_access(db,user,job_id)
    def do():
        svc.demand(j.state=='DONE','文件检查尚未完成');svc.demand(not j.committed_id,'该文件任务已经确认，请查看已有结果',409)
        result=checked_import_result(j)
        if result['issues']:
            issue=result['issues'][0]
            raise HTTPException(422, f"第 {issue['row']} 行 {issue['material_code']} · {issue['message']}")
        kind=j.payload['kind']
        if kind=='plan':
            role(user,'PLANNER');batch,ver=svc.version_access(db,user,data.get('version_id'));svc.editable(user,batch,ver,data.get('revision'))
            svc.demand(batch.warehouse==j.warehouse,'导入仓库与计划仓库不一致')
            svc.demand(not j.payload.get('version_id') or j.payload['version_id']==ver.id,'该文件属于其他计划版本')
            undo_before=svc.plan_undo.capture(ver)
            full=result.get('plan_format') in ('legacy','v2','v3')
            mode=data.get('mode','replace')
            svc.demand(mode in ('replace','update_quantities') and not (full and mode=='update_quantities'),'导入方式与文件不符')
            update=mode=='update_quantities'
            sources=None if full else svc.plan_sources(db,ver)
            rows=[]
            rule=db.get(Rule,ver.rule_id)
            previous={row['input']['material_code']:row for row in ver.items}
            for plan in result['items']:
                old=previous.get(plan['material_code'],{})
                imported_formulas = dict(plan.get('source_formulas') or {})
                if full:
                    inp={**deepcopy(plan),'reference_origin':'plan_file'}
                    svc.require_current_sales(inp, rule.package, plan['source']['row'])
                    for key in ('reason_code','reason','air_reason'):
                        if key in old.get('input',{}):
                            inp[key]=old['input'][key]
                else:
                    inp=svc.plan_input(plan,sources,replace_plan=True,previous=old.get('input'))
                    if update and old:
                        prior_input = old['input']
                        for key in PLAN_QUANTITIES:
                            if plan['source_values'].get(key) in (None, '') and plan[key] == '0':
                                inp[key] = prior_input.get(key, '0')
                                prior_formula = prior_input.get('plan_source_formulas', {}).get(key)
                                if prior_formula:
                                    imported_formulas[key] = {**prior_formula,
                                        'source': prior_formula.get('source') or prior_input.get('plan_source')}
                        for key in ('reason','reason_code','air_reason'):
                            if not plan.get(key) and old['input'].get(key):
                                inp[key]=old['input'][key]
                inp['plan_source']={**plan['source'],'job_id':j.id,'sha256':result['file_hash']}
                if full: inp['source']=dict(inp['plan_source'])
                inp.pop('plan_source_formulas',None)
                if imported_formulas:inp['plan_source_formulas']=imported_formulas
                row={'id':old.get('id') or uid(),'input':inp,'result':svc.plan_result(inp,rule,ver.snapshot_id),'decision':None}
                if old.get('decision'):
                    from .comparison import changed_fields
                    if not changed_fields(old['input'],inp,('source','source_values','source_formulas','plan_source','plan_source_formulas','reference_origin')) and not changed_fields(old['result'],row['result'],('input_hash',)):
                        row['decision']=deepcopy(old['decision'])
                for key in ('return_requested','return_reason','previous_decision'):
                    if old.get(key):row[key]=old[key]
                rows.append(row)
            if update:
                imported={row['input']['material_code']:row for row in rows}
                rows=[imported.pop(code,old) for code,old in previous.items()]+list(imported.values())
                svc.demand(len(rows)<=10000,'单批最多10000行')
            if full: ver.snapshot_id=None
            ver.items=rows;batch.updated_at=now();j.committed_id=ver.id;db.flush()
            svc.plan_undo.record(db,user,ver,undo_before,'导入计划')
            audit(db,user,'确认计划导入',j.warehouse,batch.id,ver.id,job_id=j.id,rows=len(rows))
            return {'version_id':ver.id,'revision':ver.revision}
        role(user,import_role(kind))
        svc.demand(data.get('name') and data.get('as_of') and data.get('basis'),'请填写快照名称、数据日期和净额口径说明')
        from datetime import date
        try:date.fromisoformat(data['as_of'])
        except (ValueError,TypeError):raise HTTPException(422,'数据日期必须是有效的年月日')
        mode=result['net_mode'];items=deepcopy(result['items'])
        svc.demand(not (mode=='COMPONENTS' and data.get('demand_already_deducted')),'分项模式不能再次抵扣已扣过的需求')
        if kind in ('inventory','transit','onorder','targets'):
            base=db.get(Snapshot,data.get('base_snapshot_id'));svc.demand(base is not None and base.warehouse==j.warehouse,'请选择同仓基础快照')
            updates={i['material_code']:i for i in items};items=deepcopy(base.items)
            known={i['material_code'] for i in items};missing=set(updates)-known
            svc.demand(not missing,'基础快照未包含物料：'+'、'.join(sorted(missing)[:8]))
            keys={'inventory':['on_hand_qty'],'transit':['in_transit_qty'],'onorder':['on_order_qty'],'targets':['replacement_target','sales_target','replacement_rate','fleet_qty','future_fleet_qty','vehicle_model','vehicle_parc','avg_sales_3m','avg_sales_6m','is_key_model','material_abc']}[kind]
            mode=base.net_mode if kind=='targets' else 'COMPONENTS'
            for idx,inp in enumerate(items):
                change=updates.get(inp['material_code'])
                if change:
                    svc.demand(change['uom']==inp.get('uom','PCS'),'计量单位不同，请先按标准单位转换：'+inp['material_code'])
                    for k in keys:
                        if change.get(k) is not None:inp[k]=change[k]
                    inp['source_update']=change['source']
                if kind!='targets':
                    mode='COMPONENTS'
                    inp=normalize(inp,inp['source']['row'],inp['source']['sheet'],inp['source']['file'],mode)
                # Assign back after normalization so net supply uses the new component.
                items[idx]=inp
        svc.demand(not (mode=='COMPONENTS' and data.get('demand_already_deducted')),'分项模式不能再次抵扣已扣过的需求')
        if data.get('mapping_id'):
            mapping_record=db.get(Mapping,data['mapping_id'])
            svc.demand(mapping_record is not None and mapping_record.warehouse==j.warehouse,'映射不属于该仓库')
            svc.demand(mapping_record.config==j.payload.get('mapping'),'已保存映射与本次实际使用的映射不一致')
        if kind in ('standard','v3','v2','legacy'):
            active = svc.active_rule(db,j.warehouse,required=False)
            if active:
                for inp in items:
                    svc.require_current_sales(inp, active.package, inp['source']['row'])
        if mode=='COMPONENTS':
            for inp in items:
                for key in ('on_hand_qty','in_transit_qty','on_order_qty','demand_deduction_qty'):
                    try:n=number(inp.get(key))
                    except ValueError:n=None
                    svc.demand(n is not None,'分项模式缺少有效的'+FIELDS[key]+'：'+inp['material_code'])
                vals=[number(inp[k]) for k in ('on_hand_qty','in_transit_qty','on_order_qty','demand_deduction_qty')]
                inp['net_supply_before_plan']=str(vals[0]+vals[1]+vals[2]-vals[3])
        else:
            for inp in items:
                if result['kind'] == 'v3' and inp.get('net_supply_before_plan') in (None, ''):
                    continue  # Keep unavailable stock distinct from zero for review.
                try:n=number(inp.get('net_supply_before_plan'))
                except ValueError:n=None
                svc.demand(n is not None,'审核前净额无效：'+inp['material_code'])
        snap=Snapshot(id=uid(),warehouse=j.warehouse,name=data['name'],as_of=data['as_of'],net_mode=mode,basis=data['basis'],items=items,source_id=j.id,mapping_id=data.get('mapping_id'),creator=user.id,digest=fingerprint(items))
        db.add(snap);j.committed_id=snap.id
        audit(db,user,'发布数据快照',j.warehouse,snapshot_id=snap.id,rows=len(items),net_mode=mode,basis=data['basis']);db.flush()
        return {'snapshot_id':snap.id,'rows':len(items)}
    return once(db,user,request,data,do)

@router.get('/template')
def template(kind:str='plan',version_id:str='',period:str='',ctx=Depends(context,scope="function"),lang:str='zh'):
    if kind=='v3':
        if version_id:
            db,user=ctx
            batch_id=db.scalar(select(Version.batch_id).where(Version.id==version_id))
            svc.demand(batch_id is not None,'计划版本不存在',404)
            batch=svc.batch_access(db,user,batch_id)
            if period_info(batch.period,strict=False)['start']:
                svc.demand(not period or period==batch.period,'模板月份与所选计划周期不一致')
                period=batch.period
            else:
                svc.demand(period,'旧计划缺少标准周期，请选择模板月份')
        period=period or date.today().isoformat()[:7]
        content=dated_v3_template(period,lang)
        filename=quote(f'Plan-review-V3-{period}.xlsx' if lang=='en' else f'计划审核V3模板_{period}.xlsx')
        return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}",'Cache-Control':'private, no-store'})
    if kind in WORKBOOK_TEMPLATES:
        asset, filename = WORKBOOK_TEMPLATES[kind]
        if kind=='plan' and lang=='en':
            return Response(english_workbook(asset,asset.stat().st_mtime_ns),
                            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers={'Content-Disposition':'attachment; filename="Plan-quantity-update.xlsx"'})
        return FileResponse(asset, filename=filename,
                            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    buf=StringIO();w=csv.writer(buf);w.writerow([ENGLISH_FIELDS[key] if lang=='en' else label for key,label in FIELDS.items()])
    return Response('\ufeff'+buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="standard-data-template.csv"'})

@router.post('/exports')
def export(data:dict,request:Request,ctx=Depends(context,scope="function")):
    db,user=ctx;batch,ver=svc.version_access(db,user,data.get('version_id'))
    from .table_query import COLUMNS, query_items
    def do():
        filtered=data.get('scope')=='filtered'
        reviewing=has_role(user,'REVIEWER') and ver.state in ('SUBMITTED','IN_REVIEW')
        field=data.get('sort_key','')
        direction=data.get('sort_direction','asc')
        rows=query_items(ver.items,data.get('q','') if filtered else '',data.get('filter','all') if filtered else 'all',
                         data.get('column_filters',{}) if filtered else {},field,direction,reviewing=reviewing,version_state=ver.state)
        warehouse = db.get(Warehouse, batch.warehouse)
        market = market_key(warehouse.market)
        if field:
            label=next(label for key,label,_ in COLUMNS if key==field)
            order=label+' · '+('降序' if direction=='desc' else '升序')
        else:
            order='复审优先顺序' if reviewing else '计划原顺序'
        market_tag = market+'_' if market in MARKET_NAMES else ''
        snap=db.get(Snapshot,ver.snapshot_id) if ver.snapshot_id else None
        rule=db.get(Rule,ver.rule_id)
        job=Job(id=uid(),kind='export',user_id=user.id,warehouse=batch.warehouse,payload={'batch_id':batch.id,'version_id':ver.id,'filtered':filtered,'items':deepcopy(rows),'rule_package':deepcopy(rule.package),'filename':f"计划审核_{market_tag}{batch.number}_V{ver.seq}_{'筛选结果' if filtered else '完整版本'}.xlsx",'metadata':{'市场':MARKET_NAMES.get(market,warehouse.market),'市场编码':warehouse.market,'仓库':warehouse.name,'仓库编码':warehouse.code,'批次':batch.number,'计划周期':batch.period,'计划周期说明':svc.batch_json(db,batch)['period_info']['label'],'筛选条件':json.dumps({'q':data.get('q',''),'filter':data.get('filter','all'),'columns':data.get('column_filters',{})},ensure_ascii=False) if filtered else '完整版本','排序':order,'版本':ver.seq,'版本状态':ver.state,'导出范围':'筛选结果' if filtered else '完整版本','规则版本':ver.rule_id,'审核标准名称':rule.name,'数据快照':ver.snapshot_id,'数据快照名称':snap.name if snap else None,'计划自带基础数据行数':sum(bool(row['input'].get('reference_origin')) for row in rows),'来源修订号':ver.revision,'导出人':user.name,'导出时间':now(),'精度版本':rule.package['precision_version'],'数据日期':snap.as_of if snap else None,'来源口径':snap.basis if snap else None,'规则参数':json.dumps({k:v for k,v in rule.package.items() if k!='master_data'},ensure_ascii=False),'标准物料数':len((rule.package.get('master_data') or {}).get('items',{})),'提交计算时间':ver.submitted_at or ver.created_at}})
        from .export_layout import export_layout_reference
        job.payload['layout'] = export_layout_reference(db, ver, batch.warehouse, snap)
        if ver.state == 'RETURNED':
            returned = db.scalar(select(Audit).where(Audit.version_id==ver.id,Audit.action=='退回修改').order_by(Audit.created_at.desc()).limit(1))
            if returned and returned.detail.get('reason'):
                job.payload['metadata']['整单退回备注'] = returned.detail['reason']
        if snap:
            job.payload['net_mode'] = snap.net_mode
        if ver.reviewer_name:
            job.payload['metadata']['复审负责人']=ver.reviewer_name
        from .exporting import execution_basis
        job.payload['execution'] = execution_basis(ver.state,ver.items,batch.current_id==ver.id)
        if ver.state=='PARTIALLY_APPROVED':
            job.payload['filename']='历史结案（旧规则）_'+job.payload['filename']
        db.add(job);audit(db,user,'创建导出',batch.warehouse,batch.id,ver.id,job_id=job.id,rows=len(rows),filtered=filtered);return {'id':job.id}
    return once(db,user,request,data,do)
