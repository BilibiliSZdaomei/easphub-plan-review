from backend.rules import calculate,submission_issues

def test_null_explanations_never_count_as_filled():
    # A valid numeric fixture with risk and explicit null strings from CSV.
    i={'material_code':'M1','material_name':'诊断工具','fleet_qty':2000,'avg_sales_3m':10,'avg_sales_6m':8,'replacement_rate':0.01,'replacement_target':80,'sales_target':100,'material_abc':'A','is_key_model':True,'net_supply_before_plan':50,'sea_plan_qty':35,'air_plan_qty':1,'reason':None,'reason_code':'特殊物料','air_reason':None}
    issues=submission_issues(i,calculate(i));fields={e['field'] for e in issues}
    assert {'reason','air_reason'}<=fields
    i['material_name']=None;i['material_type']=None
    assert any(e['field']=='material_name' for e in calculate(i)['errors'])
