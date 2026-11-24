"""File adapters produce a stable, source-addressed input contract."""
from io import BytesIO, StringIO
from pathlib import Path
from collections import Counter
from decimal import Decimal
import csv
import zipfile
import time,re
from openpyxl import load_workbook
from .rules import number, serial, calculate, fingerprint
from .rules import canonical_reason

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 10000
FIELDS = {
    "material_code": "物料号", "material_name": "物料名称", "material_type": "物料类型", "material_abc": "物料分类ABC",
    "vehicle_model": "车型", "local_abc": "本地ABC", "is_key_model": "是否重点车型", "fleet_qty": "装车量", "vehicle_parc": "备件保有量",
    "avg_sales_3m": "近三个月月均销量", "avg_sales_6m": "近六个月月均销量", "replacement_rate": "稳态更换率",
    "replacement_target": "更换率目标库存", "sales_target": "销量目标库存", "net_supply_before_plan": "审核前净额",
    "sea_plan_qty": "海运计划", "air_plan_qty": "空运计划", "on_hand_qty": "在库数量", "in_transit_qty": "在途数量",
    "on_order_qty": "在订数量", "demand_deduction_qty": "需求抵扣数量", "uom": "计量单位", "quantity_step": "订货步长",
    "reason_code": "原因类别", "reason": "计划说明", "air_reason": "空运说明", "source_line_id": "源明细行ID", "source_note": "备注",
}
PLAN_COLUMNS = ("material_code", "material_name", "sea_plan_qty", "air_plan_qty", "reason_code", "reason", "air_reason")
PLAN_LABELS = {FIELDS[key] for key in PLAN_COLUMNS}


def plan_header(label):
    """An annotated plan header keeps the field name on its first line."""
    if isinstance(label, str):
        lines = label.splitlines()
        if len(lines) > 1 and lines[0].strip() in PLAN_LABELS:
            return lines[0].strip()
    return label


LEGACY_MAP = {"A": "material_code", "B": "material_name", "C": "material_type", "D": "local_abc", "E": "material_abc",
              "F": "is_key_model", "G": "fleet_qty", "I": "avg_sales_6m", "J": "avg_sales_3m", "S": "on_hand_qty",
              "T": "net_supply_before_plan", "U": "sea_plan_qty", "V": "air_plan_qty", "W": "replacement_rate",
              "X": "replacement_target", "Y": "sales_target"}
V2_HEADERS = {
    **{key: FIELDS[key] for key in ("material_code", "material_name", "material_type", "vehicle_model", "local_abc",
                                    "material_abc", "fleet_qty", "vehicle_parc", "sea_plan_qty", "air_plan_qty")},
    "is_key_model": "是否是重点车型", "avg_sales_3m": "近三个月月均销量", "avg_sales_6m": "近半年月均销量",
    "on_hand_qty": "库存", "net_supply_before_plan": "库存+在途+在定-需求", "replacement_rate": "更换率",
    "replacement_target": "目标库存-稳态更换率", "sales_target": "目标库存-销量",
}

def v2_sales(months):
    values = []
    for raw in months:
        if raw is None or raw == "":
            continue
        try:
            value = number(raw)
            if value is None or value < 0:
                raise ValueError()
        except ValueError:
            return "月销量无效，请核对六个月明细"
        values.append(value)
    return serial(sum(values) / len(values)) if values else None

def canonical(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip()

def boolean(value):
    if value is True or str(value).strip().casefold() in ("true", "是", "1", "yes", "y"):
        return True
    if value is False or str(value).strip().casefold() in ("false", "否", "0", "no", "n"):
        return False
    return None

def normalize(item, row, sheet, filename, net_mode="NET_PROVIDED", legacy=False):
    item = {k: v if isinstance(v,(dict,list)) else canonical(v) for k, v in item.items()}
    item["material_code"] = str(item.get("material_code") or "").strip()
    item["is_key_model"] = boolean(item.get("is_key_model"))
    item["uom"] = item.get("uom") or "PCS"
    item["quantity_step"] = item.get("quantity_step") or "1"
    # Explicit file contract: blank order quantities mean no new order, not missing supply.
    for key in ("sea_plan_qty", "air_plan_qty"):
        item[key] = item.get(key) if item.get(key) not in (None, "") else "0"
    item["source"] = {"file": Path(filename).name, "sheet": sheet, "row": row, "adapter": "UK0804-v1" if legacy else "STANDARD-v1"}
    item["source_values"] = dict(item)
    item["source_values"].pop("source_values", None)
    if "reason_code" in item:
        item["reason_code"] = canonical_reason(item["reason_code"])
    if net_mode == "COMPONENTS":
        keys = ("on_hand_qty", "in_transit_qty", "on_order_qty", "demand_deduction_qty")
        try:
            vals = [number(item.get(key)) for key in keys]
            if any(v is None for v in vals):
                item["net_supply_before_plan"] = None
            else:
                item["net_supply_before_plan"] = serial(vals[0]+vals[1]+vals[2]-vals[3])
        except ValueError:
            item["net_supply_before_plan"] = "分项数量无效"
    return item

def parse_file(data, filename, kind="standard", mapping=None, net_mode="NET_PROVIDED", sheet_name=None):
    started=time.monotonic()
    if len(data) > MAX_BYTES:
        raise ValueError("文件超过20MiB，请分批处理")
    suffix = Path(filename).suffix.lower()
    mapping = mapping or {}
    labels = {key:plan_header(value) for key,value in mapping.items()} if kind == "plan" else mapping
    if kind in ("legacy", "v2") and net_mode != "NET_PROVIDED":
        raise ValueError("审核原表须使用已提供净额")
    if net_mode not in ("NET_PROVIDED", "COMPONENTS"):
        raise ValueError("请选择明确的净供给口径")
    items, headers = [], []
    if suffix == ".xlsx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                infos = archive.infolist()
                if sum(i.file_size for i in infos) > 250*1024*1024 or len(infos) > 5000:
                    raise ValueError("工作簿解压后过大")
                if any("vbaproject" in i.filename.lower() or "externallinks/" in i.filename.lower() for i in infos):
                    raise ValueError("不接受宏或外部链接工作簿")
            wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
            formula_book=load_workbook(BytesIO(data),read_only=True,data_only=False)
            if len(wb.sheetnames) > 20:
                raise ValueError("工作表数量超过20")
            if kind == "legacy" and "Sheet1" not in wb.sheetnames:
                raise ValueError("未找到英国0804的Sheet1")
            default_sheet = "Sheet1" if kind == "legacy" else "审核表" if kind == "v2" else wb.sheetnames[0]
            if kind == "plan" and not mapping and not sheet_name and "计划明细" in wb.sheetnames:
                candidate = next(wb["计划明细"].values, ())
                if FIELDS["material_code"] in map(plan_header, candidate):
                    default_sheet = "计划明细"
            if kind == "standard" and not mapping and not sheet_name and "审核表" in wb.sheetnames:
                candidate = next(wb["审核表"].values, ())
                if all(h in candidate for h in V2_HEADERS.values()):
                    default_sheet = "审核表"
            ws = wb[sheet_name or default_sheet]
            if (ws.max_row or 0) > MAX_ROWS+1 or (ws.max_column or 0) > 100:
                raise ValueError("超过10000行或100列限制")
            rows = ws.iter_rows(values_only=True)
            formula_rows=formula_book[ws.title].iter_rows(values_only=True)
            next(formula_rows)
            headers = [str(x or "").strip() for x in next(rows)]
            if kind == "plan":
                headers = [plan_header(header) for header in headers]
            if len(headers)>100:raise ValueError("超过100列限制")
            if kind!='legacy' and len([h for h in headers if h])!=len(set(h for h in headers if h)):raise ValueError('表头存在重名列，请先区分字段')
            if kind == "legacy" and (len(headers) < 32 or headers[19] != "库存+在途-需求" or headers[20] != "海运计划"):
                raise ValueError("与英国0804模板不符，请使用标准表映射")
            from openpyxl.utils import column_index_from_string
            if kind == "standard" and not mapping and all(h in headers for h in V2_HEADERS.values()):
                kind = "v2"
            if kind == "v2":
                if net_mode != "NET_PROVIDED":
                    raise ValueError("V2 审核表须使用已提供净额")
                missing = [h for h in [*V2_HEADERS.values(), "当月销量"] if h not in headers]
                if missing:
                    raise ValueError("V2 审核表缺少列：" + "、".join(missing))
                indices = {key:headers.index(header) for key,header in V2_HEADERS.items()}
                if "备注" in headers:
                    indices["source_note"] = headers.index("备注")
                month_end = headers.index("当月销量")
                if month_end - indices["avg_sales_6m"] != 7:
                    raise ValueError("近半年月均销量与当月销量之间须有六列月销量，并按从早到晚排列")
            elif kind == "legacy":
                indices = {key:column_index_from_string(col)-1 for col,key in LEGACY_MAP.items()}
            else:
                indices = {key:headers.index(labels.get(key) or FIELDS[key]) if (labels.get(key) or FIELDS[key]) in headers else headers.index(key)
                           for key in FIELDS if (labels.get(key) or FIELDS[key]) in headers or key in headers}
            for r, row_values in enumerate(rows, 2):
                formula_values=next(formula_rows,())
                if r>MAX_ROWS+1 or len(row_values)>100:raise ValueError("超过10000行或100列限制")
                if time.monotonic()-started>30:raise ValueError("文件解析超过30秒，请缩小工作簿后重试")
                if not any(v is not None and str(v).strip() for v in row_values):
                    continue
                item = {key:row_values[index] if index < len(row_values) else None for key,index in indices.items()}
                if kind == "v2" and not any(item.get(k) not in (None, "") for k in indices if k not in ("avg_sales_3m", "avg_sales_6m")) and not any(x is not None for x in row_values[month_end-6:month_end]):
                    continue
                provenance={}
                for key,index in indices.items():
                    formula=formula_values[index] if index<len(formula_values) else None
                    formula=getattr(formula,'text',formula)
                    if isinstance(formula,str) and formula.startswith('='):
                        provenance[key]={'formula':formula,'cached':item.get(key)}
                        if item.get(key) is None:item[key]='公式没有缓存，请在Excel重新计算并保存'
                        if re.search(r'\[[^\]]+\][^!]*!',formula):item[key]='外部引用公式不接受，请提供核实后的数值'
                if kind == "v2":
                    months = list(row_values[month_end-6:month_end])
                    for pos, raw in enumerate(formula_values[month_end-6:month_end]):
                        if months[pos] is None and str(getattr(raw, "text", raw)).startswith("="):
                            months[pos] = "月销量公式缺少缓存"
                    item["avg_sales_3m"], item["avg_sales_6m"] = v2_sales(months[-3:]), v2_sales(months)
                    item["monthly_sales"] = dict(zip(headers[month_end-6:month_end], map(canonical, months)))
                    item["is_key_model"] = str(item.get("is_key_model") or "").strip().upper() == "Y"
                normalized=normalize(item, r, ws.title, filename, net_mode, kind == "legacy")
                if kind == "v2":
                    normalized["source"]["adapter"] = "PLAN-V2"
                if provenance:normalized['source_formulas']=provenance
                items.append(normalized)
            wb.close()
            formula_book.close()
        except (zipfile.BadZipFile, KeyError, StopIteration) as e:
            raise ValueError("无法读取工作簿或指定工作表") from e
    elif suffix == ".csv" and kind not in ("legacy", "v2"):
        try:
            reader = csv.DictReader(StringIO(data.decode("utf-8-sig")))
            headers = reader.fieldnames or []
            if kind == "plan":
                headers = [plan_header(header) for header in headers]
                reader.fieldnames = headers
            if len(headers)!=len(set(headers)):raise ValueError('表头存在重名列，请先区分字段')
            if len(headers) > 100:
                raise ValueError("超过100列限制")
            for r, source in enumerate(reader, 2):
                if r > MAX_ROWS+1:
                    raise ValueError("超过10000行限制")
                if kind == "plan" and not any(value is not None and str(value).strip() for value in source.values()):
                    continue
                item = {k: source.get((labels.get(k) or FIELDS[k]), source.get(k)) for k in FIELDS}
                items.append(normalize(item, r, "CSV", filename, net_mode))
        except UnicodeDecodeError as e:
            raise ValueError("CSV需要使用UTF-8编码") from e
    else:
        raise ValueError("仅支持.xlsx和UTF-8 .csv")
    if not items:
        raise ValueError("文件中没有可读取的数据行")
    codes = Counter(i["material_code"] for i in items)
    issues = []
    for item in items:
        if not item["material_code"] or codes[item["material_code"]] > 1:
            issues.append({"row": item["source"]["row"], "material_code": item["material_code"], "field": "material_code", "message": "物料号为空或重复；请先按物料汇总，不能直接合并计划"})
    by_row={i['source']['row']:i for i in items}
    for error in issues:
        error.update({'file':filename,'sheet':by_row[error['row']]['source']['sheet'],'repair_hint':'检查物料号，并按声明的物料汇总粒度整理后重新上传'})
    return {"items": items, "headers": headers, "issues": issues, "file_hash": __import__('hashlib').sha256(data).hexdigest(), "net_mode": net_mode,
            "basis_code": {"legacy":"UK0804_NET", "v2":"V2_NET"}.get(kind, "STANDARD_"+net_mode), "mapping": mapping, "kind": kind}

def legacy_evidence(path):
    data = Path(path).read_bytes()
    result = parse_file(data, Path(path).name, kind="legacy")
    wb = load_workbook(BytesIO(data), read_only=False, data_only=True)
    ws = wb["Sheet1"]
    for item in result["items"]:
        r = item["source"]["row"]
        item["legacy"] = {k: ws[f"{col}{r}"].value for k, col in {"lower": "AA", "upper": "AB", "future_qty": "Z", "maintenance": "AC", "small": "AD", "status": "AE", "advice": "AF"}.items()}
    wb.close()
    return result
