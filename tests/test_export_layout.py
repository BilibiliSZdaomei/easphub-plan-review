from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from backend.jobs import FILES, run_job
from backend.template_assets import WORKBOOK_TEMPLATES
from test_api import P, clients, post
from test_data import upload


def workbook_bytes(book):
    data=BytesIO()
    book.save(data)
    book.close()
    return data.getvalue()


def export_bytes(planner, version_id, **options):
    response=post(planner,'/exports',{'version_id':version_id,**options})
    assert response.status_code==200,response.text
    job_id=response.json()['id']
    run_job(job_id)
    result=planner.get(P+'/jobs/'+job_id).json()
    assert result['state']=='DONE',result
    return planner.get(result['download_url']).content


def test_workbook_version_layout_after_quantity_update_and_empty_filter(clients):
    planner,*_=clients
    batch=post(planner,'/batches',{'warehouse':'UK_MAIN','title':'导出版式测试','period':'2026-11'}).json()
    vid=batch['current_id']
    def commit(blob,mode):
        imported=upload(planner,'plan',blob,'计划.xlsx')
        before=planner.get(P+'/versions/'+vid).json()
        res=post(planner,'/imports/'+imported['id']+'/commit',{'version_id':vid,'revision':before['revision'],'mode':mode})
        assert res.status_code==200,res.text
        return imported['id']
    template=load_workbook(WORKBOOK_TEMPLATES['v3'][0],read_only=True)
    headers=list(next(template['审核表'].values))
    template.close()
    months=[f'样例 {n} 月' for n in range(1,7)]
    headers[13:19]=months
    book=Workbook()
    sheet=book.active
    sheet.title='审核表'
    sheet.append(headers)
    sheet.freeze_panes='B2'
    sheet.column_dimensions['X'].width=31
    sheet['X1'].fill=PatternFill('solid',fgColor='FDDA55')
    book.create_sheet('其他仓的物料').append(['其他仓机密'])
    for n,code in enumerate(('A-SELECT','B-HIDDEN'),2):
        for col,value in {'A':code,'B':'普通件','F':'A','H':3000,'T':0,'U':0,'V':4,'W':12,'X':3,'Y':1,
                          'AA':20,'AB':20,'AN':'旧审批','AQ':'旧备注'}.items():
            sheet[col+str(n)]=value
        for col in range(14,20): sheet.cell(n,col,3)
    original_id=commit(workbook_bytes(book),'replace')
    small=Workbook()
    small.active.append(['物料号','海运计划','空运计划'])
    small.active.append(['A-SELECT',10,None])
    commit(workbook_bytes(small),'update_quantities')
    content=export_bytes(planner,vid,scope='filtered',q='A-SELECT')
    formulas=load_workbook(BytesIO(content))
    main=formulas.active
    assert main.title=='审核表' and main.max_row==2 and main.max_column==43 and main.freeze_panes=='B2'
    assert main.column_dimensions['X'].width==31 and main['X1'].fill.fgColor.rgb.endswith('FDDA55')
    assert [main.cell(1,n).value for n in range(14,20)]==months
    assert main['X1'].comment and 'W2+X2+Y2' in main['AC2'].value
    assert '其他仓的物料' not in formulas.sheetnames
    assert main['AN2'].value=='未提交' and main['AQ2'].value is None
    formulas.close()
    cached=load_workbook(BytesIO(content),data_only=True)
    assert cached.active['A2'].value=='A-SELECT' and cached.active['X2'].value==10
    assert cached.active['Y2'].value==1 and cached.active['AC2'].value==23
    cached.close()
    empty=load_workbook(BytesIO(export_bytes(planner,vid,scope='filtered',q='NO_MATCH')))
    assert empty.active.max_row==1 and empty.active.column_dimensions['X'].width==31
    empty.close()
    # Simulate a historical install that retained data but not its uploaded workbook.
    (FILES/(original_id+'.xlsx')).unlink()
    fallback=load_workbook(BytesIO(export_bytes(planner,vid)),data_only=True)
    assert fallback.active.max_row==3 and fallback.active['N1'].value==months[0]
    assert '原工作表缺失' in dict(fallback['版本与来源'].values)['审核主表版式']
    fallback.close()


def test_quantity_only_export_preserves_its_columns_and_current_decision(clients):
    planner,*_=clients
    batch=post(planner,'/batches',{'warehouse':'UK_MAIN','title':'简表导出','period':'2026-11'}).json()
    vid=batch['current_id']
    book=Workbook()
    source=book.active
    source.title='本期补货'
    source.append(['空运计划','物料号','海运计划','不导出的外部列'])
    source.append([4,'0003',0,'其他数据'])
    source.column_dimensions['A'].width=27
    imported=upload(planner,'plan',workbook_bytes(book),'补货.xlsx')
    before=planner.get(P+'/versions/'+vid).json()
    saved=post(planner,'/imports/'+imported['id']+'/commit',{'version_id':vid,'revision':before['revision'],'mode':'replace'})
    assert saved.status_code==200,saved.text
    result=load_workbook(BytesIO(export_bytes(planner,vid)),data_only=True)
    sheet=result.active
    assert sheet.title==source.title and sheet.column_dimensions['A'].width==27
    assert [v.value for v in sheet[1]]==['空运计划','物料号','海运计划','审批建议','复审决定','复审备注']
    assert [v.value for v in sheet[2]][:3]==[4,'0003',0] and sheet['E2'].value=='未提交'
    result.close()
