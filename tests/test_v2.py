from io import BytesIO

import pytest
from openpyxl import load_workbook

from backend.adapters import parse_file
from backend.exporting import export_workbook
from backend.jobs import deliver_notifications
from backend.rules import calculate, default_package
from test_api import clients, P, post
from test_data import upload
from test_rules import row


@pytest.mark.parametrize("stock, net, parc, expected", [
    (5, 10, 10000, True), (4, 10, 10000, False), (5, 9, 10000, False),
    (5, 10, 9999, False), (5, 10, None, False), (None, 10, 10000, None),
])
def test_delay_uses_both_pre_order_thresholds(stock, net, parc, expected):
    item = row(avg_sales_3m=1, avg_sales_6m=1, on_hand_qty=stock,
               net_supply_before_plan=net, vehicle_parc=parc, air_plan_qty=50)
    result = calculate(item)
    assert result['delay_replenishment'] is expected
    assert ('建议延迟补货' in result['advice']) == bool(expected)
    assert calculate({**item, 'material_name':'制动盘'})['delay_replenishment'] is False


@pytest.mark.parametrize("net, six, expected", [(150, 0, True), (149, 0, False), (200, 1, False)])
def test_small_parts_use_net_supply_even_below_parc_threshold(net, six, expected):
    result = calculate(row(material_name='固定螺栓', vehicle_parc=10, on_hand_qty=500,
                           net_supply_before_plan=net, avg_sales_6m=six, avg_sales_3m=0))
    assert result['delay_replenishment'] is expected
    assert result['review_mode'] == 'EXEMPT' and result['suggested_sea_qty'] is None


def test_snapshot_template_colors_follow_formula_and_import_roles(clients):
    response=clients[0].get(P+'/template?kind=v2')
    assert response.status_code==200
    workbook=load_workbook(BytesIO(response.content))
    sheet=workbook['审核表']
    assert workbook['填写说明'].sheet_state=='visible'
    guide=' '.join(str(cell.value) for cells in workbook['填写说明'] for cell in cells if cell.value)
    assert all(label in guide for label in ('公式','备注','Review Logic'))
    formula_cols=('K','L','AB','AC','AD','AE','AF','AG','AH','AI','AJ','AK')
    ignored_cols=('J','S','T','AL','AM','AN')
    input_cols=('A','B','G','M','R','U','V','W','X','Y','Z','AA','AO')
    for row_num in (1,2,101):
        formula_fill=sheet[f'K{row_num}'].fill
        ignored_fill=sheet[f'J{row_num}'].fill
        input_fill=sheet[f'M{row_num}'].fill
        assert formula_fill.patternType=='solid'
        assert len({color.fgColor.value for color in (formula_fill,ignored_fill,input_fill)})==3
        for columns, expected in ((formula_cols,formula_fill),(ignored_cols,ignored_fill),(input_cols,input_fill)):
            for col in columns:
                cell=sheet[f'{col}{row_num}']
                assert (cell.fill.patternType,cell.fill.fgColor) == (expected.patternType,expected.fgColor), cell.coordinate
                if row_num != 1:
                    assert (cell.data_type=='f') == (col in formula_cols), cell.coordinate
    workbook.close()


def test_downloaded_v2_template_imports_without_excel_cached_results(clients):
    planner, _, _, _ = clients
    file = planner.get(P+'/template?kind=v2')
    assert file.status_code == 200
    workbook = load_workbook(BytesIO(file.content))
    assert workbook.active.title == '审核表'
    assert 'Review Logic' in workbook.sheetnames
    sheet = workbook['审核表']
    assert all(sheet[f'A{i}'].value is None for i in range(2, sheet.max_row+1))
    for col, value in {'A':'001','B':'总成','D':'腾势','G':None,'H':20,'I':10000,
                       'M':3,'N':0,'O':0,'P':0,'Q':0,'R':0,'U':3,'V':5,'W':2,'X':1,
                       'Z':18,'AA':3,'AK':'手填的审批建议','AL':'不同意','AM':99,'AN':'不同意','AO':'测试备注'}.items():
        sheet[f'{col}2']=value
    buf=BytesIO(); workbook.save(buf)
    data=parse_file(buf.getvalue(), 'input.xlsx')
    assert data['kind']=='v2' and len(data['items'])==1
    item=data['items'][0]
    assert (item['vehicle_model'],item['vehicle_parc'],item['source_note'])==('腾势','10000','测试备注')
    assert item['is_key_model'] is False and item['avg_sales_3m']=='0' and item['avg_sales_6m']=='0.5'
    result=calculate(item)
    assert (result['future_qty'],result['future_days'],result['on_hand_months'],result['upper'])==('8','480','6','6')
    assert result['delay_replenishment'] and item['source']['adapter']=='PLAN-V2'
    assert result['advice'] != '手填的审批建议'
    assert (item['sea_plan_qty'],item['air_plan_qty']) == ('2','1')

    # A warehouse can omit all workbook review results when uploading its snapshot.
    sheet.delete_cols(28, sheet.max_column - 27)
    without_reviews=BytesIO(); workbook.save(without_reviews); workbook.close()
    job=upload(clients[2], 'v2', without_reviews.getvalue(), '库存与销量.xlsx')
    assert job['state']=='DONE' and job['rows']==1 and not job['issues'], job
    clean=job['preview'][0]
    assert not clean.get('source_note')
    assert (clean['avg_sales_3m'],clean['avg_sales_6m']) == ('0','0.5')
    recalculated=calculate(clean)
    for field in ('future_qty','future_days','on_hand_months','lower','upper','delay_replenishment','advice'):
        assert recalculated[field] == result[field]


def test_v2_workbook_through_review_and_export(clients):
    from synthetic_workbooks import v2_inventory
    planner, _, steward, _ = clients
    content, examples = v2_inventory()
    job=upload(steward,'v2',content,'合成V2.xlsx')
    assert job['state']=='DONE' and job['rows']==10 and not job['issues'] and not job['validation']
    committed=post(steward,'/imports/'+job['id']+'/commit',{'name':'V2 原表示例','as_of':'2026-11-23','basis':'审核前净额'})
    assert committed.status_code==200
    batch=post(planner,'/batches',{'warehouse':'UK_MAIN','snapshot_id':committed.json()['snapshot_id'],
                                    'title':'V2 核验','period':'2026-11','use_snapshot_plan':True}).json()
    version=planner.get(P+'/versions/'+batch['current_id']).json()
    assert version['rule']['model']=='V2' and version['summary']['delay']==6
    assert version['summary']['attention']==8
    confirm=planner.get(P+'/versions/'+version['id']+'/confirmation?stage=submit').json()
    assert confirm['affected_count']==8
    while deliver_notifications(): pass
    notices=planner.get(P+'/notifications').json()
    assert any(n['batch_id']==batch['id'] and n['text'].endswith('8 行审核提醒') for n in notices)
    assert planner.get(P+'/versions/'+version['id'],params={'filter':'delay'}).json()['total']==6
    for entry in version['items']:
        row_num = entry['input']['source']['row']
        future, months, days, delay, advice = examples[row_num]
        result = entry['result']
        assert tuple(float(result[key]) for key in ('future_qty', 'on_hand_months', 'future_days')) == (future, months, days)
        assert result['lower'] == result['upper'] == '12'
        assert (result['delay_replenishment'], result['advice']) == (delay, advice)
    old=default_package('0804')
    i=version['items'][0]['input']
    historical=calculate(i,old)
    assert 'delay_replenishment' not in historical
    replay=load_workbook(BytesIO(export_workbook({'items':[{'input':i,'result':historical}],'rule_package':old})))
    assert replay.active['AI2'].value is None and replay.active.max_column==51
    replay.close()
