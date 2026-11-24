"""Versioned replenishment rules shared by planning and review."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, localcontext
import hashlib
import json

PRECISION_VERSION = "UK0804-decimal-10-half-up-v1"
MODEL_V2 = "V2"
REASON_LABELS = {
    "市场需求变化": "预计用量有变化",
    "已确认特殊订单": "已有订单要交付",
    "补货节奏": "配合船期或到货时间",
    "特殊物料": "备件有特殊备货要求",
    "数据口径说明": "库存或销量需要说明",
    "其他": "其他原因",
}
REASON_CODES = {label: code for code, label in REASON_LABELS.items()}


def canonical_reason(value):
    return REASON_CODES.get(value, value) if isinstance(value, str) else value


DELAY_DEFAULTS = {
    "delay_on_hand_months": 4, "delay_net_months": 9,
    "delay_vehicle_parc": 10000, "small_delay_qty": 150,
}
DEFAULTS = {
    "fixed_ab": 12, "fixed_non_ab": 3, "fleet_low_threshold": 1000,
    "target_ratio_threshold": 1.5, "upper_months_key": 15, "upper_months_non_key": 12,
    "dangerous_fleet_threshold": 10000, "dangerous_ratio": 0.0015, "dangerous_fixed": 10,
    "maintenance_fixed": 200, "maintenance_fleet_low_ratio": 0.5,
    "maintenance_fleet_high_ratio": 0.6, "maintenance_lower_months": 12,
    "maintenance_upper_months": 24, "small_display_upper": 10000,
}
KEYWORDS = {
    "small": "螺栓 螺母 卡扣 螺钉 垫圈 堵盖 字标 垫片 管夹 缓冲块 子母扣 密封圈 限位块 整车标贴 螺帽".split(),
    "maintenance": "滤 刮片 制动片 制动盘 火花塞 油 液 保养件 Maintenance".split(),
    "dangerous": "补胎液 冷却液 电池 胶 气雾 喷剂 防冻 清洗剂 制冷剂".split(),
    "manual": "工具 工装 服装 文创 套装 底护板 诊断 脚垫 后备箱垫 行李箱衬垫 装置 充电盒 充电桩 小行程件 标定 车模 工作服 头枕 腰靠 麦克 保养手册".split(),
    "no_stock": ["子午线轮胎"],
}
PARAM_LABELS = {
    "fixed_ab": "A/B 类固定比较值", "fixed_non_ab": "其他分类固定比较值",
    "fleet_low_threshold": "低装车量阈值", "target_ratio_threshold": "目标库存倍数阈值",
    "upper_months_key": "重点车型上限月数", "upper_months_non_key": "非重点上限月数",
    "dangerous_fleet_threshold": "危包常规装车量阈值", "dangerous_ratio": "危包装车量比例",
    "dangerous_fixed": "危包固定比较值", "maintenance_fixed": "保养件固定比较值",
    "maintenance_fleet_low_ratio": "保养件备用装车量比例", "maintenance_fleet_high_ratio": "保养件常规装车量比例",
    "maintenance_lower_months": "保养件下限月数", "maintenance_upper_months": "保养件上限月数",
    "small_display_upper": "小件参考上限（免数量审核）",
    "delay_on_hand_months": "延迟补货 · 在库月数", "delay_net_months": "延迟补货 · 净库存月数",
    "delay_vehicle_parc": "延迟补货 · 最低备件保有量", "small_delay_qty": "小件延迟补货 · 最低净库存",
}
FLAG_LABELS = {"AIR": "空运必要性待确认", "COLLISION": "特殊分类重叠", "MISSING_RATE": "缺更换率且目标为零",
               "NO_SEA_RANGE": "仅调整海运无法达标", "ABC_MISSING": "物料分类缺失", "MANUAL": "按市场需求人工判断"}

def default_package(model=MODEL_V2):
    package = {"params": deepcopy(DEFAULTS), "keywords": deepcopy(KEYWORDS), "overrides": {}, "precision_version": PRECISION_VERSION}
    return upgrade_to_v2(package) if model == MODEL_V2 else package

def upgrade_to_v2(package):
    updated = deepcopy(package)
    updated["model"] = MODEL_V2
    updated["params"] = {**DELAY_DEFAULTS, **updated["params"]}
    return updated

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()

def number(value):
    if value is None or str(value).strip().lower() in ("", "none", "null", "nan", "nat"):
        return None
    if isinstance(value, bool):
        raise ValueError("布尔值不能作为数量")
    try:
        text = str(value).strip()
        n = Decimal(text[:-1]) / 100 if text.endswith("%") else Decimal(text)
        if not n.is_finite() or abs(n) > Decimal("1e12"):
            raise ValueError("数值超出允许范围")
        return n
    except (InvalidOperation, ValueError):
        raise ValueError("请输入有效数字，不能使用问号或说明文字")

def serial(n):
    if n is None:
        return None
    s = format(n, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s

def uk_round(n):
    # Normalize Excel's serialized input tails at a single versioned boundary.
    return n.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP).quantize(Decimal(1), rounding=ROUND_HALF_UP)

def validate_package(package):
    if not isinstance(package, dict):
        return ["规则参数格式有误"]
    errors = []
    if set(package) - {"params", "keywords", "overrides", "model", "precision_version"}:
        errors.append("含有不支持的规则字段")
    if package.get("precision_version") != PRECISION_VERSION:
        errors.append("精度策略必须使用受支持的版本")
    if package.get("model", "0804") not in ("0804", MODEL_V2):
        errors.append("审核规则版本无效")
    params = package.get("params")
    keywords = package.get("keywords")
    overrides = package.get("overrides", {})
    if not all(isinstance(section, dict) for section in (params, keywords, overrides)):
        return errors + ["参数、关键词和物料类型覆盖必须按字段填写"]
    keys = [*DEFAULTS, *DELAY_DEFAULTS] if package.get("model") == MODEL_V2 else DEFAULTS
    if set(params).difference(keys):
        errors.append("含有所选模型不支持的参数")
    if set(keywords).difference(KEYWORDS):
        errors.append("含有不支持的物料关键词分类")
    for key in keys:
        try:
            n = Decimal(str(params.get(key)))
            if not n.is_finite():
                errors.append(f"{PARAM_LABELS[key]}不是有效数字")
            elif n <= 0:
                errors.append(f"{PARAM_LABELS[key]}必须大于零")
            elif ("ratio" in key and key != "target_ratio_threshold" and n > 1) or n > 1000000:
                errors.append(f"{PARAM_LABELS[key]}超出范围")
        except (InvalidOperation, ValueError):
            errors.append(f"{PARAM_LABELS[key]}不是有效数字")
    for group in KEYWORDS:
        words = keywords.get(group)
        if not isinstance(words, list) or not words or len(words) > 100:
            errors.append(f"{group}需要1至100个关键词")
        elif any(not isinstance(w, str) or not w.strip() or len(w) > 80 for w in words):
            errors.append(f"{group}包含空白或过长关键词")
    for code, group in overrides.items():
        if not isinstance(code, str) or not code.strip() or group not in (*KEYWORDS, "normal"):
            errors.append("物料类型覆盖无效")
    return errors

def turnover_and_delay(fields, m, future, small, maintenance, params):
    stock = fields["on_hand_qty"]
    net = fields["net_supply_before_plan"]
    parc = fields["vehicle_parc"]
    six_months = fields["avg_sales_6m"]
    def months(qty):
        return qty / m if qty is not None and m and m > 0 else None
    on_hand, pipeline, after = (months(qty) for qty in (stock, net, future))
    if small:
        delay = None if net is None or six_months is None else net >= params["small_delay_qty"] and six_months == 0
    elif maintenance or parc is None or parc < params["delay_vehicle_parc"] or m == 0:
        delay = False
    elif on_hand is None or pipeline is None:
        delay = None
    else:
        # Compare in units so recurring monthly averages do not flip equality at a boundary.
        with localcontext() as precision:
            precision.prec = max(precision.prec, 36)
            delay = (stock > round(m * params["delay_on_hand_months"], 10)
                     and net > round(m * params["delay_net_months"], 10))
    return {"on_hand_months": serial(on_hand), "pipeline_days": serial(pipeline * 30) if pipeline is not None else None,
            "future_days": serial(after * 30) if after is not None else None, "delay_replenishment": delay}

def quantity_advice(mode, status, gap, unit, delay):
    if status == "UNAVAILABLE":
        advice = "计划数据异常，请核实"
    elif mode == "EXEMPT":
        advice = "小件免审核"
    elif mode == "MANUAL":
        advice = "用品精品，按市场需求人工判断"
    elif status in ("ABOVE", "BELOW"):
        suffix = "pcs" if unit in ("PCS", "EA") else unit
        amount = serial(gap)
        whole, point, fraction = amount.partition(".")
        amount = f"{int(whole):,}{point}{fraction}"
        action = "备货多，建议减少" if status == "ABOVE" else "备货少，建议增加"
        advice = f"{action}{amount}{suffix}"
    else:
        advice = "备货合理"
    return advice + ("；建议延迟补货" if delay else "")

def pending_plan_result(item):
    """Record the plan inputs without running any inventory rule."""
    errors, flags = [], []
    for key, label in (('sea_plan_qty', '海运计划'), ('air_plan_qty', '空运计划')):
        try:
            qty = number(item.get(key))
            if qty is None or qty < 0:
                errors.append({'field': key, 'message': label + '应填写非负数'})
            elif key == 'air_plan_qty' and qty > 0:
                flags.append('AIR')
        except ValueError as exc:
            errors.append({'field': key, 'message': label + '：' + str(exc)})
    message = '缺少本仓审核数据，需人工复审'
    return {
        'basis_pending': True, 'data_status': 'ERROR' if errors else 'PENDING',
        'review_mode': 'MANUAL', 'quantity_status': 'UNAVAILABLE', 'rule_id': '',
        'lower_raw': None, 'upper_raw': None, 'lower': None, 'upper': None,
        'future_qty': None, 'quantity_gap': None, 'sea_feasible': None,
        'sea_lower': None, 'sea_upper': None, 'suggested_sea_qty': None,
        'residual_excess': None, 'm': None, 'on_hand_months': None,
        'pipeline_days': None, 'future_days': None, 'delay_replenishment': None,
        'manual_flags': flags, 'errors': errors, 'warnings': [message],
        'matched_keywords': {}, 'override': None, 'advice': '需人工复审',
        'explanation': message, 'precision_version': PRECISION_VERSION,
        'input_hash': fingerprint(item),
    }


def calculate(item, package=None):
    package = package or default_package()
    v2 = package.get("model") == MODEL_V2
    p = {k: Decimal(str(v)) for k, v in package["params"].items()}
    errors, flags, warnings = [], [], []
    fields = {}
    numeric_fields = ("fleet_qty", "avg_sales_3m", "avg_sales_6m", "replacement_rate", "replacement_target", "sales_target",
                      "net_supply_before_plan", "sea_plan_qty", "air_plan_qty", "quantity_step")
    labels = {"fleet_qty": "装车量", "avg_sales_3m": "三个月月均销量", "avg_sales_6m": "六个月月均销量",
              "replacement_rate": "稳态更换率", "replacement_target": "更换率目标", "sales_target": "销量目标",
              "net_supply_before_plan": "审核前净额", "sea_plan_qty": "海运计划", "air_plan_qty": "空运计划", "quantity_step": "订货步长"}
    if v2:
        numeric_fields += ("on_hand_qty", "vehicle_parc")
        labels.update(on_hand_qty="在库数量", vehicle_parc="备件保有量")
    for key in numeric_fields:
        try:
            fields[key] = number(item.get(key, 1 if key == "quantity_step" else None))
            if fields[key] is not None and key != "net_supply_before_plan" and fields[key] < 0:
                errors.append({"field": key, "message": labels[key] + "不能为负数"})
        except ValueError as e:
            fields[key] = None
            errors.append({"field": key, "message": labels[key] + "：" + str(e)})
    def require(*keys):
        for key in keys:
            if fields[key] is None and not any(e["field"] == key for e in errors):
                errors.append({"field": key, "message": labels[key] + "缺失，请补齐来源数据"})
    if not str(item.get("material_code") or "").strip():
        errors.append({"field": "material_code", "message": "物料号不能为空"})
    if not str(item.get("material_name") or "").strip() and not str(item.get("material_type") or "").strip():
        errors.append({"field": "material_name", "message": "缺少物料名称或类型，无法识别分类"})
    require("net_supply_before_plan", "sea_plan_qty", "air_plan_qty", "quantity_step")
    if item.get('uom','PCS') not in ('PCS','EA','SET','L','KG','M'):
        errors.append({'field':'uom','message':'计量单位不在标准合同内，请统一为PCS/EA、SET、L、KG或M并确认数量换算'})
    if fields["quantity_step"] is not None and fields["quantity_step"] <= 0:
        errors.append({"field": "quantity_step", "message": "订货步长必须大于零"})
    if fields["replacement_rate"] is not None and fields["replacement_rate"] > 1:
        errors.append({"field": "replacement_rate", "message": "更换率应以小数或百分号提供，例如0.0015或0.15%"})
    for key in ("sea_plan_qty", "air_plan_qty"):
        if fields[key] is not None and fields["quantity_step"] and fields["quantity_step"] > 0 and fields[key] % fields["quantity_step"]:
            errors.append({"field": key, "message": labels[key] + "不符合订货步长"})
    base = str(item.get("material_name") or "") + str(item.get("material_type") or "")
    hits = {group: [word for word in words if word.casefold() in (base + (str(item.get("material_abc") or "") if group == "maintenance" else "")).casefold()]
            for group, words in package["keywords"].items()}
    override = package.get("overrides", {}).get(str(item.get("material_code")))
    is_type = lambda key: override == key if override else bool(hits[key])
    small, manual, maintenance, dangerous, no_stock = (is_type(k) for k in ("small", "manual", "maintenance", "dangerous", "no_stock"))
    mode = "EXEMPT" if small else "MANUAL" if manual else "AUTO"
    if hits["dangerous"] and (hits["maintenance"] or hits["small"] or hits["manual"]):
        flags.append("COLLISION")
    if fields["air_plan_qty"] is not None and fields["air_plan_qty"] > 0:
        flags.append("AIR")
    if manual and not small:
        flags.append("MANUAL")
    g, x, y, w = (fields[k] for k in ("fleet_qty", "replacement_target", "sales_target", "replacement_rate"))
    a, b = fields["avg_sales_3m"], fields["avg_sales_6m"]
    m = max(a, b) if a is not None and b is not None else None
    fixed = p["fixed_ab"] if item.get("material_abc") in ("A", "B") else p["fixed_non_ab"]
    lower = upper = None
    rule_id, explanation = "", ""
    if small:
        lower, upper, rule_id = Decimal(0), p["small_display_upper"], "UK-R01"
        explanation = "小件免数量审核，参考上限不作为拦截条件。"
    elif no_stock:
        lower, upper, rule_id = Decimal(0), Decimal(0), "UK-R02"
        explanation = "子午线轮胎按本标准不备货。" if v2 else "子午线轮胎采用英国默认不备货规则。"
    elif manual and (g is None or m is None or x is None or y is None):
        explanation = "用品精品按实际市场需求由审核人判断。"
    elif maintenance:
        require("fleet_qty", "avg_sales_3m", "avg_sales_6m")
        if g is not None and m is not None:
            if g < p["fleet_low_threshold"] or m == 0:
                lower, upper = sorted((p["maintenance_fixed"], g * p["maintenance_fleet_low_ratio"]))
                rule_id, explanation = "UK-R03", "保养件低装车量或无销量，比较固定值与装车量比例。"
            else:
                lower, upper = m * p["maintenance_lower_months"], max(m * p["maintenance_upper_months"], g * p["maintenance_fleet_high_ratio"])
                rule_id, explanation = "UK-R04", "保养件按月均销量与装车量计算储备区间。"
    elif dangerous and (g is None or not (g > p["dangerous_fleet_threshold"] and w is not None and w > 0)):
        require("fleet_qty")
        if g is not None:
            lower, upper = sorted((g * p["dangerous_ratio"], p["dangerous_fixed"]))
            rule_id, explanation = "UK-R05", "危包未达到常规分支条件，比较装车量比例与固定值。"
    else:
        require("avg_sales_3m", "avg_sales_6m", "replacement_target")
        if not item.get("material_abc"):
            flags.append("ABC_MISSING")
            warnings.append("分类缺失，固定值仅作参考" if v2 else "分类缺失，固定值仅作为英国参考结果")
        if m == 0:
            require("fleet_qty")
            if g is not None and x is not None:
                lower, upper = (fixed if g < p["fleet_low_threshold"] else min(x, fixed)), max(x, fixed)
                rule_id = "UK-R06" if g < p["fleet_low_threshold"] else "UK-R07"
                explanation = "无销量，比较更换率目标与分类固定值；低装车量采用固定下限。"
        elif m is not None:
            require("sales_target")
            if x is not None and y is not None:
                lower = min(x, y)
                ratio_high = max(x, y) > p["target_ratio_threshold"] * lower if v2 else x > p["target_ratio_threshold"] * y
                if ratio_high:
                    key = item.get("is_key_model")
                    if not isinstance(key, bool):
                        errors.append({"field": "is_key_model", "message": "该分支需要明确是否为重点车型"})
                    upper = m * p["upper_months_key" if key is True else "upper_months_non_key"]
                    rule_id, explanation = "UK-R08", "更换率目标大于销量目标的倍数阈值，上限按重点车型储备月数计算。"
                    if v2:
                        upper = max(upper, lower)
                        explanation = "两目标差距超过倍数阈值，取储备周期数量和下限中的较大值作为上限。"
                else:
                    upper = max(x, y)
                    rule_id, explanation = "UK-R09", "销量目标优先或两目标差距未超过阈值，取较小值为下限、较大值为上限。"
                    if v2:
                        explanation = "两目标在倍数阈值内，取小值为下限、大值为上限。"
                if (w is None or w == 0) and x == 0:
                    flags.append("MISSING_RATE")
    raw_l, raw_u = lower, upper
    if lower is not None and upper is not None:
        lower, upper = uk_round(lower), uk_round(upper)
        if lower > upper:
            errors.append({"field": "rule", "message": "库存下限高于上限，请由规则负责人检查参数"})
    t, sea, air = (fields[k] for k in ("net_supply_before_plan", "sea_plan_qty", "air_plan_qty"))
    future = t + sea + air if all(v is not None for v in (t, sea, air)) else None
    status, gap, feasible, sea_l, sea_u, suggested, residual = "UNAVAILABLE", None, None, None, None, None, None
    if not errors:
        if mode != "AUTO":
            status = "NOT_APPLICABLE"
        elif lower is not None and upper is not None and future is not None:
            status = "BELOW" if future < lower else "ABOVE" if future > upper else "WITHIN"
            gap = lower-future if status == "BELOW" else future-upper if status == "ABOVE" else Decimal(0)
            base_supply = t + air
            step = fields["quantity_step"]
            lo = (max(Decimal(0), lower-base_supply)/step).to_integral_value(rounding=ROUND_CEILING)*step
            hi = ((upper-base_supply)/step).to_integral_value(rounding=ROUND_FLOOR)*step
            feasible = hi >= lo
            if feasible:
                sea_l, sea_u = lo, hi
                suggested = min(max(sea, lo), hi)
                residual = Decimal(0)
            else:
                suggested, residual = Decimal(0), max(Decimal(0), base_supply-upper)
                flags.append("NO_SEA_RANGE")
    timing = {}
    if v2:
        timing = turnover_and_delay(fields, m, future, small, maintenance, p)
        timing["advice"] = quantity_advice(mode, status, gap, item.get("uom") or "PCS", timing["delay_replenishment"])
    return {
        **timing,
        "data_status": "ERROR" if errors else "WARNING" if warnings or "MISSING_RATE" in flags else "VALID",
        "review_mode": mode, "quantity_status": status, "rule_id": rule_id,
        "lower_raw": serial(raw_l), "upper_raw": serial(raw_u), "lower": serial(lower), "upper": serial(upper),
        "future_qty": serial(future), "quantity_gap": serial(gap), "sea_feasible": feasible,
        "sea_lower": serial(sea_l), "sea_upper": serial(sea_u), "suggested_sea_qty": serial(suggested),
        "residual_excess": serial(residual), "manual_flags": list(dict.fromkeys(flags)),
        "matched_keywords": hits, "override": override, "errors": errors, "warnings": warnings,
        "explanation": explanation, "m": serial(m), "precision_version": PRECISION_VERSION,
        "input_hash": fingerprint(item),
    }

def submission_issues(item, result):
    issues = list(result["errors"])
    reason = str(item.get("reason") or "").strip()
    risk_flags = [f for f in result["manual_flags"] if f != "AIR"]
    if (result["quantity_status"] in ("BELOW", "ABOVE") or (result["review_mode"] == "MANUAL" and not result.get('basis_pending')) or risk_flags) and not reason:
        issues.append({"field": "reason", "message": "请说明保留当前计划的原因或需求依据"})
    if reason and not item.get("reason_code"):
        issues.append({"field": "reason_code", "message": "请选择原因类别"})
    if "AIR" in result["manual_flags"] and not str(item.get("air_reason") or "").strip():
        issues.append({"field": "air_reason", "message": "请说明本次空运的必要性"})
    return issues
