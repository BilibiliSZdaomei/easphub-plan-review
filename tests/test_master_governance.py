from io import BytesIO

import pytest
from openpyxl import load_workbook

from backend.db import SessionLocal, User, Version
from sqlalchemy import select
from backend.exporting import export_workbook
from backend.governance import apply_governance, effective_input
from backend.master_import import read_master
from backend.rules import calculate, default_package, validate_package
from test_api import P, clients, current, post
from test_rules import row
from test_snapshotless_plan import ok


def governed():
    return {
        **default_package('V3'),
        'master_data':{'warehouse':'UK_MAIN','items':{'M1':{
            'material_abc':'A', 'material_name':'核定配件', 'replacement_rate':'0.15%',
            'replacement_target':'47','sales_target':'32','sales_months':'4'}}},
        'target_policy':{'window':'max','rounding':'up','classes':{
            '*':{'replacement_months':'6','sales_months':'2'},'A':{'replacement_months':'8'}}},
    }


def test_sku_policy_uses_approved_rate_and_keeps_sources_and_live_export():
    pkg=governed()
    item=row(material_code='M1',fleet_qty='5900',on_hand_qty='8',material_abc='C',avg_sales_3m='2.3',
             avg_sales_6m='1.4',replacement_rate='0.99',replacement_target='850',sales_target='810')
    other={**item,'material_code':'OTHER'}
    missing={**item,'fleet_qty':None,'avg_sales_3m':None}
    assert not validate_package(pkg)
    rows=[{'input':i,'result':calculate(i,pkg)} for i in (item,other,missing)]
    eff,unmatched,fallback=map(effective_input,rows)
    assert (eff['replacement_rate'],eff['replacement_target'],eff['sales_target'],eff['material_abc'])==('0.0015','71','10','A')
    assert (unmatched['replacement_target'],unmatched['sales_target'])==('850','5')
    assert (fallback['replacement_target'],fallback['sales_target'])==('47','32')
    assert item['replacement_target']=='850'
    export=export_workbook({'items':rows,'rule_package':pkg,'metadata':{}})
    with_formulas=load_workbook(BytesIO(export))
    sheet=with_formulas.worksheets[0]
    assert 'ROUNDUP(AK2*AD2*' in sheet['T2'].value and 'ROUNDUP(AG2*' in sheet['U2'].value
    assert sheet['AK2'].data_type=='f' and with_formulas['计算依据']['AF2'].value==0.0015
    assert sheet['T3'].data_type=='n' and sheet['T3'].value==850
    assert sheet['T4'].data_type=='f' and with_formulas['计算依据']['AD4'].value==47
    with_formulas.close()
    cached=load_workbook(BytesIO(export),data_only=True)
    assert [[cached.worksheets[0][f'{col}{n}'].value for col in 'TU'] for n in (2,3,4)]==[[71,10],[850,5],[47,32]]
    assert cached['计算依据']['A2'].value=='M1' and cached['计算依据']['A3'].value=='OTHER'
    cached.close()
    record=pkg['master_data']['items']['M1']
    record.update(use_fixed_targets=True,replacement_rate='0',replacement_target='0')
    assert apply_governance(item,pkg)[0]['replacement_target']=='0'
    assert apply_governance(item,pkg)[0]['sales_target']=='32'
    del record['use_fixed_targets']
    assert apply_governance(item,pkg)[0]['replacement_target']=='0'


@pytest.mark.parametrize(('rounding','window','target'),[('up','3m','10'),('down','6m','5'),('nearest','6m','6'),('raw','3m','9.2')])
def test_target_windows_and_rounding(rounding,window,target):
    pkg=governed()
    pkg['target_policy'].update(window=window,rounding=rounding)
    item=row(material_code='M1',avg_sales_3m='2.3',avg_sales_6m='1.4')
    assert apply_governance(item,pkg)[0]['sales_target']==target


def test_master_import_treats_blank_zero_and_duplicates_separately():
    raw='物料号,更换率,目标库存-销量,重点车型\n001,0%,,否\n002,,0,\n'
    parsed=read_master(raw.encode(),'master.csv')
    assert parsed=={'001':{'replacement_rate':'0','is_key_model':False},'002':{'sales_target':'0'}}
    with pytest.raises(ValueError,match='第 4 行'):
        read_master((raw+'001,1%,2,是\n').encode(),'master.csv')
    pkg=governed()
    pkg['master_data']['items']['M1']['replacement_months']='-1'
    assert validate_package(pkg)


def test_role_scope_publish_and_recalculate_existing_plan_without_snapshot(clients):
    planner,reviewer,admin,_=clients
    with SessionLocal.begin() as db:
        reviewer_account=db.scalar(select(User).where(User.username=='test_reviewer'))
        reviewer_account.roles=['REVIEWER']
        reviewer_account.warehouses=['UK_MAIN']
        db.scalar(select(User).where(User.username=='test_steward')).roles=['ADMIN']
    def preview(c,wh='UK_MAIN'):
        return c.post(P+'/rules/master-preview',data={'warehouse':wh},
                      files={'file':('m.csv','物料号,稳态更换率,备件描述\nM1,0.15%,核定配件'.encode())})
    assert preview(planner).status_code==403
    assert preview(reviewer,'DE_NSC').status_code==403
    assert ok(preview(reviewer))['items']['M1']['replacement_rate']=='0.0015'
    assert preview(admin).status_code==200
    assert planner.get(P+'/rules/master-template').status_code==403
    assert '更换率' in reviewer.get(P+'/rules/master-template').content.decode('utf-8-sig')
    batch,old=current(planner)
    draft_plan=ok(post(planner,'/batches',{'warehouse':'UK_MAIN','title':'无快照重算','period':'2026-11'}))
    path='/versions/'+draft_plan['current_id']
    source={'material_code':'M1','material_name':'当期说明','sea_plan_qty':'3','air_plan_qty':'0',
            'reference':{'monthly_sales':[1,1,1,2,2,2],'fleet_qty':'5900','on_hand_qty':'8','net_supply_before_plan':'2',
                         'replacement_target':'850','sales_target':'810','replacement_rate':'0.99'}}
    ok(post(planner,path+'/items',{'revision':ok(planner.get(P+path))['revision'],'items':[source]}))
    before=ok(planner.get(P+path))
    pkg=governed()
    body={'source_id':old['rule']['id'],'name':'仓库主数据试算','scope':'WAREHOUSE','scope_code':'UK_MAIN','model':'V3','package':pkg}
    assert post(planner,'/rules',body).status_code==403
    assert post(reviewer,'/rules',{**body,'scope_code':'DE_NSC'}).status_code==403
    assert post(admin,'/rules',{**body,'scope_code':'DE_NSC'}).status_code==422
    draft=ok(post(admin,'/rules',body))
    rp='/rules/'+draft['id']
    saved=ok(reviewer.patch(P+rp,json={'revision':draft['revision'],'package':pkg}))
    trial=ok(post(reviewer,rp+'/dry-run',{'revision':saved['revision'],'snapshot_id':old['snapshot']['id']}))
    assert not trial['proof']['new_errors']
    published=ok(post(reviewer,rp+'/publish',{'revision':trial['revision'],'reason':'核定口径'}))
    assert ok(planner.get(P+path))['items']==before['items']
    assert ok(planner.get(P+'/versions/'+old['id']))['items']==old['items']
    assert reviewer.patch(P+rp,json={'revision':published['revision'],'package':pkg}).status_code==409
    copied=ok(post(admin,'/rules',{'source_id':draft['id'],'scope':'WAREHOUSE','scope_code':'DE_NSC'}))
    assert 'master_data' not in copied['package'] and copied['package']['target_policy']==pkg['target_policy']
    switch={'revision':before['revision'],'rule_id':draft['id'],'snapshot_id':None}
    report=ok(post(planner,path+'/snapshot-preview',switch))
    assert report['snapshot'] is None and report['affected_count']==1
    ok(post(planner,path+'/basis',switch))
    version=ok(planner.get(P+path))
    entry=version['items'][0]; key=entry['id']
    assert entry['input']['replacement_target']=='71' and entry['input']['sales_target']=='8'
    assert entry['input']['material_name']=='核定配件'
    assert ok(planner.get(P+path+'/material-basis',params={'code':'M1'}))['basis']['values']['material_name']=='核定配件'
    assert ok(planner.get(P+path+'/material-basis',params={'code':'M2'}))['basis']['values']=={}
    assert ok(planner.get(P+path,params={'q':'核定配件'}))['total']==1
    with SessionLocal() as db:
        raw=db.get(Version,version['id']).items[0]['input']
        assert raw['replacement_rate']=='0.99' and raw['sales_target']=='810'
    def change(fields):
        return planner.patch(P+path+'/items',json={'revision':version['revision'],'changes':[{'id':key,'reference':fields}]})
    assert change({'replacement_rate':'1'}).status_code==422
    assert change({'sales_target':'0'}).status_code==422
    ok(change({'fleet_qty':'6000','monthly_sales':[0,0,0,4,4,4]}))
    entry=ok(planner.get(P+path+'/items/'+key))
    assert entry['input']['replacement_target']=='72' and entry['input']['sales_target']=='16'
    # A technical-only legacy account must be reassigned by an administrator.
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.username=='test_reviewer')).roles=['RULE_EDITOR','RULE_PUBLISHER']
    assert reviewer.get(P+'/rules').status_code==401
    assert post(reviewer,'/rules',body).status_code==401
    assert preview(reviewer).status_code==401
