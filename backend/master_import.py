"""Read supported master columns from a V3 workbook or a UTF-8 CSV."""
import csv
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from xml.etree.ElementTree import ParseError

from .adapters import MAX_BYTES, MAX_ROWS, ENGLISH_FIELDS
from .governance import MASTER_FIELDS, master_value
from .workbook_language import canonical_workbook_header

MASTER_ENGLISH = {**{key: ENGLISH_FIELDS[key] for key in MASTER_FIELDS if key in ENGLISH_FIELDS},
                  'material_name': 'Part description',
                  'large_value_flag': 'High-value, bulky part',
                  'replacement_rate': 'Replacement rate',
                  'replacement_months': 'Replacement coverage (months)',
                  'sales_months': 'Sales coverage (months)',
                  'use_fixed_targets': 'Use source targets'}

HEADERS={label:key for key,label in {'material_code':'物料号',**MASTER_FIELDS}.items()}
HEADERS.update({'物料名称':'material_name','本地 ABC':'local_abc','物料分类 ABC':'material_abc','是否是重点车型':'is_key_model',
                '稳态更换率':'replacement_rate','目标库存-稳态更换率':'replacement_target','目标库存-销量':'sales_target'})

HEADERS.update({label:key for key,label in {'material_code':ENGLISH_FIELDS['material_code'],**MASTER_ENGLISH}.items()})

def collect_master(rows, formulas=None):
    header=next(rows,())
    indices={}
    for idx,raw in enumerate(header):
        label=str(canonical_workbook_header(raw) or '').split('\n')[0].strip()
        key=HEADERS.get(label)
        if key:
            if key in indices: raise ValueError(f'表头重复 · {label}')
            indices[key]=idx
    if 'material_code' not in indices or len(indices)<2: raise ValueError('请提供物料号和至少一列主数据')
    records={}
    for n,row in enumerate(rows,2):
        if n>MAX_ROWS+1 or len(row)>100: raise ValueError('文件超过 10000 行或 100 列')
        formula_row=next(formulas,()) if formulas is not None else ()
        vals={k:(row[i] if i<len(row) else None) for k,i in indices.items()}
        raw=vals.pop('material_code')
        if all(v is None or str(v).strip()=='' for v in [raw,*vals.values()]): continue
        code='' if raw is None else str(raw).strip()
        if not code or len(code)>120 or code in records: raise ValueError(f'第 {n} 行 · 物料号为空、过长或重复 · {code}')
        record={}
        try:
            for k,v in vals.items():
                i=indices[k]
                if v is None and i<len(formula_row) and getattr(formula_row[i],'data_type',None)=='f':
                    raise ValueError(MASTER_FIELDS[k]+'的公式没有计算结果，请重算并保存')
                value=master_value(k,v)
                if value is not None: record[k]=value
            if not record: raise ValueError('至少填写一项主数据')
        except ValueError as exc:
            raise ValueError(f'第 {n} 行 {code} · {exc}') from exc
        records[code]=record
    if not records: raise ValueError('文件中没有物料主数据')
    return records

def read_master(blob, name):
    if len(blob)>MAX_BYTES: raise ValueError('文件超过 20 MiB')
    suffix=Path(name).suffix.lower()
    if suffix=='.csv':
        try: return collect_master(iter(csv.reader(StringIO(blob.decode('utf-8-sig')))))
        except UnicodeDecodeError as exc: raise ValueError('请使用 UTF-8 CSV') from exc
    if suffix!='.xlsx': raise ValueError('请选择 .xlsx 或 UTF-8 .csv 文件')
    try:
        with ZipFile(BytesIO(blob)) as z:
            entries=z.infolist()
            if len(entries)>5000 or sum(i.file_size for i in entries)>250*1024*1024 or any('externallinks/' in i.filename.lower() or 'vbaproject' in i.filename.lower() for i in entries):
                raise ValueError('工作簿过大或含外部链接、宏')
        book=load_workbook(BytesIO(blob),read_only=True,data_only=True)
        try:
            sheet=next((book[name] for name in ('物料主数据','审核表') if name in book.sheetnames),book.worksheets[0])
            if (sheet.max_row or 0)>MAX_ROWS+1 or (sheet.max_column or 0)>100: raise ValueError('文件超过 10000 行或 100 列')
            raw=load_workbook(BytesIO(blob),read_only=True,data_only=False)
            try:
                formulas=raw[sheet.title].iter_rows()
                next(formulas,())
                return collect_master(sheet.values,formulas)
            finally: raw.close()
        finally: book.close()
    except (BadZipFile,InvalidFileException,KeyError,IndexError,OSError,ParseError,SyntaxError) as exc:
        raise ValueError('无法读取 Excel 工作簿') from exc
