"""One table contract for paging, selection, and workbook export."""
import json
from fastapi import HTTPException
from .rules import number, FLAG_LABELS, submission_issues
from .exceptions import business_warnings

COLUMNS = [
 ('material_code','物料号','text'),('material_name','物料名称','text'),('material_abc','物料分类ABC','enum'),('vehicle_model','车型','text'),
 ('net_supply_before_plan','审核前净额','number'),('sea_plan_qty','海运计划','number'),('air_plan_qty','空运计划','number'),
 ('future_qty','未来库存','number'),('lower','库存下限','number'),('upper','库存上限','number'),
 ('status','系统结论','enum'),('attention','人工关注','text'),('m','月均销量最大值','number'),
 ('on_hand_months','在库周转（月）','number'),('pipeline_days','净库存周转（天）','number'),('future_days','补货后周转（天）','number'),
 ('delay_replenishment','建议延迟补货','enum'),('advice','审批建议','text'),('vehicle_parc','备件保有量','number'),('source_note','备注','text'),('is_key_model','是否重点车型','enum'),
 ('avg_sales_3m','三个月月均销量','number'),('avg_sales_6m','六个月月均销量','number'),('fleet_qty','装车量','number'),
 ('on_hand_qty','在库数量','number'),('in_transit_qty','在途数量','number'),('on_order_qty','在订数量','number'),
 ('replacement_rate','稳态更换率','number'),('replacement_target','更换率目标库存','number'),('sales_target','销量目标库存','number'),
 ('decision','复审决定','enum'),('reason','计划说明','text'),('air_reason','空运说明','text'),('override','提交与终审记录','enum')]
TYPES={k:t for k,_,t in COLUMNS}
STATUS={'WITHIN':'合理','BELOW':'偏少','ABOVE':'偏多','ERROR':'数据错误','PENDING':'待补数据','MANUAL':'人工判断','EXEMPT':'免数量审核','UNAVAILABLE':'无法计算'}

def numeric(v):
    try:return number(v)
    except ValueError:return None

def decision_label(decision, version_state=None):
    status = (decision or {}).get('status')
    if status:
        return {'APPROVED':'已批准','BATCH_APPROVED':'整批通过','EXCEPTION_APPROVED':'例外批准'}.get(status,status)
    if version_state == 'DRAFT':
        return '未提交'
    if version_state in ('RETURNED','VOID','APPROVED'):
        return '未复审'
    return '待复审'


def display_row(row, version_state=None):
    i=row['input'];r=row['result'];d=row.get('decision') or {}
    status=r['data_status'] if r['data_status'] in ('ERROR','PENDING') else r['review_mode'] if r['review_mode']!='AUTO' else r['quantity_status']
    values={**i,**r,'status':STATUS.get(status,status),'attention':'；'.join(FLAG_LABELS.get(f,f) for f in r['manual_flags']),
            'is_key_model':'是' if i.get('is_key_model') is True else '否' if i.get('is_key_model') is False else None,
            'decision':decision_label(d, version_state),
            'override':'例外终审' if d.get('forced') else '提交时有提醒' if (row.get('submission_override') or {}).get('mode')=='advisory' else '带问题提交' if row.get('submission_override') else '无'}
    values['delay_replenishment'] = {True:'是', False:'否'}.get(r.get('delay_replenishment'))
    for key in ('on_hand_months', 'pipeline_days', 'future_days'):
        values[key] = r.get(key)
    return values

def parse_filters(filters):
    try:filters=json.loads(filters) if isinstance(filters,str) else filters or {}
    except (ValueError,TypeError):raise HTTPException(422,'表头筛选格式无效')
    if not isinstance(filters,dict) or set(filters)-set(TYPES):raise HTTPException(422,'筛选字段无效')
    for key,rule in filters.items():
        if not isinstance(rule,dict) or set(rule)-{'contains','values','min','max','blank'}:raise HTTPException(422,'筛选条件无效')
        if rule.get('blank') not in (None,'only','exclude'):raise HTTPException(422,'空值筛选无效')
        if 'values' in rule and (not isinstance(rule['values'],list) or len(rule['values'])>100 or any(not isinstance(v,str) or len(v)>200 for v in rule['values'])):raise HTTPException(422,'筛选选项无效')
        if len(str(rule.get('contains','')))>200:raise HTTPException(422,'筛选文字过长')
        for bound in ('min','max'):
            if rule.get(bound) not in (None,'') and (TYPES[key]!='number' or numeric(rule[bound]) is None):raise HTTPException(422,'数值筛选范围无效')
        if rule.get('min') not in (None,'') and rule.get('max') not in (None,'') and numeric(rule['min'])>numeric(rule['max']):raise HTTPException(422,'筛选下限不能大于上限')
    return filters

def query_items(items,q='',filter='all',column_filters=None,sort_key='',sort_direction='asc',reviewing=False,version_state=None):
    filters=parse_filters(column_filters)
    if sort_key and sort_key not in TYPES:raise HTTPException(422,'排序字段无效')
    if sort_direction not in ('asc','desc'):raise HTTPException(422,'排序方向无效')
    rows=[]
    for row in items:
        r=row['result'];i=row['input']
        if q.casefold() not in (i['material_code']+' '+str(i.get('material_name') or '')).casefold():continue
        if filter=='delay' and not r.get('delay_replenishment'):continue
        if filter=='attention' and not business_warnings(row):continue
        if filter=='unexplained' and not submission_issues(i,r):continue
        if filter=='pending' and row.get('decision'):continue
        if filter=='returned' and not row.get('return_requested'):continue
        if filter=='air' and 'AIR' not in r['manual_flags']:continue
        if filter=='modified' and not row.get('adjustment'):continue
        if filter.startswith('abc:') and i.get('material_abc')!=filter.split(':',1)[1]:continue
        if filter in ('WITHIN','BELOW','ABOVE') and r['quantity_status']!=filter:continue
        if filter in ('MANUAL','EXEMPT') and r['review_mode']!=filter:continue
        if filter=='ERROR' and r['data_status']!='ERROR':continue
        if filter=='PENDING' and not r.get('basis_pending'):continue
        values=display_row(row, version_state);ok=True
        for key,rule in filters.items():
            value=numeric(values.get(key)) if TYPES[key]=='number' else values.get(key)
            blank=value is None or value==''
            if rule.get('blank')=='only' and not blank or rule.get('blank')=='exclude' and blank:ok=False;break
            if rule.get('contains') and str(rule['contains']).casefold() not in str(value if value is not None else '').casefold():ok=False;break
            if 'values' in rule and str(value if value is not None else '') not in rule['values']:ok=False;break
            for bound in ('min','max'):
                limit=rule.get(bound)
                if limit not in (None,'') and (blank or (value<numeric(limit) if bound=='min' else value>numeric(limit))):ok=False
        if ok:rows.append((row,values))
    if sort_key:
        def value(pair):
            raw=pair[1].get(sort_key)
            return numeric(raw) if TYPES[sort_key]=='number' else str(raw).casefold() if raw is not None else None
        present=[x for x in rows if value(x) not in (None,'')];missing=[x for x in rows if value(x) in (None,'')]
        rows=sorted(present,key=value,reverse=sort_direction=='desc')+missing
    elif reviewing:
        rows.sort(key=lambda pair:(9 if pair[0].get('decision') else 0 if pair[0]['result']['data_status']=='ERROR' or pair[0]['result']['manual_flags'] else 1 if pair[0]['result']['quantity_status']=='ABOVE' else 2 if pair[0]['result']['quantity_status']=='BELOW' else 3,pair[0]['input']['material_code']))
    return [r for r,_ in rows]

def column_options(items, version_state=None):
    options={key:set() for key,_,kind in COLUMNS if kind=='enum'}
    for row in items:
        values=display_row(row,version_state)
        for key,allowed in options.items():
            allowed.add(str(values.get(key) or ''))
    return {key:sorted(allowed) for key,allowed in options.items()}
