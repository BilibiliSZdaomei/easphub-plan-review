from decimal import Decimal, InvalidOperation


def number(value):
    if value is None or str(value).strip().lower() in ("", "none", "null", "nan", "nat"):
        return None
    if isinstance(value, bool):
        raise ValueError("布尔值不能作为数量")
    try:
        text = str(value).strip()
        n = Decimal(text[:-1]) / 100 if text.endswith("%") else Decimal(text)
        if not n.is_finite() or n.copy_abs() > Decimal("1e12"):
            raise ValueError("数值超出允许范围")
        return n
    except (InvalidOperation, ValueError):
        raise ValueError("请输入有效数字，不能使用问号或说明文字")

def serial(n):
    if n is None:
        return None
    s = format(n, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s
