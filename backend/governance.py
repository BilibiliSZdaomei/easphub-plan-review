"""Apply the warehouse's published master data and target-stock policy to plan inputs."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext

from .numbers import number, serial

MASTER_FIELDS = {
    'material_name':'备件描述', 'material_type':'物料类型', 'vehicle_model':'车型',
    'local_abc':'本地ABC', 'material_abc':'物料分类ABC', 'is_key_model':'重点车型',
    'large_value_flag':'高单价大体积识别', 'replacement_rate':'更换率',
    'replacement_target':'更换率目标库存', 'sales_target':'销量目标库存',
    'replacement_months':'更换率储备月数', 'sales_months':'销量储备月数', 'use_fixed_targets':'沿用来源目标',
}
MONTH_KEYS = ('replacement_months', 'sales_months')
TARGETS = (('replacement_target','replacement_months'), ('sales_target','sales_months'))
REF_FIELDS = set(MASTER_FIELDS) - {*MONTH_KEYS, 'use_fixed_targets'}
ROUNDING = {'up':ROUND_CEILING, 'nearest':ROUND_HALF_UP, 'down':ROUND_FLOOR, 'raw':None}
WINDOWS = ('3m','6m','max')
NUMERIC_FIELDS = {'replacement_rate','replacement_target','sales_target',*MONTH_KEYS}
BOOL_FIELDS = {'is_key_model','use_fixed_targets'}


def master_value(key, raw):
    if key not in MASTER_FIELDS:
        raise ValueError('未知主数据字段')
    if raw is None or (isinstance(raw,str) and not raw.strip()):
        return None
    if key in NUMERIC_FIELDS:
        if len(str(raw))>80: raise ValueError(MASTER_FIELDS[key]+'数值过长')
        n = number(raw)
        if n is None or n.as_tuple().exponent < -50 or n < 0 or (key == 'replacement_rate' and n > 1) or (key in MONTH_KEYS and n <= 0):
            raise ValueError(MASTER_FIELDS[key]+'数值无效')
        return serial(n)
    if key in BOOL_FIELDS:
        value=str(raw).strip().casefold()
        if value in ('是','true','1','y','yes'): return True
        if value in ('否','false','0','n','no'): return False
        raise ValueError(MASTER_FIELDS[key]+'请填是或否')
    if not isinstance(raw,(str,int,float)) or isinstance(raw,bool) or len(str(raw).strip())>300:
        raise ValueError(MASTER_FIELDS[key]+'格式无效')
    return str(raw).strip()


def check_governance(package):
    master=package.get('master_data'); policy=package.get('target_policy')
    if master is None and policy is None: return []
    if package.get('model')!='V3': return ['物料主数据和目标计算需要 V3 标准']
    try:
        if master is not None:
            if not isinstance(master,dict) or set(master)!={'warehouse','items'} or not isinstance(master.get('warehouse'),str) or not master['warehouse'].strip():
                raise ValueError('请指定主数据所属仓库')
            items=master['items']
            if not isinstance(items,dict) or len(items)>10000:
                raise ValueError('主数据每仓最多 10000 种物料')
            for code, record in items.items():
                if not isinstance(code,str) or not 0<len(code)<=120 or code!=code.strip() or not isinstance(record,dict) or not record:
                    raise ValueError('物料号或主数据记录无效')
                try:
                    for key, value in record.items():
                        if master_value(key,value) is None: raise ValueError('请移除空字段')
                except ValueError as exc:
                    raise ValueError(f'物料 {code} · {exc}') from exc
        if policy is not None:
            if not isinstance(policy,dict) or set(policy)!={'window','rounding','classes'}:
                raise ValueError('请填写目标库存计算口径')
            if policy['window'] not in WINDOWS or policy['rounding'] not in tuple(ROUNDING):
                raise ValueError('请选择月均销量窗口和取整方式')
            groups=policy['classes']
            if not isinstance(groups,dict) or len(groups)>200: raise ValueError('目标库存分类格式无效')
            for group, months in groups.items():
                if not isinstance(group,str) or not 0<len(group)<=30 or group!=group.strip().upper() or not isinstance(months,dict) or not months or set(months)-set(MONTH_KEYS):
                    raise ValueError('请填写唯一的物料分类及储备月数')
                for key, value in months.items():
                    if master_value(key,value) is None: raise ValueError('储备月数不能为空')
    except (ValueError,TypeError) as exc: return [str(exc)]
    return []


def valid_amount(value):
    try: amount=number(value)
    except ValueError: return None
    return amount if amount is not None and amount >= 0 else None


def apply_governance(item, package):
    master=package.get('master_data') or {}
    record=master.get('items',{}).get(item.get('material_code'),{})
    policy=package.get('target_policy')
    if not record and not policy: return item, None
    values={key:master_value(key,v) for key,v in record.items() if key in REF_FIELDS}
    effective={**item,**values}
    details={}
    if policy and not master_value('use_fixed_targets',record.get('use_fixed_targets')):
        categories=policy['classes']
        group=str(effective.get('material_abc') or '').upper()
        periods={**categories.get('*',{}),**categories.get(group,{}),
                 **{k:record[k] for k in MONTH_KEYS if k in record}}
        for target,key in TARGETS:
            months=valid_amount(periods.get(key))
            if months is None: continue
            if target=='replacement_target':
                rate=valid_amount(values.get('replacement_rate'))
                fleet=valid_amount(effective.get('fleet_qty'))
                operands=[rate,fleet]
            else:
                window=policy['window']
                avgs=[valid_amount(effective.get('avg_sales_'+w)) for w in (('3m','6m') if window=='max' else (window,))]
                operands=[max(avgs)] if None not in avgs else [None]
            detail={'months':serial(months),'rounding':policy['rounding']}
            if target=='sales_target':detail['window']=policy['window']
            if None in operands:
                detail['fallback']=True
            else:
                with localcontext() as ctx:
                    ctx.prec=50
                    v=months
                    for operand in operands: v*=operand
                    rounding=ROUNDING[policy['rounding']]
                    if rounding is not None: v=v.to_integral_value(rounding=rounding)
                values[target]=serial(v)
                effective[target]=values[target]
            details[target]=detail
    if not values and not details: return item, None
    return effective, {'values':values,'master_fields':sorted(set(record)&REF_FIELDS),'targets':details,'source_targets':{k:master_value(k,record[k]) for k,_ in TARGETS if k in record}}


def effective_input(row):
    values=(row['result'].get('master_basis') or {}).get('values')
    return {**row['input'],**values} if values else row['input']
