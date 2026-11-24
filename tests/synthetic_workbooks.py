"""Generate test-only workbooks in memory from public column contracts."""
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook


def workbook_bytes(book):
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def legacy_inventory():
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    headers = [f"历史字段{i}" for i in range(1, 33)]
    headers[19:21] = ["库存+在途-需求", "海运计划"]
    sheet.append(headers)
    for idx in range(688):
        row = [None] * len(headers)
        row[:7] = [f"FIXTURE-0804-{idx:04}", "示例总成", "普通件", "A", "A", "Y", 2000]
        row[8:10] = [1, 1]
        row[18:25] = [2, 12, "需核实" if idx < 7 else 0, 0, 0.01, 12, 12]
        sheet.append(row)
    return workbook_bytes(book)


def v2_inventory():
    template = Path(__file__).resolve().parents[1] / "backend/templates/plan-review-v2.xlsx"
    book = load_workbook(template)
    sheet = book["审核表"]
    expectations = {}
    for idx in range(10):
        row_num = idx + 2
        if idx < 6:
            stock, net, sea = 5, 12, 0
            expected = (12, 5, 360, True, "备货合理；建议延迟补货")
        elif idx < 8:
            stock, net, sea = 2, 3, 0
            expected = (3, 2, 90, False, "备货少，建议增加9pcs")
        else:
            stock, net, sea = 1, 11, 1
            expected = (12, 1, 360, False, "备货合理")
        fields = {
            "A": f"FIXTURE-V2-{idx:03}", "B": "示例总成", "C": "普通件", "D": "示例车型",
            "E": "A", "F": "A", "G": "Y", "H": 2000, "I": 12000,
            "U": stock, "V": net, "W": sea, "X": 0, "Y": 0.01, "Z": 12, "AA": 12,
        }
        fields.update(dict.fromkeys("MNOPQR", 1))
        for column, value in fields.items():
            sheet[f"{column}{row_num}"] = value
        expectations[row_num] = expected
    return workbook_bytes(book), expectations
