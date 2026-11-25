"""Editable numeric formulas plus frozen audit evidence, with truthful initial caches."""
from io import BytesIO
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET
import json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from .rules import number, default_package, corrected_v3, FLAG_LABELS, PARAM_LABELS, MODEL_V2, MODEL_V3, REASON_LABELS
from .table_query import decision_label
from .governance import effective_input

COLS=[('material_code','物料号'),('material_name','物料名称'),('sea_plan_qty','海运计划'),('air_plan_qty','空运计划'),('net_supply_before_plan','审核前净额'),('future_qty','未来库存（公式）'),('lower','库存下限（公式）'),('upper','库存上限（公式）'),('quantity_status','系统数量结论（公式）'),('review_mode','审核方式'),('data_status','数据状态（公式）'),('manual_flags','审核时人工关注'),('suggested_sea_qty','建议海运量（公式）'),('residual_excess','剩余超储（公式）'),('reason','计划说明'),('air_reason','空运说明'),('decision','人工决定（留档）'),('reviewer_name','审核人'),('review_reason','复审依据'),('replacement_target','更换率目标库存'),('sales_target','销量目标库存'),('reason_code','计划原因类别'),('review_reason_code','复审原因类别'),('source_file','基础数据文件'),('source_row','基础数据行'),('plan_file','计划文件'),('plan_row','计划源行'),('material_abc','物料分类ABC'),('is_key_model','是否重点车型'),('fleet_qty','装车量'),('avg_sales_3m','三个月月均销量'),('avg_sales_6m','六个月月均销量'),('m','月均销量最大值（公式）'),('pipeline_days','管道库存可用周转天数（口径待确认）'),('future_days','下单后周转天数（口径待确认）'),('on_hand_qty','在库数量'),('replacement_rate','稳态更换率'),('quantity_step','订货步长'),('material_type','物料类型'),('original_status','审核时数量结论（留档）'),('original_data','审核时数据状态（留档）'),('original_lower','审核时库存下限（留档）'),('original_upper','审核时库存上限（留档）'),('original_future','审核时未来库存（留档）'),('submission_reason','带问题提交说明'),('submission_user','提交确认人'),('submission_at','提交确认时间'),('final_exception','例外终审说明'),('in_transit_qty','在途数量'),('on_order_qty','在订数量'),('uom','计量单位')]
NUMERIC={'sea_plan_qty','air_plan_qty','net_supply_before_plan','future_qty','lower','upper','suggested_sea_qty','residual_excess','replacement_target','sales_target','source_row','plan_row','fleet_qty','avg_sales_3m','avg_sales_6m','m','on_hand_qty','replacement_rate','quantity_step','original_lower','original_upper','original_future','in_transit_qty','on_order_qty'}
TEXT={'WITHIN':'合理','BELOW':'偏少','ABOVE':'偏多','NOT_APPLICABLE':'不适用','UNAVAILABLE':'无法计算','AUTO':'规则计算','MANUAL':'人工判断','EXEMPT':'免数量审核','VALID':'有效','WARNING':'需关注','ERROR':'数据错误','PENDING':'待补数据','APPROVED':'已批准','BATCH_APPROVED':'整批通过','EXCEPTION_APPROVED':'例外批准'}

def n(v):
    try:return number(v)
    except ValueError:return None

def literal(cell,value,numeric=False):
    parsed=n(value) if numeric else None
    if parsed is not None:cell.value=float(parsed)
    elif value is None:cell.value=None
    else:cell.value=str(value);cell.data_type='s'

def cached_book(wb,caches):
    raw=BytesIO();wb.save(raw);wb.close();out=BytesIO();ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with ZipFile(raw) as source,ZipFile(out,'w',ZIP_DEFLATED) as target:
        for entry in source.infolist():
            data=source.read(entry.filename)
            if entry.filename in caches:
                root=ET.fromstring(data)
                for cell in root.findall('.//{'+ns+'}c'):
                    if cell.get('r') not in caches[entry.filename]:continue
                    val=caches[entry.filename][cell.get('r')];v=cell.find('{'+ns+'}v')
                    if v is None:v=ET.SubElement(cell,'{'+ns+'}v')
                    if val is None:cell.set('t','str');v.text=''
                    elif isinstance(val,bool):cell.set('t','b');v.text='1' if val else '0'
                    elif isinstance(val,(Decimal,float,int)):cell.set('t','n');v.text=str(val)
                    else:cell.set('t','str');v.text=str(val)
                data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            target.writestr(entry,data)
    return out.getvalue()

V2_COLUMNS = [
    ('vehicle_model', '车型'), ('vehicle_parc', '备件保有量'), ('on_hand_months', '在库周转（月）'),
    ('delay_replenishment', '建议延迟补货'), ('advice', '审批建议'), ('source_note', '备注'),
]

CLASS_GROUPS = (('small','小件'),('no_stock','不备货'),('manual','用品精品'),('maintenance','保养件'),('dangerous','危包'))


def write_v3_rule_inputs(params, calc, package):
    ranges = {}
    for index, (key, label) in enumerate(CLASS_GROUPS, 5):
        column = get_column_letter(index)
        params.cell(1, index, label+'关键词')
        words = package['keywords'].get(key, [])
        for row, value in enumerate(words, 2):
            literal(params.cell(row, index), value)
        ranges[key] = f"'规则参数'!${column}$2:${column}${max(2, len(words)+1)}"
    params['K1'], params['L1'] = '指定物料号', '指定审核类型'
    for row, (code, kind) in enumerate(package.get('overrides', {}).items(), 2):
        literal(params.cell(row, 11), code)
        literal(params.cell(row, 12), kind)
    last = max(2, len(package.get('overrides', {}))+1)
    ranges['override_codes'] = f"'规则参数'!$K$2:$K${last}"
    ranges['override_types'] = f"'规则参数'!$L$2:$L${last}"
    headers = [*(f'前 {j} 月销量' for j in range(6, 0, -1)), '销量月份（早到晚）',
               *(label+'关键词命中' for _, label in CLASS_GROUPS), '指定审核类型', '需求抵扣数量', '更换率储备月数', '销量储备月数', '来源更换率目标', '来源销量目标', '核定稳态更换率']
    for col, label in enumerate(headers, 14):
        calc.cell(1, col, label)
    return ranges


def write_target_formulas(ws, calc, idx, row, formula):
    basis=row['result'].get('master_basis') or {}
    item=effective_input(row)
    source=row['input']
    if 'replacement_rate' in basis.get('master_fields',[]):
        rate_ref=f"'计算依据'!AF{idx}"
        literal(calc.cell(idx,32),item.get('replacement_rate'),True)
        formula(ws,f'AK{idx}',f'IF(EXACT(A{idx},\'计算依据\'!A{idx}),{rate_ref},"")',n(item.get('replacement_rate')))
    funcs={'up':'ROUNDUP','nearest':'ROUND','down':'ROUNDDOWN'}
    for key,detail in basis.get('targets',{}).items():
        replacement=key=='replacement_target'
        target='T' if replacement else 'U'
        period_col,source_col=(28,30) if replacement else (29,31)
        literal(calc.cell(idx,period_col),detail['months'],True)
        master=basis.get('source_targets',{})
        literal(calc.cell(idx,source_col),master.get(key,source.get(key)),True)
        period=f"'计算依据'!{get_column_letter(period_col)}{idx}"
        fallback=f"'计算依据'!{get_column_letter(source_col)}{idx}"
        refs=[f'AK{idx}',f'AD{idx}'] if replacement else [{'3m':'AE','6m':'AF','max':'AG'}[detail['window']]+str(idx)]
        if replacement and 'replacement_rate' not in basis['master_fields']: continue
        operands=','.join([*refs,period])
        body='*'.join([*refs,period])
        rounding=funcs.get(detail['rounding'])
        if rounding: body=f'{rounding}({body},0)'
        expr=f'IF(AND(COUNT({operands})={len(refs)+1},MIN({operands})>=0),{body},IF(ISBLANK({fallback}),"",{fallback}))'
        formula(ws,target+str(idx),expr,n(item.get(key)))


def write_v3_row_inputs(ws, calc, row, item, result, formula, ranges, net_mode):
    months = item.get('monthly_sales') or {}
    labels = item.get('month_labels') or list(months)
    if isinstance(months, dict) and len(labels) == 6:
        for col, label in enumerate(labels, 14):
            literal(calc.cell(row, col), months.get(label), True)
        literal(calc.cell(row, 20), ' / '.join(map(str, labels)))
        for target, start, field in [('AE','Q','avg_sales_3m'),('AF','N','avg_sales_6m')]:
            source = f"'计算依据'!{start}{row}:S{row}"
            invalid = f'OR(COUNT({source})+COUNTBLANK({source})<>COLUMNS({source}),MIN({source})<0)'
            expr = f'IF({invalid},"月销量无效，请核对六个月明细",IF(COUNT({source})=0,"",AVERAGE({source})))'
            cached = item.get(field)
            numeric = n(cached)
            formula(ws, f'{target}{row}', expr, numeric if numeric is not None else cached)
    if net_mode == 'COMPONENTS':
        literal(calc.cell(row, 27), item.get('demand_deduction_qty'), True)
        demand = f"'计算依据'!AA{row}"
        expr = f'IF(COUNT(AJ{row},AW{row},AX{row},{demand})=4,AJ{row}+AW{row}+AX{row}-{demand},"")'
        formula(ws, f'E{row}', expr, n(item.get('net_supply_before_plan')))
    base = f"'计划审核结果'!B{row}&'计划审核结果'!AM{row}"
    override = result.get('override')
    match_code = f'MATCH(TRUE,INDEX(EXACT(A{row},{ranges["override_codes"]}),0),0)'
    lookup = f'IFERROR(INDEX({ranges["override_types"]},{match_code}),"")'
    formula(calc, f'Z{row}', lookup, override)
    for pos, (key, _) in enumerate(CLASS_GROUPS):
        text = base + (f"&'计划审核结果'!AB{row}" if key == 'maintenance' else '')
        words = ranges[key]
        raw = f'{get_column_letter(21+pos)}{row}'
        match = f'SUMPRODUCT(--({words}<>""),--ISNUMBER(FIND(LOWER({words}),LOWER({text}))))>0'
        hit = bool(result.get('matched_keywords', {}).get(key))
        formula(calc, raw, match, hit)
        formula(calc, f'{get_column_letter(2+pos)}{row}', f'IF(Z{row}="",--{raw},--(Z{row}="{key}"))',
                int(override == key if override else hit))


APPROVALS = frozenset(('APPROVED','EXCEPTION_APPROVED','BATCH_APPROVED'))
EXECUTION_FORMAT = 1
EXECUTION_COLUMNS = [('plan_outcome','整单结论'),('executable_sea','本版可执行海运量'),('executable_air','本版可执行空运量')]
ARCHIVE_COLUMNS = [('historical_sea','历史核准海运量（旧规则）'),('historical_air','历史核准空运量（旧规则）')]


def execution_basis(state, rows, current):
    """Use the complete version before selecting any visible output rows."""
    statuses = [(row.get('decision') or {}).get('status') for row in rows]
    all_approved = bool(statuses) and all(status in APPROVALS for status in statuses)
    approved = state=='APPROVED' and all_approved and current
    label = {'DRAFT':'草稿','SUBMITTED':'待复审','IN_REVIEW':'复审中','RETURNED':'整单退回','VOID':'已作废',
             'APPROVED':'整单通过','REJECTED':'整单不批准','PARTIALLY_APPROVED':'历史结案（旧规则）'}.get(state,'待核实')
    if state=='APPROVED' and not approved:
        label = '历史版本（整单通过）' if not current else '整单记录待核'
    return {'state':state,'current':current,'total':len(statuses),'has_review':any(statuses),'executable':approved,'label':label}


def old_export_requires_refresh(payload, result, full_version=None):
    if result.get('execution_format')==EXECUTION_FORMAT:
        return False
    state = (payload.get('metadata') or {}).get('版本状态')
    if state=='PARTIALLY_APPROVED':
        return True
    if state=='APPROVED':
        rows=full_version.items if full_version else payload.get('items',[])
        return any((row.get('decision') or {}).get('status') in ('REJECTED','RETURNED') for row in rows)
    # In the old format REJECTED could carry signed positive quantities on approved rows.
    return state=='REJECTED' and any((row.get('decision') or {}).get('status') in APPROVALS and
        any((n(row['input'].get(k)) or 0)>0 for k in ('sea_plan_qty','air_plan_qty'))
        for row in payload.get('items',[]))


def export_workbook(payload, files=None):
    package=payload.get('rule_package')
    if not package:
        raw=payload.get('metadata',{}).get('规则参数')
        results = [row['result'] for row in payload['items']]
        model = MODEL_V3 if any('turnover_warning' in r for r in results) else MODEL_V2 if any('advice' in r for r in results) else '0804'
        package=json.loads(raw) if raw else default_package(model)
        if not raw and model == MODEL_V3 and not any(r.get('v3_revision') for r in results):
            package.pop('v3_revision', None)  # Historical export jobs predate rule-package capture.
    wb=Workbook();ws=wb.active;ws.title='计划审核结果';meta=wb.create_sheet('版本与来源');params=wb.create_sheet('规则参数');calc=wb.create_sheet('计算依据')
    wb.calculation=CalcProperties(calcMode='auto',fullCalcOnLoad=True,forceFullCalc=True)
    v3 = package.get('model') == MODEL_V3
    current_v3 = corrected_v3(package)
    v2 = package.get('model') in (MODEL_V2, MODEL_V3)
    columns = COLS
    if v2:
        labels = {'pipeline_days':'净库存周转（天）', 'future_days':'补货后周转（天）'}
        columns = [(k, labels.get(k, title)) for k,title in COLS] + V2_COLUMNS
    if v3:
        columns += [('future_fleet_qty','未来装车量'), ('turnover_warning','周转预警（公式）')]
    metadata = payload.get('metadata',{})
    state = metadata.get('版本状态')
    basis = payload.get('execution')
    if not basis:
        # Jobs queued before this format have no proof of their complete, current version.
        basis = execution_basis(state,[],False)
        if state=='APPROVED':
            basis['label']='归档导出（整单通过，执行量待核）'
    if metadata.get('复审负责人') or state in ('IN_REVIEW','APPROVED','REJECTED','PARTIALLY_APPROVED','RETURNED') or any(row.get('return_reason') for row in payload['items']):
        columns = [*columns, ('return_reason','上轮退回原因')]
    reviewed_draft = state=='DRAFT' and (basis['has_review'] or any(row.get('return_requested') for row in payload['items']))
    if reviewed_draft or state in ('SUBMITTED','IN_REVIEW','APPROVED','REJECTED','PARTIALLY_APPROVED','RETURNED','VOID'):
        columns = [*columns, *EXECUTION_COLUMNS]
    if state=='PARTIALLY_APPROVED':
        columns = [*columns, *ARCHIVE_COLUMNS]
    if current_v3:
        columns += [('current_sales','当月销量（必填）'),('shortage_qty','缺货数量（必填）')]
    column_letters = {key:get_column_letter(index) for index,(key,_) in enumerate(columns,1)}
    ws.append([label for _,label in columns]);params.append(['参数','值','字段'])
    param_refs={}
    for key,value in package['params'].items():
        params.append([PARAM_LABELS.get(key,key),value,key]);literal(params.cell(params.max_row,2),value,True);param_refs[key]=f"'规则参数'!$B${params.max_row}"
    calc.append(['物料号','小件命中','不备货命中','人工类命中','保养件命中','危包命中','规则分支（公式）','原始下限（公式）','原始上限（公式）','数据错误（公式）','海运下界（公式）','海运上界（公式）','海运范围可行（公式）'])
    v3_ranges = write_v3_rule_inputs(params, calc, package) if v3 else {}
    caches={'xl/worksheets/sheet1.xml':{},'xl/worksheets/sheet4.xml':{}}
    formula_fill=PatternFill('solid',fgColor='E7F1FB')
    def formula(sheet,coord,text,value):
        sheet[coord]='='+text
        if sheet is ws and v3: sheet[coord].fill=formula_fill
        caches['xl/worksheets/sheet1.xml' if sheet is ws else 'xl/worksheets/sheet4.xml'][coord]=value
    for idx,row in enumerate(payload['items'],2):
        i=effective_input(row);r=row['result'];d=row.get('decision') or {};o=row.get('submission_override') or {}
        defaults = {} if r.get('basis_pending') else {'quantity_step':1,'uom':'PCS'}
        values={**defaults,**i,**r,'decision':decision_label(d,payload.get('metadata',{}).get('版本状态'),row.get('return_requested')),'reviewer_name':d.get('reviewer_name'),'review_reason':d.get('reason'),'review_reason_code':d.get('reason_code'),
            'source_file':i.get('source',{}).get('file'),'source_row':i.get('source',{}).get('row'),'plan_file':i.get('plan_source',{}).get('file'),'plan_row':i.get('plan_source',{}).get('row'),
            'original_status':r['quantity_status'],'original_data':r['data_status'],'original_lower':r['lower'],'original_upper':r['upper'],'original_future':r['future_qty'],
            'submission_reason':o.get('reason'),'submission_user':o.get('user_name'),'submission_at':o.get('at'),'final_exception':d.get('reason') if d.get('forced') else None,
            'pipeline_days':None,'future_days':None,'is_key_model':'是' if i.get('is_key_model') is True else '否' if i.get('is_key_model') is False else None}
        values['plan_outcome'] = basis['label']
        for transport in ('sea','air'):
            qty=n(i.get(transport+'_plan_qty'))
            approved_line=d.get('status') in APPROVALS
            values['executable_'+transport] = qty if state=='APPROVED' and basis['executable'] and approved_line else 0
            if state=='PARTIALLY_APPROVED':
                values['historical_'+transport] = qty if approved_line else 0 if d.get('status')=='REJECTED' else None
        values['return_reason'] = row.get('return_reason')
        for col,(key,_) in enumerate(columns,1):
            v=values.get(key)
            if key in ('reason_code','review_reason_code') and isinstance(v,str):v=REASON_LABELS.get(v,v)
            if key=='manual_flags':v='；'.join(FLAG_LABELS.get(f,f) for f in v or [])
            if key in ('quantity_status','review_mode','data_status','decision','original_status','original_data'):v=TEXT.get(v,v)
            literal(ws.cell(idx,col),v,key in NUMERIC or key in ('vehicle_parc','future_fleet_qty','executable_sea','executable_air','historical_sea','historical_air','current_sales','shortage_qty'))
        if v3: write_target_formulas(ws,calc,idx,row,formula)
        if r.get('basis_pending'):
            literal(calc.cell(idx,1),i['material_code'])
            continue
        hits=r.get('matched_keywords',{});override=r.get('override')
        flags=[override==key if override else bool(hits.get(key)) for key in ('small','no_stock','manual','maintenance','dangerous')]
        for col,value in enumerate([i['material_code'],*[int(v) for v in flags]],1): calc.cell(idx,col,value)
        calc.cell(idx,1).data_type='s'
        if v3:
            write_v3_row_inputs(ws, calc, idx, i, r, formula, v3_ranges, payload.get('net_mode'))
            mode = f'IF(\'计算依据\'!B{idx}=1,"免数量审核",IF(\'计算依据\'!D{idx}=1,"人工判断","规则计算"))'
            formula(ws, f'J{idx}', mode, TEXT[r['review_mode']])
        R=lambda c:f"'计划审核结果'!{c}{idx}"
        P=lambda k:param_refs[k]
        g,m,x,y,w,key,step,t,sea,air=map(R,('AD','AG','T','U','AK','AC','AL','E','C','D'))
        fixed=f'IF({R("AB")}="A",{P("fixed_ab")},IF({R("AB")}="B",{P("fixed_ab")},{P("fixed_non_ab")}))'
        ratio_test = f'MAX({x},{y})>{P("target_ratio_threshold")}*MIN({x},{y})' if v2 else f'{x}>{P("target_ratio_threshold")}*{y}'
        regular=f'IF(COUNT({m},{x})<>2,"",IF({m}=0,IF(ISNUMBER({g}),IF({g}<{P("fleet_low_threshold")},"UK-R06","UK-R07"),""),IF(ISNUMBER({y}),IF({ratio_test},"UK-R08","UK-R09"),"")))'
        maintenance=f'IF(COUNT({g},{m})<>2,"",IF(OR({g}<{P("fleet_low_threshold")},{m}=0),"UK-R03","UK-R04"))'
        danger=f'AND(F{idx}=1,NOT(AND(ISNUMBER({g}),{g}>{P("dangerous_fleet_threshold")},ISNUMBER({w}),{w}>0)))'
        branch=f'IF(B{idx}=1,"UK-R01",IF(C{idx}=1,"UK-R02",IF(AND(D{idx}=1,COUNT({g},{m},{x},{y})<>4),"",IF(E{idx}=1,{maintenance},IF({danger},IF(ISNUMBER({g}),"UK-R05",""),{regular})))))'
        formula(calc,f'G{idx}',branch,r.get('rule_id') or '')
        lo={'01':'0','02':'0','03':f'MIN({P("maintenance_fixed")},{g}*{P("maintenance_fleet_low_ratio")})','04':f'{m}*{P("maintenance_lower_months")}','05':f'MIN({g}*{P("dangerous_ratio")},{P("dangerous_fixed")})','06':fixed,'07':f'MIN({x},{fixed})','08':f'MIN({x},{y})','09':f'MIN({x},{y})'}
        hi={'01':P('small_display_upper'),'02':'0','03':f'MAX({P("maintenance_fixed")},{g}*{P("maintenance_fleet_low_ratio")})','04':f'MAX({m}*{P("maintenance_upper_months")},{g}*{P("maintenance_fleet_high_ratio")})','05':f'MAX({g}*{P("dangerous_ratio")},{P("dangerous_fixed")})','06':f'MAX({x},{fixed})','07':f'MAX({x},{fixed})','08':f'{m}*IF({key}="是",{P("upper_months_key")},{P("upper_months_non_key")})','09':f'MAX({x},{y})'}
        if v2:
            hi['08'] = f'MAX({hi["08"]},MIN({x},{y}))'
        for col,choices,cached in [('H',lo,r.get('lower_raw')),('I',hi,r.get('upper_raw'))]:
            expr='""'
            for code,body in reversed(list(choices.items())):expr=f'IF(G{idx}="UK-R{code}",{body},{expr})'
            formula(calc,f'{col}{idx}',expr,n(cached))
        formula(ws,f'AG{idx}',f'IF(COUNT(AE{idx},AF{idx})=2,MAX(AE{idx},AF{idx}),"")',n(r.get('m')))
        supply_col = 'AJ' if v3 and not current_v3 else 'D'
        supply_ref = R(supply_col)
        formula(ws,f'F{idx}',f'IF(COUNT(E{idx},C{idx},{supply_col}{idx})=3,E{idx}+C{idx}+{supply_col}{idx},"")',n(r.get('future_qty')))
        for col,raw in [('G','H'),('H','I')]:
            ref=f"'计算依据'!{raw}{idx}"
            formula(ws,f'{col}{idx}',f'IF(ISNUMBER({ref}),ROUND(ROUND({ref},10),0),"")',n(r.get('lower' if col=='G' else 'upper')))
        # Live validation for source fields. Missing optional values stay distinct from zero.
        errors=[f'{R("A")}=""',f'AND({R("B")}="",{R("AM")}="")',f'COUNT({t},{sea},{air},{step})<>4',f'{sea}<0',f'{air}<0',f'{step}<=0',f'ROUND({sea}/{step},10)<>ROUND({sea}/{step},0)',f'ROUND({air}/{step},10)<>ROUND({air}/{step},0)',f'{w}>1',f'AND(G{idx}="",D{idx}<>1)',f'AND(G{idx}="UK-R08",{key}<>"是",{key}<>"否")',f'AND(ISNUMBER({R("G")}),ISNUMBER({R("H")}),{R("G")}>{R("H")})']
        for field in ('AD','AE','AF','AK','T','U') + (('AJ','BA') if v2 else ()):
            ref=R(field);errors.append(f'AND({ref}<>"",OR(NOT(ISNUMBER({ref})),{ref}<0))')
        if current_v3:
            for field in ('current_sales','shortage_qty'):
                ref = R(column_letters[field])
                errors.append(f'OR(NOT(ISNUMBER({ref})),{ref}<0)')
        elif v3:
            errors.append(f'NOT(ISNUMBER({supply_ref}))')
        errors.append('AND('+','.join(f'{R("AY")}<>"{u}"' for u in ('PCS','EA','SET','L','KG','M'))+')')
        formula(calc,f'J{idx}','IFERROR(OR('+','.join(errors)+'),TRUE)',r['data_status']=='ERROR')
        error=f"'计算依据'!J{idx}";manual=f"OR('计算依据'!B{idx}=1,'计算依据'!D{idx}=1)"
        formula(ws,f'I{idx}',f'IF({error},"无法计算",IF({manual},"不适用",IF(F{idx}<G{idx},"偏少",IF(F{idx}>H{idx},"偏多","合理"))))',TEXT[r['quantity_status']])
        branch_ref=f"'计算依据'!G{idx}"
        warn=f'OR(AND(OR({branch_ref}="UK-R06",{branch_ref}="UK-R07",{branch_ref}="UK-R08",{branch_ref}="UK-R09"),AB{idx}=""),AND(OR({branch_ref}="UK-R08",{branch_ref}="UK-R09"),OR(AK{idx}="",AK{idx}=0),T{idx}=0))'
        formula(ws,f'K{idx}',f'IF({error},"数据错误",IF({warn},"需关注","有效"))',TEXT[r['data_status']])
        usable=not r['errors'] and r['review_mode']=='AUTO';low=high=None
        if usable:
            base=n(i['net_supply_before_plan'])+n(i['on_hand_qty' if supply_col=='AJ' else 'air_plan_qty']);st=n(i.get('quantity_step',1))
            low=(max(Decimal(0),n(r['lower'])-base)/st).to_integral_value(rounding=ROUND_CEILING)*st
            high=((n(r['upper'])-base)/st).to_integral_value(rounding=ROUND_FLOOR)*st
        gate=f'OR(J{idx},B{idx}=1,D{idx}=1)'
        formula(calc,f'K{idx}',f'IF({gate},"",ROUNDUP(MAX(0,{R("G")}-{t}-{supply_ref})/{step},0)*{step})',low)
        formula(calc,f'L{idx}',f'IF({gate},"",INT(({R("H")}-{t}-{supply_ref})/{step})*{step})',high)
        formula(calc,f'M{idx}',f'IF(COUNT(K{idx},L{idx})=2,L{idx}>=K{idx},FALSE)',r['sea_feasible'] is True)
        a,b,c=(f"'计算依据'!{col}{idx}" for col in ('K','L','M'))
        formula(ws,f'M{idx}',f'IF(COUNT({a},{b})<>2,"",IF({c},MIN(MAX(C{idx},{a}),{b}),0))',n(r.get('suggested_sea_qty')))
        formula(ws,f'N{idx}',f'IF(COUNT({a},{b})<>2,"",IF({c},0,MAX(0,E{idx}+{supply_col}{idx}-H{idx})))',n(r.get('residual_excess')))
        if v2:
            for column, field, source, factor in (('BB','on_hand_months','AJ',1), ('AH','pipeline_days','E',30), ('AI','future_days','F',30)):
                qty = f'{source}{idx}'
                expr = f'IF(NOT(ISNUMBER(AG{idx})),"",IF(AG{idx}=0,"无销量",IF(ISNUMBER({qty}),{qty}/AG{idx}*{factor},"")))'
                formula(ws, f'{column}{idx}', expr, '无销量' if n(r.get('m'))==0 else n(r.get(field)))
            small = f"'计算依据'!B{idx}=1"
            maintenance = f"'计算依据'!E{idx}=1"
            small_result = f'IF(COUNT(E{idx},AF{idx})<2,"",IF(AND(E{idx}>={P("small_delay_qty")},AF{idx}=0),"是","否"))'
            parc = f'IF(BA{idx}="",N(AD{idx}),N(BA{idx}))' if v3 else f'N(BA{idx})'
            excluded = f'OR({maintenance},{parc}<{P("delay_vehicle_parc")},AND(ISNUMBER(AG{idx}),AG{idx}=0))'
            gate = f'AND(AJ{idx}>ROUND(AG{idx}*{P("delay_on_hand_months")},10),E{idx}>ROUND(AG{idx}*{P("delay_net_months")},10))'
            ordinary = f'IF({excluded},"否",IF(COUNT(AJ{idx},E{idx},AG{idx})<>3,"",IF({gate},"是","否")))'
            formula(ws, f'BC{idx}', f'IF({small},{small_result},{ordinary})', {True:'是',False:'否'}.get(r.get('delay_replenishment')))
            gap = f'IF(I{idx}="偏多",F{idx}-H{idx},G{idx}-F{idx})'
            amount = f'TEXT({gap},IF(MOD({gap},1)=0,"#,##0","#,##0.##########"))'
            unit = f'IF(OR(AY{idx}="PCS",AY{idx}="EA"),"pcs",AY{idx})'
            quantity = f'IF(I{idx}="合理","备货合理",IF(I{idx}="偏多","备货多，建议减少","备货少，建议增加")&{amount}&{unit})'
            advice = f'IF(I{idx}="无法计算","计划数据异常，请核实",IF({small},"小件免审核",IF(J{idx}="人工判断","用品精品，按市场需求人工判断",{quantity})))'
            advice += f'&IF(BC{idx}="是","；建议延迟补货","")'
            if v3:
                low_limit = f'ROUND(AG{idx}*{P("turnover_low_months")},10)'
                high_limit = f'ROUND(AG{idx}*{P("turnover_high_months")},10)'
                warning = f'IF(OR({small},COUNT(F{idx},AG{idx})<>2,AG{idx}<=0),"",IF(F{idx}<{low_limit},"周转过低",IF(F{idx}>{high_limit},"周转过高","")))'
                formula(ws, f'BG{idx}', warning, r.get('turnover_warning'))
                advice += f'&IF(BG{idx}="","","；"&BG{idx}&"预警")'
                # Keep the flags in the same order as the review engine, including raw keyword collisions.
                helper = lambda col: f"'计算依据'!{col}{idx}"
                regular = f'AND({helper("B")}=0,{helper("C")}=0,NOT(AND({helper("D")}=1,COUNT(AD{idx},AG{idx},T{idx},U{idx})<>4)),{helper("E")}=0,NOT(AND({helper("F")}=1,NOT(AND(AD{idx}>{P("dangerous_fleet_threshold")},AK{idx}>0)))))'
                flags = [('COLLISION',f'AND({helper("Y")},OR({helper("U")},{helper("W")},{helper("X")}))'),
                         ('AIR',f'AND(ISNUMBER(D{idx}),D{idx}>0)'), ('MANUAL',f'J{idx}="人工判断"'),
                         ('ABC_MISSING',f'AND({regular},AB{idx}="")'),
                         ('MISSING_RATE',f'AND(OR({branch_ref}="UK-R08",{branch_ref}="UK-R09"),OR(AK{idx}="",AK{idx}=0),T{idx}=0)'),
                         ('NO_SEA_RANGE',f'AND(ISNUMBER({helper("K")}),ISNUMBER({helper("L")}),NOT({helper("M")}))')]
                joined = '&'.join(f'IF({test},"；{FLAG_LABELS[flag]}","")' for flag,test in flags)
                formula(ws, f'L{idx}', f'MID({joined},2,32767)', '；'.join(FLAG_LABELS[k] for k in r['manual_flags']))
            formula(ws, f'BD{idx}', advice, r.get('advice'))
    metadata={**payload.get('metadata',{}),'公式说明':'未来库存、上下限、数量结论、月均销量最大值、建议海运及剩余超储包含Excel公式；自动重算。',
        '留档说明':'人工审批、审核时结果及分类命中是冻结记录。修改Excel数量或参数后的公式结果不会改变网页审批；应重新走提交和复审。',
        '分类与目标口径':'分类命中固定为当前审核版本；X/Y为上游提供值，不推测其来源公式。',
        '周转天数':'用户要求待确认口径后再计算；当前表头保留、单元格为空。'}
    if v2:
        metadata['周转天数'] = '月均销量取近三个月与近半年月均的较大值。净库存及补货后库存按每月30天折算；未来库存含本次海运和空运。'
    if v3:
        supply_description = '审核前净额＋海运计划＋空运计划' if current_v3 else '在库数量＋审核前净额＋海运计划'
        metadata['周转天数'] = f'V3 未来库存＝{supply_description}。补货后周转天数＝未来库存÷最大月均销量×30。'
        metadata['公式说明'] = '浅蓝色单元格包含公式。月均销量、自动目标、数量和周转判断按本版标准重算。核定更换率来自本版物料主数据。'
        metadata['留档说明'] = '人工决定、核准数量和审核时结果按提交版本留档。'
        metadata['分类与目标口径'] = '物料按本仓绑定的标准匹配。按储备月数计算的目标保留公式，来源目标保留原值。'
    if state:
        metadata['整单结论'] = basis['label']
        if state in ('APPROVED','REJECTED','PARTIALLY_APPROVED'):
            metadata['终审结果'] = basis['label']
        metadata['执行口径'] = '海运计划、空运计划为申报数量。仅当前版本整单通过后，方可按本版可执行数量执行。'
        if state=='PARTIALLY_APPROVED':
            metadata['旧规则留档'] = '历史核准量保留当时的逐行决定。本版本全部物料的可执行量为 0。'
    for k,v in metadata.items():literal(meta.cell(meta.max_row+1 if meta['A1'].value is not None else 1,1),k);literal(meta.cell(meta.max_row,2),v)
    for sheet in (ws,params,calc):
        for cell in sheet[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='31263B')
        sheet.freeze_panes='C2' if sheet is ws else 'B2';sheet.auto_filter.ref=sheet.dimensions
        for col in range(1,sheet.max_column+1):sheet.column_dimensions[get_column_letter(col)].width=20
    for col in ('B','O','P','S','AS','AV'):ws.column_dimensions[col].width=34
    if v2: ws.column_dimensions['BD'].width = 46
    ws.column_dimensions['AH'].width=34;ws.column_dimensions['AI'].width=34
    meta.column_dimensions['A'].width=25;meta.column_dimensions['B'].width=105;params.column_dimensions['A'].width=30
    from .export_layout import add_business_sheet
    outcome_columns=[pair for pair in EXECUTION_COLUMNS+ARCHIVE_COLUMNS if pair[0] in column_letters]
    caches,description=add_business_sheet(wb,payload,files,column_letters,ws,calc,caches,v3,v2,literal,outcome_columns)
    meta.append(['审核主表版式',description])
    return cached_book(wb,caches)
