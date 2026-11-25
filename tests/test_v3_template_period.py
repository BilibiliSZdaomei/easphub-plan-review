from datetime import date
from io import BytesIO
from zipfile import ZipFile

from openpyxl import load_workbook

from backend.adapters import parse_file
from backend.db import Batch, SessionLocal
from backend.periods import previous_sales_months
from backend.template_assets import WORKBOOK_TEMPLATES
from test_api import P, clients, post


def month_headers(content):
    book=load_workbook(BytesIO(content),read_only=True)
    try:
        return [cell.value for cell in next(book['审核表'].iter_rows(min_col=14,max_col=19))]
    finally:
        book.close()


def test_workbook_guides_cover_all_headers_and_highlight_transport_inputs():
    asset,_=WORKBOOK_TEMPLATES['v3']
    book=load_workbook(asset)
    try:
        sheet=book['审核表']
        headers=sheet[1]
        assert len(headers)==43 and all(c.comment and c.comment.text.strip() for c in headers)
        auto=('L','M','AC','AD','AE','AF','AG','AH','AI','AJ','AK','AL','AM')
        for column in auto:
            assert '无需填写' in sheet[column+'1'].comment.text
            assert sheet[column+'2001'].data_type=='f'
        for column in ('X','Y'):
            assert sheet[column+'1'].fill!=sheet['W1'].fill
            assert sheet[column+'2'].fill.fgColor==sheet.column_dimensions[column].fill.fgColor
            assert sheet[column+'2'].fill.fgColor!=sheet['AC2'].fill.fgColor
            assert sheet[column+'2'].value is None
    finally:
        book.close()


def test_plan_bound_download_and_import_keeps_the_correct_calendar_months(clients):
    planner,_,_,other=clients
    monthly=post(planner,'/batches',{'warehouse':'UK_MAIN','period':'2026-02','title':'月度计划'}).json()
    weekly=post(planner,'/batches',{'warehouse':'UK_MAIN','period':'2026-W01','title':'周度计划'}).json()
    url=P+'/template'
    def download(batch):
        return planner.get(url,params={'kind':'v3','version_id':batch['current_id']})
    response=download(monthly)
    assert response.status_code==200 and '2026-02.xlsx' in response.headers['content-disposition']
    expected=[m+' 销量' for m in ('2025-08','2025-09','2025-10','2025-11','2025-12','2026-01')]
    assert month_headers(response.content)==expected
    # Monday of ISO week 1 lies in December 2025. December is still incomplete.
    assert month_headers(download(weekly).content)==[f'2025-{i:02d} 销量' for i in range(6,12)]
    assert download(monthly).content==response.content
    assert other.get(url,params={'kind':'v3','version_id':monthly['current_id']}).status_code==403
    assert planner.get(url,params={'kind':'v3','version_id':'missing'}).status_code==404
    assert planner.get(url,params={'kind':'v3','version_id':monthly['current_id'],'period':'2026-03'}).status_code==422

    asset,_=WORKBOOK_TEMPLATES['v3']
    with ZipFile(asset) as original, ZipFile(BytesIO(response.content)) as dated:
        assert set(original.namelist())==set(dated.namelist())
        assert all(original.read(part)==dated.read(part) for part in original.namelist() if part!='xl/worksheets/sheet1.xml')
        sheet_part='xl/worksheets/sheet1.xml'
        assert original.read(sheet_part).split(b'</row>',1)[1]==dated.read(sheet_part).split(b'</row>',1)[1]
    book=load_workbook(BytesIO(response.content))
    try:
        sheet=book['审核表']
        sheet['A2']='M-2026';sheet['X2']=1
        for n,letter in enumerate('NOPQRS',1):sheet[f'{letter}2']=n
        edited=BytesIO()
        book.save(edited)
    finally:
        book.close()
    result=parse_file(edited.getvalue(),'月份.xlsx','plan')
    assert result['plan_format']=='v3' and not result['issues']
    item,=result['items']
    assert item['month_labels']==expected
    assert item['monthly_sales']==dict(zip(expected,map(str,range(1,7))))
    assert (item['avg_sales_3m'],item['avg_sales_6m'])==('5','3.5')


def test_generic_and_legacy_downloads_use_explicit_month_or_current_month(clients):
    planner=clients[0]
    url=P+'/template'
    generic=planner.get(url,params={'kind':'v3','period':'2027-01'})
    assert month_headers(generic.content)==[f'2026-{i:02d} 销量' for i in range(7,13)]
    calendar=date.today().isoformat()[:7]
    assert month_headers(planner.get(url,params={'kind':'v3'}).content)==[m+' 销量' for m in previous_sales_months(calendar)]
    assert planner.get(url,params={'kind':'v3','period':'2026-13'}).status_code==422
    batch=post(planner,'/batches',{'warehouse':'UK_MAIN','period':'2027-01','title':'历史计划'}).json()
    with SessionLocal.begin() as db:
        db.get(Batch,batch['id']).period='手工历史周期'
    bound={'kind':'v3','version_id':batch['current_id']}
    assert planner.get(url,params=bound).status_code==422
    assert month_headers(planner.get(url,params={**bound,'period':'2027-01'}).content)==month_headers(generic.content)
