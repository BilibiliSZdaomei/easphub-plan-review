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
from .rules import number, default_package, FLAG_LABELS, PARAM_LABELS, MODEL_V2, REASON_LABELS
from .table_query import decision_label

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

def export_workbook(payload):
    package=payload.get('rule_package')
    if not package:
        raw=payload.get('metadata',{}).get('规则参数')
        model = MODEL_V2 if any('advice' in row['result'] for row in payload['items']) else '0804'
        package=json.loads(raw) if raw else default_package(model)
    wb=Workbook();ws=wb.active;ws.title='计划审核结果';meta=wb.create_sheet('版本与来源');params=wb.create_sheet('规则参数');calc=wb.create_sheet('计算依据')
    wb.calculation=CalcProperties(calcMode='auto',fullCalcOnLoad=True,forceFullCalc=True)
    v2 = package.get('model') == MODEL_V2
    columns = COLS
    if v2:
        labels = {'pipeline_days':'净库存周转（天）', 'future_days':'补货后周转（天）'}
        columns = [(k, labels.get(k, title)) for k,title in COLS] + V2_COLUMNS
    ws.append([label for _,label in columns]);params.append(['参数','值','字段'])
    param_refs={}
    for key,value in package['params'].items():
        params.append([PARAM_LABELS.get(key,key),value,key]);literal(params.cell(params.max_row,2),value,True);param_refs[key]=f"'规则参数'!$B${params.max_row}"
    calc.append(['物料号','小件命中','不备货命中','人工类命中','保养件命中','危包命中','规则分支（公式）','原始下限（公式）','原始上限（公式）','数据错误（公式）','海运下界（公式）','海运上界（公式）','海运范围可行（公式）'])
    caches={'xl/worksheets/sheet1.xml':{},'xl/worksheets/sheet4.xml':{}}
    def formula(sheet,coord,text,value):
        sheet[coord]='='+text;caches['xl/worksheets/sheet1.xml' if sheet is ws else 'xl/worksheets/sheet4.xml'][coord]=value
    for idx,row in enumerate(payload['items'],2):
        i=row['input'];r=row['result'];d=row.get('decision') or {};o=row.get('submission_override') or {}
        defaults = {} if r.get('basis_pending') else {'quantity_step':1,'uom':'PCS'}
        values={**defaults,**i,**r,'decision':decision_label(d,payload.get('metadata',{}).get('版本状态')),'reviewer_name':d.get('reviewer_name'),'review_reason':d.get('reason'),'review_reason_code':d.get('reason_code'),
            'source_file':i.get('source',{}).get('file'),'source_row':i.get('source',{}).get('row'),'plan_file':i.get('plan_source',{}).get('file'),'plan_row':i.get('plan_source',{}).get('row'),
            'original_status':r['quantity_status'],'original_data':r['data_status'],'original_lower':r['lower'],'original_upper':r['upper'],'original_future':r['future_qty'],
            'submission_reason':o.get('reason'),'submission_user':o.get('user_name'),'submission_at':o.get('at'),'final_exception':d.get('reason') if d.get('forced') else None,
            'pipeline_days':None,'future_days':None,'is_key_model':'是' if i.get('is_key_model') is True else '否' if i.get('is_key_model') is False else None}
        for col,(key,_) in enumerate(columns,1):
            v=values.get(key)
            if key in ('reason_code','review_reason_code') and isinstance(v,str):v=REASON_LABELS.get(v,v)
            if key=='manual_flags':v='；'.join(FLAG_LABELS.get(f,f) for f in v or [])
            if key in ('quantity_status','review_mode','data_status','decision','original_status','original_data'):v=TEXT.get(v,v)
            literal(ws.cell(idx,col),v,key in NUMERIC or key == 'vehicle_parc')
        if r.get('basis_pending'):
            literal(calc.cell(idx,1),i['material_code'])
            continue
        hits=r.get('matched_keywords',{});override=r.get('override')
        flags=[override==key if override else bool(hits.get(key)) for key in ('small','no_stock','manual','maintenance','dangerous')]
        calc.append([i['material_code'],*[int(v) for v in flags]])
        calc.cell(idx,1).data_type='s'
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
        formula(ws,f'F{idx}',f'IF(COUNT(E{idx},C{idx},D{idx})=3,E{idx}+C{idx}+D{idx},"")',n(r.get('future_qty')))
        for col,raw in [('G','H'),('H','I')]:
            ref=f"'计算依据'!{raw}{idx}"
            formula(ws,f'{col}{idx}',f'IF(ISNUMBER({ref}),ROUND(ROUND({ref},10),0),"")',n(r.get('lower' if col=='G' else 'upper')))
        # Live validation for source fields. Missing optional values stay distinct from zero.
        errors=[f'{R("A")}=""',f'AND({R("B")}="",{R("AM")}="")',f'COUNT({t},{sea},{air},{step})<>4',f'{sea}<0',f'{air}<0',f'{step}<=0',f'ROUND({sea}/{step},10)<>ROUND({sea}/{step},0)',f'ROUND({air}/{step},10)<>ROUND({air}/{step},0)',f'{w}>1',f'AND(G{idx}="",D{idx}<>1)',f'AND(G{idx}="UK-R08",{key}<>"是",{key}<>"否")',f'AND(ISNUMBER({R("G")}),ISNUMBER({R("H")}),{R("G")}>{R("H")})']
        for field in ('AD','AE','AF','AK','T','U') + (('AJ','BA') if v2 else ()):
            ref=R(field);errors.append(f'AND({ref}<>"",OR(NOT(ISNUMBER({ref})),{ref}<0))')
        errors.append('AND('+','.join(f'{R("AY")}<>"{u}"' for u in ('PCS','EA','SET','L','KG','M'))+')')
        formula(calc,f'J{idx}','IFERROR(OR('+','.join(errors)+'),TRUE)',r['data_status']=='ERROR')
        error=f"'计算依据'!J{idx}";manual=f"OR('计算依据'!B{idx}=1,'计算依据'!D{idx}=1)"
        formula(ws,f'I{idx}',f'IF({error},"无法计算",IF({manual},"不适用",IF(F{idx}<G{idx},"偏少",IF(F{idx}>H{idx},"偏多","合理"))))',TEXT[r['quantity_status']])
        branch_ref=f"'计算依据'!G{idx}"
        warn=f'OR(AND(OR({branch_ref}="UK-R06",{branch_ref}="UK-R07",{branch_ref}="UK-R08",{branch_ref}="UK-R09"),AB{idx}=""),AND(OR({branch_ref}="UK-R08",{branch_ref}="UK-R09"),OR(AK{idx}="",AK{idx}=0),T{idx}=0))'
        formula(ws,f'K{idx}',f'IF({error},"数据错误",IF({warn},"需关注","有效"))',TEXT[r['data_status']])
        usable=not r['errors'] and r['review_mode']=='AUTO';low=high=None
        if usable:
            base=n(i['net_supply_before_plan'])+n(i['air_plan_qty']);st=n(i.get('quantity_step',1))
            low=(max(Decimal(0),n(r['lower'])-base)/st).to_integral_value(rounding=ROUND_CEILING)*st
            high=((n(r['upper'])-base)/st).to_integral_value(rounding=ROUND_FLOOR)*st
        gate=f'OR(J{idx},B{idx}=1,D{idx}=1)'
        formula(calc,f'K{idx}',f'IF({gate},"",ROUNDUP(MAX(0,{R("G")}-{t}-{air})/{step},0)*{step})',low)
        formula(calc,f'L{idx}',f'IF({gate},"",INT(({R("H")}-{t}-{air})/{step})*{step})',high)
        formula(calc,f'M{idx}',f'IF(COUNT(K{idx},L{idx})=2,L{idx}>=K{idx},FALSE)',r['sea_feasible'] is True)
        a,b,c=(f"'计算依据'!{col}{idx}" for col in ('K','L','M'))
        formula(ws,f'M{idx}',f'IF(COUNT({a},{b})<>2,"",IF({c},MIN(MAX(C{idx},{a}),{b}),0))',n(r.get('suggested_sea_qty')))
        formula(ws,f'N{idx}',f'IF(COUNT({a},{b})<>2,"",IF({c},0,MAX(0,E{idx}+D{idx}-H{idx})))',n(r.get('residual_excess')))
        if v2:
            for column, field, source, factor in (('BB','on_hand_months','AJ',1), ('AH','pipeline_days','E',30), ('AI','future_days','F',30)):
                qty = f'{source}{idx}'
                expr = f'IF(NOT(ISNUMBER(AG{idx})),"",IF(AG{idx}=0,"无销量",IF(ISNUMBER({qty}),{qty}/AG{idx}*{factor},"")))'
                formula(ws, f'{column}{idx}', expr, '无销量' if n(r.get('m'))==0 else n(r.get(field)))
            small = f"'计算依据'!B{idx}=1"
            maintenance = f"'计算依据'!E{idx}=1"
            small_result = f'IF(COUNT(E{idx},AF{idx})<2,"",IF(AND(E{idx}>={P("small_delay_qty")},AF{idx}=0),"是","否"))'
            excluded = f'OR({maintenance},N(BA{idx})<{P("delay_vehicle_parc")},AND(ISNUMBER(AG{idx}),AG{idx}=0))'
            gate = f'AND(AJ{idx}>ROUND(AG{idx}*{P("delay_on_hand_months")},10),E{idx}>ROUND(AG{idx}*{P("delay_net_months")},10))'
            ordinary = f'IF({excluded},"否",IF(COUNT(AJ{idx},E{idx},AG{idx})<>3,"",IF({gate},"是","否")))'
            formula(ws, f'BC{idx}', f'IF({small},{small_result},{ordinary})', {True:'是',False:'否'}.get(r.get('delay_replenishment')))
            gap = f'IF(I{idx}="偏多",F{idx}-H{idx},G{idx}-F{idx})'
            amount = f'TEXT({gap},IF(MOD({gap},1)=0,"#,##0","#,##0.##########"))'
            unit = f'IF(OR(AY{idx}="PCS",AY{idx}="EA"),"pcs",AY{idx})'
            quantity = f'IF(I{idx}="合理","备货合理",IF(I{idx}="偏多","备货多，建议减少","备货少，建议增加")&{amount}&{unit})'
            advice = f'IF(I{idx}="无法计算","计划数据异常，请核实",IF({small},"小件免审核",IF(J{idx}="人工判断","用品精品，按市场需求人工判断",{quantity})))'
            formula(ws, f'BD{idx}', f'{advice}&IF(BC{idx}="是","；建议延迟补货","")', r.get('advice'))
    metadata={**payload.get('metadata',{}),'公式说明':'未来库存、上下限、数量结论、月均销量最大值、建议海运及剩余超储包含Excel公式；自动重算。',
        '留档说明':'人工审批、审核时结果及分类命中是冻结记录。修改Excel数量或参数后的公式结果不会改变网页审批；应重新走提交和复审。',
        '分类与目标口径':'分类命中固定为当前审核版本；X/Y为上游提供值，不推测其来源公式。',
        '周转天数':'用户要求待确认口径后再计算；当前表头保留、单元格为空。'}
    if v2:
        metadata['周转天数'] = '月均销量取近三个月与近半年月均的较大值。净库存及补货后库存按每月30天折算；未来库存含本次海运和空运。'
    for k,v in metadata.items():literal(meta.cell(meta.max_row+1 if meta['A1'].value is not None else 1,1),k);literal(meta.cell(meta.max_row,2),v)
    for sheet in (ws,params,calc):
        for cell in sheet[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='31263B')
        sheet.freeze_panes='C2' if sheet is ws else 'B2';sheet.auto_filter.ref=sheet.dimensions
        for col in range(1,sheet.max_column+1):sheet.column_dimensions[get_column_letter(col)].width=20
    for col in ('B','O','P','S','AS','AV'):ws.column_dimensions[col].width=34
    if v2: ws.column_dimensions['BD'].width = 46
    ws.column_dimensions['AH'].width=34;ws.column_dimensions['AI'].width=34
    meta.column_dimensions['A'].width=25;meta.column_dimensions['B'].width=105;params.column_dimensions['A'].width=30
    return cached_book(wb,caches)
