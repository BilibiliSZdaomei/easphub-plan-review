from copy import deepcopy
from decimal import Decimal
import pytest
from backend.rules import calculate, default_package, submission_issues

def row(**kw):
    return {"material_code": "DEMO-001", "material_name": "前保险杠", "material_type": "车身件", "material_abc": "A", "is_key_model": True,
            "fleet_qty": "1000", "avg_sales_3m": "10", "avg_sales_6m": "8", "replacement_rate": "0.001",
            "replacement_target": "100", "sales_target": "80", "net_supply_before_plan": "50", "sea_plan_qty": "30",
            "air_plan_qty": "0", "uom": "PCS", "quantity_step": "1", **kw}

@pytest.mark.parametrize("change,expected,rule", [
    ({}, (80,100), "UK-R09"),
    ({"replacement_target":150,"sales_target":100}, (100,150), "UK-R09"),
    ({"replacement_target":151,"sales_target":100}, (100,150), "UK-R08"),
    ({"sales_target":300}, (100,150), "UK-R08"),
    ({"avg_sales_3m":0,"avg_sales_6m":0,"fleet_qty":999,"replacement_target":0}, (12,12), "UK-R06"),
    ({"avg_sales_3m":0,"avg_sales_6m":0,"fleet_qty":1000,"replacement_target":0}, (0,12), "UK-R07"),
    ({"material_name":"动力电池","fleet_qty":10000}, (10,15), "UK-R05"),
    ({"material_name":"动力电池","fleet_qty":10001}, (80,100), "UK-R09"),
    ({"material_name":"制动盘"}, (120,600), "UK-R04"),
    ({"material_name":"制动盘","fleet_qty":999}, (200,500), "UK-R03"),
    ({"material_name":"卡扣","net_supply_before_plan":10001}, (0,10000), "UK-R01"),
    ({"material_name":"子午线轮胎"}, (0,0), "UK-R02"),
])
def test_branches(change, expected, rule):
    r=calculate(row(**change))
    assert not r['errors']
    assert (Decimal(r['lower']), Decimal(r['upper'])) == expected
    assert r['rule_id']==rule

def test_air_fixed_and_no_feasible_sea():
    r=calculate(row(net_supply_before_plan=30,sea_plan_qty=5,replacement_target=28,sales_target=27))
    assert r['quantity_gap']=='7' and r['residual_excess']=='2' and r['suggested_sea_qty']=='0'
    assert r['sea_feasible'] is False and r['sea_lower'] is None

@pytest.mark.parametrize("air, future, status, gap, suggested_sea", [
    (0, "12", "WITHIN", "0", "2"),
    (5, "17", "ABOVE", "2", "0"),
])
def test_quantity_review_counts_planned_air(air, future, status, gap, suggested_sea):
    item = row(net_supply_before_plan=10, sea_plan_qty=2, air_plan_qty=air,
               replacement_target=12, sales_target=15)
    result = calculate(item)
    assert result["future_qty"] == future
    assert result["quantity_status"] == status
    assert result["quantity_gap"] == gap
    assert result["suggested_sea_qty"] == suggested_sea

def test_special_data_error_not_hidden():
    for name in ['套装','卡扣']:
        r=calculate(row(material_name=name,sea_plan_qty='?'))
        assert r['data_status']=='ERROR'

def test_round_not_ceil_and_half_boundary():
    assert calculate(row(replacement_target=189,sales_target='83.3333333333333',avg_sales_3m='8.33333333333333'))['lower']=='83'
    assert calculate(row(replacement_target=34,sales_target='18.3333333333333',avg_sales_3m='1.83333333333333',avg_sales_6m=1))['upper']=='28'

def test_negative_supply_and_equal_boundaries():
    assert calculate(row(net_supply_before_plan=-100))['future_qty']=='-70'
    assert calculate(row(net_supply_before_plan=50,sea_plan_qty=30))['quantity_status']=='WITHIN'
    assert calculate(row(net_supply_before_plan=50,sea_plan_qty=50))['quantity_status']=='WITHIN'

def test_v2_upper_floor_and_legacy_replay():
    item = row(replacement_target=1000, sales_target=200)
    result = calculate(item)
    assert (result['lower'], result['upper'], result['data_status']) == ('200', '200', 'VALID')
    assert calculate(item, default_package('0804'))['data_status'] == 'ERROR'
    assert calculate(row(sales_target=300), default_package('0804'))['upper'] == '300'

def test_priority_collision_and_manual():
    r=calculate(row(material_name='补胎液',fleet_qty=3960,avg_sales_3m=0,avg_sales_6m=0))
    assert (r['lower'],r['upper'])==('200','1980') and 'COLLISION' in r['manual_flags']
    assert calculate(row(material_name='套装'))['review_mode']=='MANUAL'

def test_zero_not_missing_and_branch_required_fields():
    r=calculate(row(replacement_target=0,replacement_rate=None))
    assert r['lower']=='0' and 'MISSING_RATE' in r['manual_flags']
    assert calculate(row(replacement_target=None))['data_status']=='ERROR'
    assert calculate(row(material_name='卡扣',replacement_target=None,sales_target=None,fleet_qty=None,avg_sales_3m=None,avg_sales_6m=None))['data_status']=='VALID'

def test_step_range_has_no_solution():
    r=calculate(row(replacement_target=99,sales_target=98,net_supply_before_plan=0,sea_plan_qty=0,quantity_step=10))
    assert r['sea_feasible'] is False

def test_reasons_and_air_are_independent():
    item=row(air_plan_qty=1,reason='已有订单需求',reason_code='需求变化')
    assert any(x['field']=='air_reason' for x in submission_issues(item,calculate(item)))

def test_versioned_package_does_not_mutate_default():
    p=default_package(); p['params']['fixed_ab']=15
    assert default_package()['params']['fixed_ab']==12
