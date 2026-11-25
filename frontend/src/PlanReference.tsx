type Field = [string, string, ('text'|'number'|'flag'|'rate')?]
type Edits = Record<string, string | string[]>
const material: Field[] = [
 ['material_name','备件描述','text'],['vehicle_model','车型','text'],['material_type','物料类型','text'],
 ['local_abc','本地 ABC','text'],['material_abc','物料分类 ABC','text'],['is_key_model','重点车型','flag'],
 ['fleet_qty','装车量'],['vehicle_parc','备件保有量'],['future_fleet_qty','未来装车量'],
]
const inventory: Field[] = [['on_hand_qty','在库数量'],['net_supply_before_plan','补货前净额']]
const components: Field[] = [['in_transit_qty','在途数量'],['on_order_qty','在订数量'],['demand_deduction_qty','需求抵扣数量']]
const targets: Field[] = [['replacement_rate','稳态更换率','rate'],['replacement_target','更换率目标库存'],['sales_target','销量目标库存']]
const optional: Field[] = [['large_value_flag','高单价大体积识别','text'],['current_sales','当月销量'],['shortage_qty','缺货数量']]
const defaultMonths = ['第1月销量','第2月销量','第3月销量','第4月销量','第5月销量','第6月销量']
export const referenceLabels:Record<string,string> = Object.fromEntries([
 ...material,...inventory,...components,...targets,...optional,['monthly_sales','近六个月销量'],
 ['avg_sales_3m','三个月月均销量'],['avg_sales_6m','六个月月均销量'],
].map(([key,label])=>[key,label]))

export default function PlanReference({input,changes,onChange,readOnly=false,basis,componentNet=false,omitDescription=false}:{
 input:Record<string,any>;changes:Edits;onChange:(next:Edits)=>void;readOnly?:boolean;basis?:{values:Record<string,unknown>;targets:Record<string,{months:string;fallback?:boolean}>};componentNet?:boolean;omitDescription?:boolean
}){
 const labels:string[]=input.month_labels||Object.keys(input.monthly_sales||{})
 const monthKeys=labels.length===6?labels:defaultMonths
 const original=monthKeys.map(key=>String(input.monthly_sales?.[key]??''))
 const months=Array.isArray(changes.monthly_sales)?changes.monthly_sales:original
 function change(key:string,value:string|string[],same:boolean){
  const next={...changes}
  if(same)delete next[key]
  else next[key]=value
  onChange(next)
 }
 function fields(title:string,group:Field[]){
  return <fieldset><legend>{title}</legend><div className="form-grid">{group.map(([key,label,type='number'])=>{
   const base=String(input[key]??'')
   const formula=basis?.targets[key]
   const managed=!!basis && Object.prototype.hasOwnProperty.call(basis.values,key)
   const value=managed?base:String(changes[key]??base)
   const origin=formula?(formula.fallback?'来源目标':'按 '+formula.months+' 个月计算'):managed?'仓库主数据':''
   const locked=managed||readOnly||(componentNet&&key==='net_supply_before_plan')
   return <label key={key}>{label}{origin&&<small>{origin}</small>}{locked?<output>{type==='flag'?value==='true'?'是':value==='false'?'否':'—':type==='rate'&&value!==''&&Number.isFinite(Number(value))?new Intl.NumberFormat('zh-CN',{style:'percent',maximumFractionDigits:9}).format(Number(value)):value||'—'}</output>
    :type==='flag'?<select value={value} onChange={e=>change(key,e.target.value,e.target.value===base)}><option value="">未提供</option><option value="true">是</option><option value="false">否</option></select>
    :<input type={type==='number'?'number':'text'} step={type==='number'?'any':undefined} maxLength={300}
      placeholder={type==='rate'?'例如 2%':undefined} value={value} onChange={e=>change(key,e.target.value,e.target.value===base)}/>}</label>
  })}</div></fieldset>
 }
 return <div className="plan-reference">
  {fields('物料与车辆',omitDescription?material.slice(1):material)}
  {fields('库存与供给',componentNet?[inventory[0],...components,inventory[1]]:inventory)}
  <fieldset><legend>近六个月销量 <small>从早到晚</small></legend><div className="reference-months">{monthKeys.map((key,n)=>{
   const label=key.match(/^\d{4}-\d{2}/)?.[0]||key.replace('（最早）','').replace('（最近）','')
   return <label key={key}>{label}{readOnly?<output>{months[n]||'—'}</output>:<input type="number" min="0" step="any" value={months[n]} onChange={e=>{
    const next=months.map((v,pos)=>pos===n?e.target.value:v)
    change('monthly_sales',next,next.every((v,pos)=>v===original[pos]))
   }}/>}</label>
  })}</div></fieldset>
  {fields('目标库存',targets)}
  <details className="evidence-details"><summary>其他来源字段</summary>{fields('辅助信息',optional)}</details>
 </div>
}
