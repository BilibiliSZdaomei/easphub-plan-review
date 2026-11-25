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
    except (ValueError,TypeError,OverflowError):pass
    if not strict:return {'kind':'legacy','start':None,'end':None,'label':str(value or '')}
    raise HTTPException(422,'计划周期请选择有效月份或ISO周，例如2026-09或2026-W37')


def previous_sales_months(period):
    """Six closed calendar months, anchored to the first day of the plan period."""
    start=date.fromisoformat(period_info(period)['start']).replace(day=1)
    months=[]
    try:
        for _ in range(6):
            start=(start-timedelta(days=1)).replace(day=1)
            months.append(start.isoformat()[:7])
    except OverflowError as exc:
        raise HTTPException(422,'计划周期过早，无法生成前六个月的销量表头') from exc
    return tuple(reversed(months))
