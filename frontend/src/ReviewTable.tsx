import {useState} from 'react'
import {ArrowUp,ArrowDown,ArrowUpDown,Filter,SlidersHorizontal,ExternalLink} from 'lucide-react'
import {Badge,Modal} from './ui'
import {fmt} from './api'

const IDENTITY_COLUMNS = ['material_code', 'material_name']
export const DEFAULT_COLUMNS = [
 ...IDENTITY_COLUMNS, 'status', 'sea_plan_qty', 'air_plan_qty', 'future_qty', 'attention', 'decision',
]
const INVENTORY_COLUMNS = [
 ...IDENTITY_COLUMNS, 'on_hand_qty', 'in_transit_qty', 'on_order_qty', 'net_supply_before_plan',
 'sea_plan_qty', 'air_plan_qty', 'future_qty', 'lower', 'upper', 'm', 'vehicle_parc', 'on_hand_months', 'future_days', 'delay_replenishment',
]
const ALL_COLUMNS = [
 ...IDENTITY_COLUMNS, 'material_abc', 'net_supply_before_plan', 'sea_plan_qty', 'air_plan_qty',
 'future_qty', 'lower', 'upper', 'status', 'attention', 'm', 'pipeline_days', 'future_days', 'is_key_model',
 'avg_sales_3m', 'avg_sales_6m', 'fleet_qty', 'vehicle_model', 'vehicle_parc', 'on_hand_months', 'delay_replenishment', 'advice', 'source_note', 'on_hand_qty', 'in_transit_qty', 'on_order_qty',
 'replacement_rate', 'replacement_target', 'sales_target', 'decision', 'reason', 'air_reason', 'override',
]

export function withMaterialColumns(columns:unknown):string[] {
 const saved=Array.isArray(columns)?columns.filter((key):key is string=>typeof key==='string'):DEFAULT_COLUMNS
 return [...new Set([...IDENTITY_COLUMNS,...saved])]
}

type Density = 'compact' | 'standard'
type ViewControlsProps = {
 columns: string[]
 onChange: (columns: string[]) => void
 density: Density
 onDensityChange: (density: Density) => void
 availableColumns?: string[]
 disabled?: boolean
}

export function TableViewControls({columns, onChange, density, onDensityChange, availableColumns = ALL_COLUMNS, disabled}: ViewControlsProps) {
 const presets = [
  {key:'quick', label:'快速审核', columns:DEFAULT_COLUMNS.filter(key=>availableColumns.includes(key))},
  {key:'inventory', label:'库存依据', columns:INVENTORY_COLUMNS.filter(key=>availableColumns.includes(key))},
  {key:'all', label:'完整数据', columns:withMaterialColumns(availableColumns)},
 ]
 const active = presets.find(p=>p.columns.length===columns.length && p.columns.every((key,i)=>key===columns[i]))
 return <div className="table-view-controls">
  <select aria-label="表格视图" value={active?.key || 'custom'} disabled={disabled} onChange={e=>{
   const next = presets.find(p=>p.key===e.target.value)
   if (next) onChange([...next.columns])
  }}>
   {presets.map(p=><option key={p.key} value={p.key}>{p.label}</option>)}
   {!active && <option value="custom">自定义视图</option>}
  </select>
  <select aria-label="表格密度" value={density} disabled={disabled} onChange={e=>onDensityChange(e.target.value as Density)}>
   <option value="compact">紧凑行距</option><option value="standard">标准行距</option>
  </select>
 </div>
}

export type TableState={filters:Record<string,any>;sortKey:string;sortDirection:string}
export const EMPTY_TABLE:TableState={filters:{},sortKey:'',sortDirection:'asc'}
type Column = {key:string; label:string; type:string}
export function ColumnPicker({columns,visible,onChange,disabled}:{columns:Column[];visible:string[];onChange:(v:string[])=>void;disabled?:boolean}){
 return <details className="column-settings">
  <summary><SlidersHorizontal size={14}/>显示列</summary>
  <div className="dropdown column-picker">
   {columns.filter(c=>!IDENTITY_COLUMNS.includes(c.key)).map(c=><label className="check-row" key={c.key}>
    <input type="checkbox" disabled={disabled} checked={visible.includes(c.key)} onChange={e=>onChange(e.target.checked?[...visible,c.key]:visible.filter(k=>k!==c.key))}/>{c.label}
   </label>)}
   <button className="text-button" disabled={disabled} onClick={()=>onChange(DEFAULT_COLUMNS.filter(key=>columns.some(c=>c.key===key)))}>恢复快速审核视图</button>
  </div>
 </details>
}

export default function ReviewTable({ver,visible,state,onState,editable,reviewing,dirty,busy=false,selected,setSelected,edits,setNumber,onDetail}:{ver:any;visible:string[];state:TableState;onState:(s:TableState)=>void;editable:boolean;reviewing:boolean;dirty:boolean;busy?:boolean;selected:Set<string>;setSelected:(fn:(s:Set<string>)=>Set<string>)=>void;edits:any;setNumber:(id:string,key:string,value:string)=>void;onDetail:(r:any)=>void}){
 const [filterCol,setFilterCol]=useState<Column|null>(null)
 const catalog:Column[] = ver.columns || []
 const orderedKeys = withMaterialColumns(visible)
 const columns = orderedKeys.map(key=>catalog.find(c=>c.key===key)).filter((c):c is Column=>!!c)
 const locked = dirty || busy
 const pageSelected = ver.items.length > 0 && ver.items.every((r:any)=>selected.has(r.id))
 const pageMixed = !pageSelected && ver.items.some((r:any)=>selected.has(r.id))
 function selectPage(checked:boolean){
  setSelected(current=>{
   const next=new Set(current)
   for(const row of ver.items){if(checked)next.add(row.id);else next.delete(row.id)}
   return next
  })
 }
 function sort(key:string){onState({...state,sortKey:state.sortKey===key&&state.sortDirection==='desc'?'':key,sortDirection:state.sortKey===key&&state.sortDirection==='asc'?'desc':'asc'})}
 function cell(row:any,col:any){const i=row.input,v=row.table_values?.[col.key],d=row.decision
  if(col.key==='material_code')return <span className="material-code-value" title={i.material_code}>{i.material_code}</span>
  if(col.key==='material_name')return <><button className="material-link" disabled={locked} onClick={()=>onDetail(row)}>{i.material_name||'—'}</button><small>{i.material_abc||'未分类'}{editable&&row.return_requested&&<em className="exception-tag">指定修改</em>}{row.submission_override&&row.submission_override.mode!=='advisory'&&<em className="exception-tag">带问题提交</em>}{d?.forced&&<em className="exception-tag">例外终审</em>}</small></>
  if(editable&&['sea_plan_qty','air_plan_qty'].includes(col.key))return <input className={'quantity-input '+(edits[row.id]?.[col.key]!==undefined?'edited':'')} aria-label={i.material_code+' '+col.label} disabled={busy} type="number" min="0" step={i.quantity_step||1} value={edits[row.id]?.[col.key]??i[col.key]??''} onChange={e=>setNumber(row.id,col.key,e.target.value)}/>
  if(['on_hand_months','pipeline_days','future_days'].includes(col.key)&&row.result.m==='0'&&'advice' in row.result)return <span className="muted">无销量</span>
  if(col.key==='status'){const r=row.result;return <><Badge value={['ERROR','PENDING'].includes(r.data_status)?r.data_status:r.review_mode==='AUTO'?r.quantity_status:r.review_mode}/>{r.delay_replenishment&&<small className="text-coral">建议延迟补货</small>}</>}
  if(col.key==='decision'){
   const reason=row.return_requested?row.return_reason:d?.reason
   return <>{d?<Badge value={d.status} label={v}/>:row.return_requested?<Badge value="RETURNED" label="需修改"/>:<span className="muted">{v}</span>}
    {reason&&<small className="decision-reason" title={reason}>{reason}</small>}</>
  }
  if(col.key==='replacement_rate')return v==null?'—':fmt(Number(v)*100)+'%'
  if(col.type==='number')return <span className="mono">{fmt(v)}</span>
  return <span className={['reason','air_reason','attention'].includes(col.key)?'clipped-cell':''} title={String(v??'')}>{v==null||v===''?'—':String(v)}</span>
 }
 function columnClass(c:Column){return c.key==='material_code'?'material-code-col':c.key==='material_name'?'material-col':c.type==='number'?'numeric-col':undefined}
 const count=Object.keys(state.filters).length
 return <>
  {(count>0||state.sortKey)&&<div className="table-query-state">
   <span>{count>0?`${count} 列筛选 · `:''}{ver.total} / {ver.summary.total} 行{state.sortKey?' · '+(catalog.find(c=>c.key===state.sortKey)?.label||'')+' '+(state.sortDirection==='asc'?'升序':'降序'):''}</span>
   <button disabled={locked} className="text-button" onClick={()=>onState(EMPTY_TABLE)}>清除筛选与排序</button>
  </div>}
  <div className="table-scroll plan-scroll">
   <table className="plan-table expanded-table" aria-label="计划物料">
    <thead><tr>
     {(editable||reviewing)&&<th className="check-cell"><input type="checkbox" aria-label="选择当前页" disabled={busy||!ver.items.length} checked={pageSelected} ref={el=>{if(el)el.indeterminate=pageMixed}} onChange={e=>selectPage(e.target.checked)}/></th>}
     {columns.map(c=><th key={c.key} scope="col" className={columnClass(c)} aria-sort={state.sortKey===c.key?state.sortDirection==='asc'?'ascending':'descending':'none'}>
      <div className="table-column-head">
       <button disabled={locked} onClick={()=>sort(c.key)} title="切换排序" aria-label={'排序 '+c.label}>{c.label}
        {state.sortKey===c.key?state.sortDirection==='asc'?<ArrowUp size={12}/>:<ArrowDown size={12}/>:<ArrowUpDown size={11}/>}
       </button>
       <button className={state.filters[c.key]?'filter-active':''} disabled={locked} onClick={()=>setFilterCol(c)} aria-label={'筛选 '+c.label} title={'筛选 '+c.label}><Filter size={12}/></button>
      </div>
     </th>)}
     <th scope="col" aria-label="操作"/>
    </tr></thead>
    <tbody>{ver.items.map((r:any)=><tr key={r.id} className={selected.has(r.id)?'selected':''}>
     {(editable||reviewing)&&<td className="check-cell"><input type="checkbox" aria-label={'选择 '+r.input.material_code} disabled={busy} checked={selected.has(r.id)} onChange={e=>{
      const checked=e.target.checked
      setSelected(current=>{const next=new Set(current);if(checked)next.add(r.id);else next.delete(r.id);return next})
     }}/></td>}
     {columns.map(c=><td key={c.key} className={columnClass(c)}>{cell(r,c)}</td>)}
     <td><button className="text-button" disabled={locked} onClick={()=>onDetail(r)} aria-label={'查看 '+r.input.material_code}>查看<ExternalLink size={12}/></button></td>
    </tr>)}</tbody>
   </table>
  </div>
 {!ver.items.length&&<div className="filtered-empty">{ver.summary.total?'没有符合当前筛选条件的物料。':'暂无计划物料'}</div>}
 {filterCol&&<ColumnFilter column={filterCol} rule={state.filters[filterCol.key]||{}} options={ver.column_options?.[filterCol.key]||[]} onClose={()=>setFilterCol(null)} onApply={rule=>{const filters={...state.filters};if(rule)filters[filterCol.key]=rule;else delete filters[filterCol.key];onState({...state,filters});setFilterCol(null)}}/>}</>
}

function ColumnFilter({column,rule,options,onClose,onApply}:{column:any;rule:any;options:string[];onClose:()=>void;onApply:(v:any)=>void}){
 const [value,setValue]=useState<any>({...rule}),[error,setError]=useState('')
 function apply(){const result=Object.fromEntries(Object.entries(value).filter(([_,v])=>v!==''&&v!==undefined));if(result.min!==undefined&&result.max!==undefined&&Number(result.min)>Number(result.max)){setError('最小值不能大于最大值');return}onApply(Object.keys(result).length?result:null)}
 return <Modal title={'筛选 · '+column.label} onClose={onClose}><form className="modal-body" onSubmit={e=>{e.preventDefault();apply()}}>{error&&<p className="text-coral">{error}</p>}{column.type==='number'?<div className="form-grid"><label>最小值（含）<input type="number" step="any" value={value.min??''} onChange={e=>setValue({...value,min:e.target.value})}/></label><label>最大值（含）<input type="number" step="any" value={value.max??''} onChange={e=>setValue({...value,max:e.target.value})}/></label></div>:column.type==='enum'?<><div className="filter-options-actions"><button type="button" className="text-button" onClick={()=>setValue({...value,values:undefined})}>全选</button><button type="button" className="text-button" onClick={()=>setValue({...value,values:[]})}>全不选</button></div><div className="filter-option-list">{options.map(o=><label className="check-row" key={o}><input type="checkbox" checked={(value.values||options).includes(o)} onChange={e=>{const values=value.values||options;setValue({...value,values:e.target.checked?[...values,o]:values.filter((v:string)=>v!==o)})}}/>{o||'空值'}</label>)}</div></>:<label>包含文字<input value={value.contains||''} onChange={e=>setValue({...value,contains:e.target.value})} maxLength={200}/></label>}
 {column.key==='replacement_rate'&&<p className="muted">更换率筛选使用小数，例如0.0015代表0.15%。</p>}
 <label>空值<select value={value.blank||''} onChange={e=>setValue({...value,blank:e.target.value})}><option value="">包含空值</option><option value="exclude">排除空值</option><option value="only">只看空值</option></select></label><div className="modal-actions"><button type="button" className="secondary" onClick={()=>onApply(null)}>清除此列筛选</button><button className="primary">应用筛选</button></div></form></Modal>
}
