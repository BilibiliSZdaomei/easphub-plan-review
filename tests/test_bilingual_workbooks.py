from io import BytesIO
from zipfile import ZipFile

from openpyxl import load_workbook

from backend.adapters import parse_file
from backend.template_assets import WORKBOOK_TEMPLATES
from test_api import P, clients


def test_english_v3_preserves_formulas_and_can_be_imported(clients):
    response = clients[0].get(P + '/template?kind=v3&period=2026-11&lang=en')
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as english, ZipFile(WORKBOOK_TEMPLATES['v3'][0]) as original:
        sheet = 'xl/worksheets/sheet1.xml'
        assert english.read(sheet).split(b'</row>', 1)[1] == original.read(sheet).split(b'</row>', 1)[1]
        assert english.read('xl/worksheets/sheet3.xml') == original.read('xl/worksheets/sheet3.xml')
    book = load_workbook(BytesIO(response.content))
    sheet = book['审核表']
    assert sheet['N1'].value == '2026-05 sales\n2026-05 销量'
    assert 'Required' in sheet['T1'].comment.text and 'Required' in sheet['U1'].comment.text
    assert all(c.comment for c in sheet[1]) and sheet['AC2'].data_type == 'f'
    assert book.worksheets[1]['A1'].value == 'V3 plan review instructions'
    sheet['A2'], sheet['B2'], sheet['W2'], sheet['X2'] = 'T001', '客户原文', 17, 6
    sheet['T2'] = sheet['U2'] = 0
    for pos, col in enumerate('NOPQRS', 1):
        sheet[col+'2'] = pos
    edited = BytesIO()
    book.save(edited)
    book.close()
    result = parse_file(edited.getvalue(), 'full.xlsx', 'plan')
    row, = result['items']
    assert result['plan_format'] == 'v3' and not result['issues']
    assert row['material_name'] == '客户原文' and row['sea_plan_qty'] == '6'
    assert (row['avg_sales_3m'], row['avg_sales_6m']) == ('5', '3.5')


def test_english_quantity_template_preserves_zero_blank_and_reason(clients):
    response = clients[0].get(P + '/template?kind=plan&lang=en')
    assert response.status_code == 200
    book = load_workbook(BytesIO(response.content))
    sheet = book.worksheets[0]
    assert sheet['A1'].value.startswith('Material number\n') and len(sheet[1]) == 7
    assert all(cell.comment for cell in sheet[1])
    assert 'Confirmed order' in sheet.data_validations.dataValidation[0].formula1
    sheet['A2'], sheet['D2'], sheet['E2'] = 'M002', 0, 'Confirmed order'
    edited = BytesIO()
    book.save(edited)
    book.close()
    result = parse_file(edited.getvalue(), 'quantities.xlsx', 'plan')
    line, = result['items']
    assert not result['issues']
    assert line['reason_code'] == '已确认特殊订单'
    assert line['source_values']['sea_plan_qty'] is None and line['source_values']['air_plan_qty'] == '0'
