import re
from datetime import date,timedelta
from fastapi import HTTPException

def period_info(value,strict=True):
    try:
        if re.fullmatch(r'\d{4}-W\d{2}',value):
            year,week=int(value[:4]),int(value[-2:]);start=date.fromisocalendar(year,week,1);end=start+timedelta(days=6)
            return {'kind':'week','start':start.isoformat(),'end':end.isoformat(),'label':f'{year}年第{week:02d}周（{start:%m/%d}–{end:%m/%d}）'}
        if re.fullmatch(r'\d{4}-\d{2}',value):
            start=date.fromisoformat(value+'-01');next_month=date(start.year+(start.month==12),start.month%12+1,1)
            return {'kind':'month','start':start.isoformat(),'end':(next_month-timedelta(days=1)).isoformat(),'label':f'{start.year}年{start.month}月'}
    except (ValueError,TypeError):pass
    if not strict:return {'kind':'legacy','start':None,'end':None,'label':str(value or '')}
    raise HTTPException(422,'计划周期请选择有效月份或ISO周，例如2026-09或2026-W37')
