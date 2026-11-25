"""Rebuild an editable business sheet from the selected version and its upload's visual layout."""
from copy import copy
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
import hashlib
import re

from openpyxl import load_workbook
from openpyxl.cell import Cell
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill
from openpyxl.writer.theme import theme_xml
from openpyxl.utils import get_column_letter

from .adapters import FIELDS, PLAN_COLUMNS, REFERENCE_HEADERS, V2_HEADERS, plan_header
from .governance import effective_input
from .periods import period_info, previous_sales_months
from .template_assets import WORKBOOK_TEMPLATES


FORMATS = {'PLAN-V3': 'v3', 'PLAN-V2': 'v2', 'UK0804-v1': 'legacy'}
FIELDS_BY_HEADER = {v:k for k,v in {**FIELDS, **V2_HEADERS}.items()}
FIELDS_BY_HEADER.update({v:k for k,v in FIELDS.items()})
FIELDS_BY_HEADER.update({v:k for k,v in REFERENCE_HEADERS.items()})
FIELDS_BY_HEADER.update({'是否是重点车型':'is_key_model', '库存+在途-需求':'net_supply_before_plan',
    '未来库存':'future_qty', '在库周转(月)':'on_hand_months', '补货后周转天数':'future_days',
    '建议延迟补货':'delay_replenishment', '周转预警':'turnover_warning', '下限':'lower',
    '上限':'upper', '保养件':'maintenance', '小件':'small', '计划是否合理':'quantity_status',
    '审批建议':'advice', '审批是否同意':'decision', '调整后计划':'adjusted_plan',
    '调整后是否同意':'adjusted_decision', '备注':'review_note'})
FIELDS_BY_HEADER.update({v:k for k,v in V2_HEADERS.items()})
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def export_layout_reference(db, version, warehouse, snapshot):
    """Capture just the identity of the source sheet at enqueue time, also for empty filters."""
    from sqlalchemy import select
    from .db import Job

    originals, quantities = set(), set()
    for row in version.items:
        inp = row['input']
        for key, bucket in [('source', originals), ('plan_source', quantities)]:
            src = inp.get(key) or {}
            if src.get('job_id'):
                bucket.add((src['job_id'], src.get('sheet'), src.get('sha256'), FORMATS.get(src.get('adapter'), 'plan')))
    refs = originals or quantities
    if len(refs) > 1:
        return {'fallback': '本版本合并了多份来源，使用统一模板', 'format': next(iter(refs))[3] if len({r[3] for r in refs}) == 1 else None, 'mixed': True}
    if refs:
        job_id, sheet, digest, kind = next(iter(refs))
    elif snapshot and snapshot.source_id and version.items:
        src = version.items[0]['input'].get('source') or {}
        job_id, sheet, digest, kind = snapshot.source_id, src.get('sheet'), None, FORMATS.get(src.get('adapter'))
        if not kind:
            return {}
    else:
        return {}
    job = db.execute(select(Job.payload, Job.result['file_hash'].as_string()).where(
        Job.id == job_id, Job.warehouse == warehouse, Job.kind == 'import', Job.committed_id.is_not(None))).first()
    if not job or (digest and digest != job[1]):
        return {'format':kind, 'fallback':'来源记录无法核对，使用本版模板'}
    upload, stored_digest = job
    if Path(upload.get('filename','')).suffix.lower() != '.xlsx':
        return {'format':kind, 'fallback':'原导入文件没有 Excel 版式，使用本版模板'}
    return {'format':kind, 'file_id':upload['file_id'], 'sha256':digest or stored_digest, 'sheet':sheet,
            'mapping':upload.get('mapping') or {}}


@dataclass
class Column:
    index: int
    field: str
    header: object
    header_style: tuple
    row_style: tuple
    width: float | None
    hidden: bool


@dataclass
class Layout:
    columns: list
    freeze: str | None
    header_height: float | None
    row_height: float | None
    gridlines: bool
    title: str
    default_width: float | None
    default_height: float | None
    theme: bytes | None
    indexed_colors: tuple


def cell_style(cell):
    if not getattr(cell,'has_style',False):
        return ()
    return tuple(copy(getattr(cell,k)) for k in ('font','fill','border','alignment','number_format'))


def workbook_theme(source):
    # Import only RGB swatches, never drawings, relationships or theme extensions.
    if not source: return None
    source_scheme=ET.fromstring(source).find('.//{*}clrScheme')
    standard=ET.fromstring(theme_xml)
    target_scheme=standard.find('.//{*}clrScheme')
    if source_scheme is None: return None
    for slot in target_scheme:
        color=source_scheme.find(slot.tag)
        if color is None or not len(color): continue
        rgb=color[0].get('lastClr') or color[0].get('val','')
        if re.fullmatch(r'[0-9A-Fa-f]{6}',rgb):
            existing=slot[0]
            existing.set('lastClr' if existing.tag.endswith('sysClr') else 'val',rgb)
    return ET.tostring(standard,encoding='utf-8',xml_declaration=True)


def read_layout(path, kind, sheet_name=None, mapping=None):
    with open(path,'rb') as stream:
        book = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        try:
            title = sheet_name or ('计划明细' if kind == 'plan' else 'Sheet1' if kind == 'legacy' else '审核表')
            sheet = book[title]
            header, sample = sheet.iter_rows(min_row=1, max_row=2)
            labels = [plan_header(c.value) for c in header]
            month_end = labels.index('当月销量') if kind in ('v2','v3','legacy') else -1
            if month_end != -1 and month_end < 6:
                raise ValueError('缺少月销量列')
            fields = dict(FIELDS_BY_HEADER)
            fields.update({plan_header(v):k for k,v in (mapping or {}).items()})
            # For a quantity import expose only the plan fields it was authorized to update.
            keys = [fields.get(label, label if label in FIELDS else None) for label in labels]
            if kind == 'plan':
                keys = [key if key in PLAN_COLUMNS else None for key in keys]
            else:
                for i in range(6):
                    keys[month_end-6+i] = f'month{i}'
            if 'material_code' not in keys or not {'sea_plan_qty','air_plan_qty'}.intersection(keys):
                raise ValueError('无法匹配计划列')
            with ZipFile(path) as archive, archive.open(sheet._worksheet_path) as xml:
                widths, heights, freeze, gridlines = {}, {}, None, True
                default_width, default_height = None, None
                for _, element in ET.iterparse(xml,events=('start',)):
                    tag = element.tag.removeprefix(NS)
                    if tag == 'sheetView':
                        gridlines = element.get('showGridLines') not in ('0','false')
                    elif tag == 'pane' and element.get('state','').startswith('frozen'):
                        freeze = element.get('topLeftCell')
                    elif tag == 'sheetFormatPr':
                        if element.get('defaultColWidth'):
                            default_width=float(element.get('defaultColWidth'))
                        if element.get('defaultRowHeight'):
                            default_height=float(element.get('defaultRowHeight'))
                    elif tag == 'col':
                        width = float(element.get('width',13))
                        for j in range(int(element.get('min')),min(100,int(element.get('max')))+1):
                            widths[j] = (min(255,max(0,width)),element.get('hidden') in ('1','true'))
                    elif tag == 'row':
                        index = int(element.get('r','0'))
                        if element.get('ht'):
                            heights[index] = min(409,float(element.get('ht')))
                        if index >= 2:
                            break
            columns = []
            for i,(key,c) in enumerate(zip(keys,header),1):
                if not key: continue
                if c.data_type == 'f': raise ValueError('表头含公式')
                width,hidden = widths.get(i,(None,False))
                columns.append(Column(i,key,c.value,cell_style(c),cell_style(sample[i-1]),width,hidden))
            colors=tuple(book._colors) if all(re.fullmatch(r'[0-9A-Fa-f]{8}',c) for c in book._colors) else ()
            return Layout(columns,freeze,heights.get(1),heights.get(2),gridlines,title,default_width,default_height,
                          workbook_theme(book.loaded_theme), colors)
        finally:
            book.close()


@lru_cache(maxsize=3)
def standard_layout(kind):
    return read_layout(WORKBOOK_TEMPLATES[kind][0],kind)


@lru_cache(maxsize=3)
def standard_notes(kind):
    layout = standard_layout(kind)
    with ZipFile(WORKBOOK_TEMPLATES[kind][0]) as bundle:
        names = [p for p in bundle.namelist() if p.startswith('xl/comments/comment') and p.endswith('.xml')]
        if not names: return {}
        root = ET.fromstring(bundle.read(names[0]))
        by_coord = {c.get('ref'):''.join(c.itertext()) for c in root.iter(NS+'comment')}
    return {c.field:by_coord[get_column_letter(c.index)+'1'] for c in layout.columns if get_column_letter(c.index)+'1' in by_coord}


def select_layout(payload, files, v3, v2):
    ref = payload.get('layout') or {}
    default_kind = 'v3' if v3 else 'v2' if v2 else 'plan'
    kind = ref.get('format') or default_kind
    fallback = ref.get('fallback') or '手工计划或历史来源无可用版式，使用平台模板'
    file_id = ref.get('file_id','')
    if files and re.fullmatch(r'[0-9a-f]{32}\.xlsx',file_id):
        path = files / file_id
        try:
            if path.stat().st_size <= 20*1024*1024 and hashlib.sha256(path.read_bytes()).hexdigest() == ref.get('sha256'):
                return read_layout(path,kind,ref['sheet'],ref.get('mapping')),kind,'本版本导入工作表',True
        except (OSError,KeyError,ValueError,StopIteration,TypeError,BadZipFile,ET.ParseError):
            pass
        fallback = '原工作表缺失或版式无法匹配，使用平台模板'
    if kind == 'legacy': kind = 'v2'
    return standard_layout(kind),kind,fallback,False


def row_style(sheet, style):
    if not style: return None
    sample = Cell(sheet)
    sample.font, sample.fill, sample.border, sample.alignment, sample.number_format = style
    return sample._style


def add_business_sheet(wb, payload, files, columns, ws, calc, caches, v3, v2, literal, outcome_columns):
    layout,kind,description,original = select_layout(payload,files,v3,v2)
    main = wb.create_sheet(layout.title,0)
    wb.active=0
    if layout.theme: wb.loaded_theme=layout.theme
    if layout.indexed_colors: wb._colors=layout.indexed_colors
    main.sheet_view.showGridLines=layout.gridlines
    main.freeze_panes=layout.freeze
    if layout.default_width: main.sheet_format.defaultColWidth=layout.default_width
    if layout.default_height: main.sheet_format.defaultRowHeight=layout.default_height
    if layout.header_height: main.row_dimensions[1].height=layout.header_height
    labels = ()
    if not original:
        labels = {tuple(r['input'].get('month_labels') or ()) for r in payload['items']} - {()}
        period = payload.get('metadata',{}).get('计划周期')
        if len(labels)==1:
            labels = tuple(next(iter(labels)))
        elif not labels and period and period_info(period,strict=False)['start']:
            labels = tuple(m+' 销量' for m in previous_sales_months(period))
        else:
            labels = ()
    notes = standard_notes(kind if kind in WORKBOOK_TEMPLATES else 'v2')
    display_columns=list(layout.columns)
    if kind in ('v2','v3'):
        # Some accepted inputs contain only reference data. Present their columns first
        # and add the missing computed/review columns using the official template.
        visible={c.field for c in display_columns}
        computed={'future_qty','on_hand_months','future_days','delay_replenishment','turnover_warning','lower','upper',
                  'maintenance','small','quantity_status','advice','decision','adjusted_plan','adjusted_decision','review_note'}
        display_columns.extend(c for c in standard_layout(kind).columns if c.field in computed-visible)
    if kind == 'plan':
        visible={c.field for c in display_columns}
        display_columns.extend(c for c in standard_layout('plan').columns
                               if c.field in {'air_plan_qty','sea_plan_qty'}-visible)
        style_source=display_columns[-1]
        for key,title,width in [('advice','审批建议',36),('decision','复审决定',16),('review_note','复审备注',32)]:
            display_columns.append(Column(len(display_columns)+1,key,title,style_source.header_style,(),width,False))
    style_source=display_columns[-1]
    for key,title in outcome_columns:
        width=26 if key=='plan_outcome' or key.startswith('historical_') else 20
        display_columns.append(Column(len(display_columns)+1,key,title,style_source.header_style,(),width,False))
    outcomes={key for key,_ in outcome_columns}
    styles = []
    for j,col in enumerate(display_columns,1):
        key=col.field
        title=col.header
        if not original and key.startswith('month') and len(labels)==6:
            title = labels[int(key[5:])]
        cell = main.cell(1,j)
        if isinstance(title,(date,datetime)): cell.value=title
        else: literal(cell,title)
        cell._style=row_style(main,col.header_style)
        if notes.get(key): cell.comment=Comment(notes[key],'计划审核')
        if col.width is not None or col.hidden:
            dim=main.column_dimensions[get_column_letter(j)]
            if col.width is not None: dim.width=col.width
            dim.hidden=col.hidden
        styles.append(row_style(main,col.row_style))
    main_cache={}
    ws_cache=caches['xl/worksheets/sheet1.xml']
    calc_cache=caches['xl/worksheets/sheet4.xml']
    def link(target,origin,cache,value,zero=False):
        title = origin.parent.title.replace("'", "''")
        ref = f"'{title}'!{origin.coordinate}"
        empty = '0' if zero else '""'
        target.value = f'=IF(ISBLANK({ref}),{empty},{ref})'
        cache[target.coordinate]=value
    numeric={'fleet_qty','future_fleet_qty','vehicle_parc','current_sales','shortage_qty','on_hand_qty','net_supply_before_plan',
             'sea_plan_qty','air_plan_qty','replacement_rate','replacement_target','sales_target','avg_sales_3m','avg_sales_6m'}
    results={'future_qty','on_hand_months','future_days','delay_replenishment','turnover_warning','lower','upper','quantity_status','advice'}
    positions = {c.field: get_column_letter(j) for j,c in enumerate(display_columns,1)}
    month_positions = {key:col for key,col in positions.items() if key.startswith('month')}
    future_refs = {columns[k]:positions[k] for k in ('on_hand_qty','net_supply_before_plan','sea_plan_qty','air_plan_qty') if k in positions}
    for index,row in enumerate(payload['items'],2):
        inp=effective_input(row)
        if layout.row_height: main.row_dimensions[index].height=layout.row_height
        for j,(col,style) in enumerate(zip(display_columns,styles),1):
            key=col.field
            cell=main.cell(index,j)
            cell._style=style
            audit=ws[f'{columns[key]}{index}'] if key in columns else None
            if key.startswith('month'):
                pos=int(key[5:])
                monthly=inp.get('monthly_sales') or {}
                month_keys=inp.get('month_labels') or list(monthly)
                raw=monthly.get(month_keys[pos]) if len(month_keys)==6 else None
                literal(cell,raw,True)
                if v3 and len(month_keys)==6:
                    link(calc.cell(index,14+pos),cell,calc_cache,cell.value)
            elif key in ('avg_sales_3m','avg_sales_6m') and kind == 'v2' and not v3 and len(month_positions)==6 and len(inp.get('month_labels') or ())==6:
                start = 3 if key=='avg_sales_3m' else 0
                area = f"{month_positions['month'+str(start)]}{index}:{month_positions['month5']}{index}"
                cell.value = f'=IF(COUNT({area})+COUNTBLANK({area})<>COLUMNS({area}),"月销量无效，请核对六个月明细",IF(COUNT({area}),AVERAGE({area}),""))'
                main_cache[cell.coordinate]=audit.value
                link(audit,cell,ws_cache,audit.value)
            elif key in ('small','maintenance'):
                if row['result'].get('basis_pending'): continue
                origin=calc.cell(index,2 if key=='small' else 5)
                ref=f"'计算依据'!{origin.coordinate}"
                cell.value=f'=IF({ref}=1,"是","否")'
                hit=calc_cache.get(origin.coordinate,origin.value)
                main_cache[cell.coordinate]='是' if hit==1 else '否'
            elif key=='quantity_status' and audit is not None:
                mode=ws[f'{columns["review_mode"]}{index}']
                status_ref=f"'计划审核结果'!{audit.coordinate}"
                mode_ref=f"'计划审核结果'!{mode.coordinate}"
                lookup={'合理':'是','偏少':'否','偏多':'否','无法计算':'数据异常'}
                modes={'免数量审核':'免审核','人工判断':'人工审核'}
                status=ws_cache.get(audit.coordinate,audit.value)
                mode_value=ws_cache.get(mode.coordinate,mode.value)
                label=lookup.get(status) or modes.get(mode_value) or '待补资料'
                if row['result'].get('basis_pending'): literal(cell,'待补资料')
                else:
                    cell.value=(f'=IF({status_ref}="合理","是",IF(OR({status_ref}="偏少",{status_ref}="偏多"),"否",'
                                f'IF({status_ref}="无法计算","数据异常",IF({mode_ref}="免数量审核","免审核","人工审核"))))')
                    main_cache[cell.coordinate]=label
            elif key=='future_qty' and audit is not None and audit.data_type=='f' and len(future_refs)==4:
                # Same versioned formula as the calculation sheet, using the visible input columns.
                expr=re.sub(r'(?<![A-Z])([A-Z]+)(?=[0-9])',lambda m:future_refs[m[1]],audit.value[1:])
                sea,air=(positions[field]+str(index) for field in ('sea_plan_qty','air_plan_qty'))
                cell.value=f"=IF(OR(ISBLANK({sea}),ISBLANK({air})),'计划审核结果'!{audit.coordinate},{expr})"
                main_cache[cell.coordinate]=ws_cache[audit.coordinate]
            elif key=='advice' and audit is None:
                link(cell,ws[f'{columns["quantity_status"]}{index}'],main_cache,ws_cache.get(f'{columns["quantity_status"]}{index}'))
            elif key in outcomes:
                # Frozen version dispositions must not change when someone edits a requested quantity in Excel.
                literal(cell,audit.value,key!='plan_outcome')
            elif key=='review_note':
                literal(cell,(row.get('decision') or {}).get('reason') or row.get('return_reason'))
            elif audit is not None and (audit.data_type=='f' or key in results):
                link(cell,audit,main_cache,ws_cache.get(audit.coordinate,audit.value))
            elif key in ('adjusted_plan','adjusted_decision'):
                # No separate signed-off adjustment exists in the plan's recorded workflow.
                continue
            else:
                value=audit.value if audit is not None else inp.get(key)
                literal(cell,value,key in numeric)
                if audit is not None and key not in ('decision','reason','air_reason','reason_code'):
                    link(audit,cell,ws_cache,cell.value,key in ('sea_plan_qty','air_plan_qty'))
    if 'quantity_status' in positions and payload['items']:
        col=positions['quantity_status']
        for label,fg,bg in [('是','006100','C6EFCE'),('否','9C0006','FFC7CE')]:
            rule=CellIsRule(operator='equal',formula=[f'"{label}"'],font=Font(color=fg),fill=PatternFill('solid',fgColor=bg))
            main.conditional_formatting.add(f'{col}2:{col}{main.max_row}',rule)
    main.auto_filter.ref=main.dimensions
    return {'xl/worksheets/sheet1.xml':main_cache,'xl/worksheets/sheet2.xml':ws_cache,'xl/worksheets/sheet5.xml':calc_cache},description
