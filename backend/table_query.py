"""One table contract for paging, selection, and workbook export."""
import json
import operator
import re
from fastapi import HTTPException
from .rules import number, FLAG_LABELS, submission_issues, match_material_type
from .exceptions import approval_status, business_warnings
from .governance import effective_input

COLUMNS = [
 ('material_code','物料号','text'),('material_name','物料名称','text'),('material_abc','物料分类ABC','enum'),('vehicle_model','车型','text'),
 ('net_supply_before_plan','审核前净额','number'),('sea_plan_qty','海运计划','number'),('air_plan_qty','空运计划','number'),
 ('future_qty','未来库存','number'),('lower','库存下限','number'),('upper','库存上限','number'),
 ('status','系统结论','enum'),('attention','人工关注','text'),('m','月均销量最大值','number'),
 ('on_hand_months','在库周转（月）','number'),('pipeline_days','净库存周转（天）','number'),('future_days','补货后周转（天）','number'),
 ('turnover_warning','周转预警','enum'),('future_fleet_qty','未来装车量','number'),
 ('delay_replenishment','建议延迟补货','enum'),('advice','审批建议','text'),('vehicle_parc','备件保有量','number'),('source_note','备注','text'),('is_key_model','是否重点车型','enum'),
 ('avg_sales_3m','三个月月均销量','number'),('avg_sales_6m','六个月月均销量','number'),('fleet_qty','装车量','number'),
 ('on_hand_qty','在库数量','number'),('in_transit_qty','在途数量','number'),('on_order_qty','在订数量','number'),
 ('replacement_rate','稳态更换率','number'),('replacement_target','更换率目标库存','number'),('sales_target','销量目标库存','number'),
 ('decision','复审决定','enum'),('reason','计划说明','text'),('air_reason','空运说明','text'),('override','提交与终审记录','enum')]
TYPES={k:t for k,_,t in COLUMNS}
STATUS={'WITHIN':'合理','BELOW':'偏少','ABOVE':'偏多','ERROR':'数据错误','PENDING':'待补数据','MANUAL':'人工判断','EXEMPT':'免数量审核','UNAVAILABLE':'无法计算','NOT_APPLICABLE':'不适用'}
NUMBER_OPS = {'eq':operator.eq, 'ne':operator.ne, 'gt':operator.gt, 'ge':operator.ge, 'lt':operator.lt, 'le':operator.le}
TEXT_OPS = {'eq':operator.eq, 'ne':operator.ne, 'contains':operator.contains, 'not_contains':lambda v, t:t not in v,
            'starts':str.startswith, 'ends':str.endswith}

# Text filters, selections and exports must compare the same words shown in the table.
# Enum filters always use the original option value in either language.
_GENERATED_TEXT_EN = {
    '空运必要性待确认': 'Confirm the need for air freight',
    '特殊分类重叠': 'Special classifications overlap',
    '缺更换率且目标为零': 'Missing replacement rate and zero stock target',
    '仅调整海运无法达标': 'Adjusting sea freight alone cannot reach the target',
    '物料分类缺失': 'Missing material classification',
    '按市场需求人工判断': 'Assess market demand manually',
    '计划数据异常，请核实': 'Check the plan data',
    '小件免审核': 'Small parts are exempt from quantity review',
    '用品精品，按市场需求人工判断': 'Assess accessory demand manually',
    '备货合理': 'Stock within range',
    '需人工复审': 'Manual review required',
    '建议延迟补货': 'Delay replenishment',
    '周转过低预警': 'Low stock cover alert',
    '周转过高预警': 'High stock cover alert',
}
_QUANTITY_ADVICE = re.compile(r'^(备货多，建议减少|备货少，建议增加)([\d,.]+)(.*)$')


def english_table_text(value):
    if not value:
        return ''
    parts = []
    for part in value.split('；'):
        match = _QUANTITY_ADVICE.fullmatch(part)
        if match:
            action, amount, unit = match.groups()
            prefix = 'Excess stock. Reduce by' if action == '备货多，建议减少' else 'Low stock. Increase by'
            parts.append(' '.join(v for v in (prefix, amount, unit) if v))
        else:
            parts.append(_GENERATED_TEXT_EN.get(part, part))
    return '; '.join(parts)


def numeric(v):
    try:return number(v)
    except ValueError:return None

def decision_label(decision, version_state=None, return_requested=False):
    status = (decision or {}).get('status')
    if status:
        return {'APPROVED':'已批准','BATCH_APPROVED':'整批通过','EXCEPTION_APPROVED':'例外批准','REJECTED':'不批准','RETURNED':'退回修改'}.get(status,status)
    if version_state == 'DRAFT':
        return '需修改' if return_requested else '未提交'
    if version_state in ('RETURNED','VOID','APPROVED','PARTIALLY_APPROVED','REJECTED'):
        return '未复审'
    return '待复审'


def display_row(row, version_state=None):
    i=effective_input(row);r=row['result'];d=row.get('decision') or {}
    status=r['data_status'] if r['data_status'] in ('ERROR','PENDING') else r['review_mode'] if r['review_mode']!='AUTO' else r['quantity_status']
    values={**i,**r,'status':STATUS.get(status,status),'attention':'；'.join(FLAG_LABELS.get(f,f) for f in r['manual_flags']),
            'is_key_model':'是' if i.get('is_key_model') is True else '否' if i.get('is_key_model') is False else None,
            'decision':decision_label(d, version_state, row.get('return_requested')),
            'override':'例外终审' if d.get('forced') else '提交时有提醒' if (row.get('submission_override') or {}).get('mode')=='advisory' else '带问题提交' if row.get('submission_override') else '无'}
    values['delay_replenishment'] = {True:'是', False:'否'}.get(r.get('delay_replenishment'))
    for key in ('on_hand_months', 'pipeline_days', 'future_days'):
        values[key] = r.get(key)
    return values

def table_item(row, version_state, compact=False, package=None):
    source = effective_input(row)
    if row['result'].get('basis_pending') and package is not None:
        # A quantity-only plan has no inventory calculation, but its frozen
        # standard can still identify material types from a code or name.
        hits, override = match_material_type(source, package)
        row = {**row, 'result':{**row['result'], 'matched_keywords':hits, 'override':override}}
    values = display_row(row, version_state)
    if not compact:
        return {**row, 'input':source, 'table_values':values, 'approval_status':approval_status(row['result'])}
    # The drawer loads its own full item. Omit history, snapshots and repeated
    # calculation inputs from the paged table response, especially for 全部.
    input_keys = ('material_code','material_name','material_abc','large_value_flag','quantity_step','sea_plan_qty','air_plan_qty')
    result_keys = ('data_status','review_mode','quantity_status','m','advice','turnover_warning','delay_replenishment','matched_keywords','override')
    item = {key:row[key] for key in ('id','decision','return_requested','return_reason') if key in row}
    if row.get('submission_override'):
        item['submission_override'] = {'mode':row['submission_override'].get('mode')}
    return {**item, 'input':{k:source[k] for k in input_keys if k in source},
            'result':{k:row['result'][k] for k in result_keys if k in row['result']},
            'table_values':{k:values[k] for k in TYPES if k in values}}

def parse_filters(filters):
    try:filters=json.loads(filters) if isinstance(filters,str) else filters or {}
    except (ValueError,TypeError):raise HTTPException(422,'表头筛选格式无效')
    if not isinstance(filters,dict) or set(filters)-set(TYPES):raise HTTPException(422,'筛选字段无效')
    for key,rule in filters.items():
        if not isinstance(rule,dict) or set(rule)-{'contains','values','min','max','blank','op','term','lang'}:raise HTTPException(422,'筛选条件无效')
        if 'lang' in rule and (key not in ('attention','advice') or rule['lang'] != 'en' or not isinstance(rule.get('op'), str) or rule['op'] not in TEXT_OPS):
            raise HTTPException(422, '筛选条件无效')
        if rule.get('blank') not in (None,'only','exclude'):raise HTTPException(422,'空值筛选无效')
        if 'values' in rule and (not isinstance(rule['values'],list) or len(rule['values'])>100 or any(not isinstance(v,str) or len(v)>200 for v in rule['values'])):raise HTTPException(422,'筛选选项无效')
        if len(str(rule.get('contains','')))>200:raise HTTPException(422,'筛选文字过长')
        for bound in ('min','max'):
            if rule.get(bound) not in (None,'') and (TYPES[key]!='number' or numeric(rule[bound]) is None):raise HTTPException(422,'数值筛选范围无效')
        if rule.get('min') not in (None,'') and rule.get('max') not in (None,'') and numeric(rule['min'])>numeric(rule['max']):raise HTTPException(422,'筛选下限不能大于上限')
        if 'op' in rule or 'term' in rule:
            op, term = rule.get('op'), rule.get('term')
            if not isinstance(op, str) or term in ('', None) or not isinstance(term, (str, int, float)) or len(str(term)) > 200:
                raise HTTPException(422, '请填写有效筛选条件')
            if TYPES[key] == 'number':
                if op not in NUMBER_OPS or numeric(term) is None:
                    raise HTTPException(422, '数值比较条件无效')
            elif TYPES[key] != 'text' or op not in TEXT_OPS:
                raise HTTPException(422, '文字比较条件无效')
    return filters

def matches_rule(value, kind, rule):
    if isinstance(value, tuple):
        return any(matches_rule(label, kind, rule) for label in value)
    if kind == 'number':
        value = numeric(value)
    if rule.get('lang') == 'en':
        value = english_table_text(value)
    blank = value in (None, '')
    if rule.get('blank') == 'only':
        return blank
    if blank and rule.get('blank') == 'exclude':
        return False
    text = '' if blank else str(value)
    if 'values' in rule and text not in rule['values']:
        return False
    if rule.get('contains') and str(rule['contains']).casefold() not in text.casefold():
        return False
    if rule.get('op'):
        if blank:
            return False
        if kind == 'number':
            return NUMBER_OPS[rule['op']](value, numeric(rule['term']))
        return TEXT_OPS[rule['op']](text.casefold(), str(rule['term']).casefold())
    for key, compare in (('min', operator.ge), ('max', operator.le)):
        if rule.get(key) not in ('', None) and (blank or not compare(value, numeric(rule[key]))):
            return False
    return True

def query_items(items,q='',filter='all',column_filters=None,sort_key='',sort_direction='asc',reviewing=False,version_state=None,facets=None):
    filters=parse_filters(column_filters)
    if sort_key and sort_key not in TYPES:raise HTTPException(422,'排序字段无效')
    if sort_direction not in ('asc','desc'):raise HTTPException(422,'排序方向无效')
    rows=[]
    for row in items:
        r=row['result'];i=effective_input(row)
        if q.casefold() not in (i['material_code']+' '+str(i.get('material_name') or '')).casefold():continue
        if filter=='delay' and not r.get('delay_replenishment'):continue
        if filter=='turnover' and not r.get('turnover_warning'):continue
        if filter=='attention' and not business_warnings(row):continue
        if filter=='unexplained' and not submission_issues(i,r):continue
        if filter=='pending' and row.get('decision'):continue
        if filter=='returned' and not row.get('return_requested'):continue
        if filter=='return_marked' and (row.get('decision') or {}).get('status')!='RETURNED':continue
        if filter=='rejected' and (row.get('decision') or {}).get('status')!='REJECTED':continue
        if filter=='air' and 'AIR' not in r['manual_flags']:continue
        if filter=='modified' and not row.get('adjustment'):continue
        if filter.startswith('abc:') and i.get('material_abc')!=filter.split(':',1)[1]:continue
        if filter in ('WITHIN','BELOW','ABOVE') and r['quantity_status']!=filter:continue
        if filter in ('MANUAL','EXEMPT') and r['review_mode']!=filter:continue
        if filter=='ERROR' and r['data_status']!='ERROR':continue
        if filter=='PENDING' and not r.get('basis_pending'):continue
        values=display_row(row, version_state)
        # The system conclusion cell can show a primary decision and two warnings.
        # Selecting several displayed labels is a union, as for other checklists.
        status_labels=tuple(v for v in (values['status'],r.get('turnover_warning'),'建议延迟补货' if r.get('delay_replenishment') else None) if v)
        failed=[key for key,rule in filters.items() if not matches_rule(status_labels if key=='status' else values.get(key), TYPES[key], rule)]
        if facets is not None and len(failed) <= 1:
            # Each dropdown reflects the other active conditions while allowing its own selection to be changed.
            for key in failed or facets:
                if key=='status' and key in facets:
                    facets[key].update(status_labels)
                elif key in facets:
                    facets[key].add(str(values.get(key) or ''))
        if not failed:rows.append((row,values.get(sort_key)))
    if sort_key:
        def value(pair):
            raw=pair[1]
            return numeric(raw) if TYPES[sort_key]=='number' else str(raw).casefold() if raw is not None else None
        present=[x for x in rows if value(x) not in (None,'')];missing=[x for x in rows if value(x) in (None,'')]
        rows=sorted(present,key=value,reverse=sort_direction=='desc')+missing
    elif reviewing:
        rows.sort(key=lambda pair:(9 if pair[0].get('decision') else 0 if pair[0]['result']['data_status']=='ERROR' or pair[0]['result']['manual_flags'] else 1 if pair[0]['result']['quantity_status']=='ABOVE' else 2 if pair[0]['result']['quantity_status']=='BELOW' else 3,pair[0]['input']['material_code']))
    elif version_state=='DRAFT':
        rows.sort(key=lambda pair:not pair[0].get('return_requested'))
    return [r for r,_ in rows]

