from decimal import Decimal
from io import BytesIO

from openpyxl import load_workbook

from backend.exporting import export_workbook
from backend.rules import MODEL_V3, calculate, default_package
from test_api import P, clients, post
from test_data import upload
from test_rules import row


def test_v3_export_keeps_calculated_inputs_live_and_source_values_distinct():
    package = default_package(MODEL_V3)
    package['overrides'] = {'MAT-*':'small'}
    months = dict(zip('ABCDEF', [0, None, 3, 2, 1, 3]))
    item = row(material_code='MAT-*', material_name='冷却液', monthly_sales=months,
               month_labels=list(months), avg_sales_3m=2, avg_sales_6m=1.8,
               on_hand_qty=8, in_transit_qty=4, on_order_qty=5, demand_deduction_qty=2,
               net_supply_before_plan=15)
    old = row(material_code='OLD', avg_sales_3m=9, avg_sales_6m=6, on_hand_qty=4)
    rows = [{'input':i, 'result':calculate(i,package)} for i in (item,old)]
    book = export_workbook({'items':rows, 'rule_package':package, 'net_mode':'COMPONENTS'})
    with_values = load_workbook(BytesIO(book),data_only=True)
    assert with_values.worksheets[0]['AE2'].value == 2 and with_values.worksheets[0]['AF2'].value == 1.8
    assert with_values['计算依据']['B2'].value == 1 and with_values['计算依据']['Z2'].value == 'small'
    with_values.close()
    formulas = load_workbook(BytesIO(book))
    ws = formulas['计划审核结果']
    for ref in ('E2','AE2','AF2','J2','L2','BC2','BG2'):
        assert ws[ref].data_type == 'f'
    assert ws['AE3'].data_type == 'n' and ws['AE3'].value == 9
    assert formulas['计算依据']['O2'].value is None and formulas['计算依据']['N2'].value == 0
    formulas.close()


def test_versioned_supply_sea_range_and_missing_stock():
    item = row(on_hand_qty=4, net_supply_before_plan=0, sea_plan_qty=2, air_plan_qty=20,
               avg_sales_3m=1, avg_sales_6m=1, replacement_target=5, sales_target=6)
    v3 = default_package(MODEL_V3)
    result = calculate(item, v3)
    assert (result['future_qty'], result['quantity_status'], result['future_days']) == ('6', 'WITHIN', '180')
    assert (result['sea_lower'], result['sea_upper'], result['suggested_sea_qty']) == ('1', '2', '2')
    assert 'AIR' in result['manual_flags']
    assert calculate({**item, 'air_plan_qty':1}, v3)['future_qty'] == '6'
    assert calculate(item, default_package('V2'))['future_qty'] == '22'
    for field in ('on_hand_qty','net_supply_before_plan'):
        missing = calculate({**item, field:None}, v3)
        assert missing['future_qty'] is None and missing['quantity_status'] == 'UNAVAILABLE'
    excess = calculate({**item, 'on_hand_qty':9}, v3)
    assert excess['sea_feasible'] is False and excess['residual_excess'] == '3'


def test_warning_boundaries_and_delay_are_independent():
    v3 = default_package(MODEL_V3)
    monthly = Decimal(1)/3
    item = row(avg_sales_3m=monthly, avg_sales_6m=monthly, on_hand_qty=0,
               net_supply_before_plan=0, air_plan_qty=7)
    for sea, warning in [(0,'周转过低'), (1,None), (3,None), (4,'周转过高')]:
        result = calculate({**item, 'sea_plan_qty':sea}, v3)
        assert result['turnover_warning'] == warning and result['delay_replenishment'] is False
    item.update(on_hand_qty=5, net_supply_before_plan=10, fleet_qty=10000, vehicle_parc=None,
                avg_sales_3m=1, avg_sales_6m=1)
    assert calculate(item,v3)['delay_replenishment'] is True
    assert calculate({**item,'vehicle_parc':0},v3)['delay_replenishment'] is False
    assert calculate({**item,'material_name':'固定螺栓'},v3)['turnover_warning'] is None


def test_v3_template_import_publish_and_history(clients):
    planner, reviewer, steward, _ = clients
    template=planner.get(P+'/template?kind=v3')
    assert template.status_code==200
    wb=load_workbook(BytesIO(template.content)); sheet=wb['审核表']
    assert sheet['J1'].value=='未来装车量' and sheet['AG1'].value=='周转预警'
    assert 'V2+W2+X2' in sheet['AC2'].value
    for col,value in {'A':'PART-V3','B':'座椅支架','F':'A','G':'Y','H':18000,'J':19000,
                      'V':4,'W':0,'X':2,'Y':20,'AA':5,'AB':6,'AC':999}.items():
        sheet[f'{col}2']=value
    for col in 'NOPQRS': sheet[f'{col}2']=1
    sheet['A3']='NO-NET'; sheet['B3']='固定螺栓'; sheet['X3']=3
    buf=BytesIO(); wb.save(buf); wb.close()
    job=upload(steward,'v3',buf.getvalue(),'source.xlsx')
    assert job['state']=='DONE' and job['rows']==2 and job['preview'][0]['future_fleet_qty']=='19000'
    snap=post(steward,'/imports/'+job['id']+'/commit',{'name':'V3 test','as_of':'2026-11-24','basis':'已有净额'}).json()['snapshot_id']
    def plan(title):
        response=post(planner,'/batches',{'warehouse':'UK_MAIN','snapshot_id':snap,
                      'title':title,'period':'2026-11','use_snapshot_plan':True})
        return P+'/versions/'+response.json()['current_id']
    previous=plan('历史标准')
    original=planner.get(previous).json()
    rule=post(reviewer,'/rules',{'source_id':original['rule']['id'],'model':'V3','name':'测试 V3'}).json()
    path='/rules/'+rule['id']
    trial=post(reviewer,path+'/dry-run',{'snapshot_id':snap,'revision':rule['revision']}).json()
    assert not trial['proof']['new_errors']
    assert post(reviewer,path+'/publish',{'revision':trial['revision'],'reason':'验证 V3'}).status_code==200
    current=planner.get(plan('新标准')).json()
    by_code={r['input']['material_code']:r['result'] for r in current['items']}
    assert current['rule']['model']=='V3' and by_code['PART-V3']['future_qty']=='6'
    assert by_code['NO-NET']['future_qty'] is None
    assert planner.get(previous).json()['items']==original['items']
