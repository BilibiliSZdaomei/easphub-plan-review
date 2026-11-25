import {tr, systemText} from './i18n'
import {planMessage,tableDisplay} from './planMessages'
import {useState} from 'react'
import {ArrowUp,ArrowDown,ArrowUpDown,Filter,SlidersHorizontal,ExternalLink} from 'lucide-react'
import {Badge} from './ui'
import ColumnFilterMenu from './ColumnFilterMenu'
import WindowedRows from './WindowedRows'
import {fmt} from './api'
import type {ReactNode} from 'react'
import {RotateCcw} from 'lucide-react'
import {useReviewWidths,ResizeHandle} from './ReviewColumns'
import {materialMarks,PlanQuantity} from './ReviewMaterial'

const IDENTITY_COLUMNS = ['material_code', 'material_name']
export const DEFAULT_COLUMNS = [
 ...IDENTITY_COLUMNS, 'status', 'sea_plan_qty', 'air_plan_qty', 'future_qty', 'attention', 'decision',
]
const INVENTORY_COLUMNS = [
 ...IDENTITY_COLUMNS, 'on_hand_qty', 'in_transit_qty', 'on_order_qty', 'net_supply_before_plan',
 'sea_plan_qty', 'air_plan_qty', 'future_qty', 'lower', 'upper', 'm', 'vehicle_parc', 'on_hand_months', 'future_days', 'delay_replenishment', 'turnover_warning',
]
const ALL_COLUMNS = [
 ...IDENTITY_COLUMNS, 'material_abc', 'net_supply_before_plan', 'sea_plan_qty', 'air_plan_qty',
 'future_qty', 'lower', 'upper', 'status', 'attention', 'm', 'pipeline_days', 'future_days', 'is_key_model',
 'avg_sales_3m', 'avg_sales_6m', 'fleet_qty', 'future_fleet_qty', 'turnover_warning', 'vehicle_model', 'vehicle_parc', 'on_hand_months', 'delay_replenishment', 'advice', 'source_note', 'on_hand_qty', 'in_transit_qty', 'on_order_qty',
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
  {key:'quick', label:systemText("快速审核"), columns:DEFAULT_COLUMNS.filter(key=>availableColumns.includes(key))},
  {key:'inventory', label:systemText("库存依据"), columns:INVENTORY_COLUMNS.filter(key=>availableColumns.includes(key))},
  {key:'all', label:systemText("完整数据"), columns:withMaterialColumns(availableColumns)},
 ]
 const active = presets.find(p=>p.columns.length===columns.length && p.columns.every((key,i)=>key===columns[i]))
 return <div className="table-view-controls">
  <select aria-label={systemText("表格视图")} value={active?.key || 'custom'} disabled={disabled} onChange={e=>{
   const next = presets.find(p=>p.key===e.target.value)
   if (next) onChange([...next.columns])
  }}>
   {presets.map(p=><option key={p.key} value={p.key}>{p.label}</option>)}
   {!active && <option value="custom">{systemText("自定义视图")}</option>}
  </select>
  <select aria-label={systemText("表格密度")} value={density} disabled={disabled} onChange={e=>onDensityChange(e.target.value as Density)}>
   <option value="compact">{systemText("紧凑行距")}</option><option value="standard">{systemText("标准行距")}</option>
  </select>
 </div>
}

export type TableState={filters:Record<string,any>;sortKey:string;sortDirection:string}
export const EMPTY_TABLE:TableState={filters:{},sortKey:'',sortDirection:'asc'}
type Column = {key:string; label:string; type:string}
export function ColumnPicker({columns,visible,onChange,disabled}:{columns:Column[];visible:string[];onChange:(v:string[])=>void;disabled?:boolean}){
 return <details className="column-settings">
  <summary><SlidersHorizontal size={14}/>{systemText("显示列")}</summary>
  <div className="dropdown column-picker">
   {columns.filter(c=>!IDENTITY_COLUMNS.includes(c.key)).map(c=><label className="check-row" key={c.key}>
    <input type="checkbox" disabled={disabled} checked={visible.includes(c.key)} onChange={e=>onChange(e.target.checked?[...visible,c.key]:visible.filter(k=>k!==c.key))}/>{systemText(c.label)}
   </label>)}
   <button className="text-button" disabled={disabled} onClick={()=>onChange(DEFAULT_COLUMNS.filter(key=>columns.some(c=>c.key===key)))}>{systemText("恢复快速审核视图")}</button>
  </div>
 </details>
}

export default function ReviewTable({ver,visible,layoutOwner,quickActions,state,onState,editable,reviewing,dirty,busy=false,selected,setSelected,edits,setNumber,onDetail}:{ver:any;visible:string[];layoutOwner:string;quickActions?:(row:any)=>ReactNode;state:TableState;onState:(s:TableState)=>void;editable:boolean;reviewing:boolean;dirty:boolean;busy?:boolean;selected:Set<string>;setSelected:(fn:(s:Set<string>)=>Set<string>)=>void;edits:any;setNumber:(id:string,key:string,value:string)=>void;onDetail:(r:any)=>void}){
 const [filterCol,setFilterCol]=useState<(Column & {anchor:HTMLButtonElement})|null>(null)
 const catalog:Column[] = (ver.columns || []).map((c:Column)=>({...c,label:systemText(c.label)}))
 const orderedKeys = withMaterialColumns(visible)
 const columns = orderedKeys.map(key=>catalog.find(c=>c.key===key)).filter((c):c is Column=>!!c)
 const view = columns.map(c=>c.key).join(',')
 const checkWidth = editable || reviewing ? 38 : 0
 const actionWidth = reviewing && quickActions ? 172 : 78
 const layout = useReviewWidths(layoutOwner,view,columns,checkWidth,actionWidth)
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
 function cell(row:any,col:any,marks:ReturnType<typeof materialMarks>){const i=row.input,v=row.table_values?.[col.key],d=row.decision
  if(col.key==='material_code')return <span className="material-code-value" title={i.material_code}>{i.material_code}</span>
  if(col.key==='material_name')return <><button className="material-link" title={i.material_name||''} disabled={locked} onClick={()=>onDetail(row)}>{i.material_name||'—'}</button><small className="material-meta"><span>{i.material_abc||systemText("未分类")}</span>{marks.special.map(label=><em key={label} className="material-mark special" title={systemText("特殊物料 · ")+label}>{label}</em>)}{marks.size&&<em className={'material-mark '+(marks.highlighted?'large':'neutral')} title={tableDisplay('size',marks.size)}>{tableDisplay('size',marks.size)}</em>}{editable&&row.return_requested&&<em className="exception-tag">{systemText("上版需修改")}</em>}{row.submission_override&&row.submission_override.mode!=='advisory'&&<em className="exception-tag">{systemText("带问题提交")}</em>}{d?.forced&&<em className="exception-tag">{systemText("例外终审")}</em>}</small></>
  if(editable&&['sea_plan_qty','air_plan_qty'].includes(col.key))return <PlanQuantity value={edits[row.id]?.[col.key]??i[col.key]??''}
   step={i.quantity_step||1} label={i.material_code+' '+col.label} disabled={busy}
   edited={edits[row.id]?.[col.key]!==undefined} onChange={value=>setNumber(row.id,col.key,value)}/>
  if(['on_hand_months','pipeline_days','future_days'].includes(col.key)&&row.result.m==='0'&&'advice' in row.result)return <span className="muted">{systemText("无销量")}</span>
  if(col.key==='status'){const r=row.result;return <><Badge value={['ERROR','PENDING'].includes(r.data_status)?r.data_status:r.review_mode==='AUTO'?r.quantity_status:r.review_mode}/>{r.turnover_warning&&<small className="text-coral">{planMessage(r.turnover_warning)}</small>}{r.delay_replenishment&&<small className="text-coral">{systemText("建议延迟补货")}</small>}</>}
  if(col.key==='decision'){
   const reason=d?d.reason:row.return_requested?row.return_reason:''
   return <>{d?<Badge value={d.status} label={systemText(v)}/>:v==="需修改"?<Badge value="RETURNED" label={systemText(v)}/>:<span className="muted">{systemText(v)}</span>}
    {reason&&<small className="decision-reason" title={reason}>{reason}</small>}</>
  }
  if(col.key==='replacement_rate')return v==null?'—':fmt(Number(v)*100)+'%'
  if(col.type==='number')return <span className="mono">{fmt(v)}</span>
  const display=tableDisplay(col.key,v)
  return <span className={['reason','air_reason','attention'].includes(col.key)?'clipped-cell':''} title={display}>{display||'—'}</span>
 }
 function columnClass(c:Column){return c.key==='material_code'?'material-code-col':c.key==='material_name'?'material-col':c.key==='sea_plan_qty'?'numeric-col sea-col':c.key==='air_plan_qty'?'numeric-col air-col':c.type==='number'?'numeric-col':undefined}
 const count=Object.keys(state.filters).length
 return <>
  {(count>0||state.sortKey)&&<div className="table-query-state">
   <span>{count>0?tr(`${count} 列筛选 · `,`${count} active column filters · `):''}{ver.total} / {ver.summary.total} {systemText("行")}{state.sortKey?' · '+(catalog.find(c=>c.key===state.sortKey)?.label||'')+' '+(state.sortDirection==='asc'?systemText("升序"):systemText("降序")):''}</span>
   <button disabled={locked} className="text-button" onClick={()=>onState(EMPTY_TABLE)}>{systemText("清除筛选与排序")}</button>
  </div>}
  <div className="table-scroll plan-scroll">
   <table className="plan-table expanded-table layout-table" ref={layout.tableRef} style={layout.style} data-review-actions={Boolean(reviewing&&quickActions)} aria-label={systemText("计划物料")}>
    <colgroup>
     {checkWidth>0&&<col style={{width:checkWidth}}/>}
     {columns.map(c=><col key={c.key} style={{width:'var(--width-'+c.key+')'}}/>)}
     <col/>
    </colgroup>
    <thead><tr>
     {(editable||reviewing)&&<th className="check-cell"><input type="checkbox" aria-label={systemText("选择当前页")} disabled={busy||!ver.items.length} checked={pageSelected} ref={el=>{if(el)el.indeterminate=pageMixed}} onChange={e=>selectPage(e.target.checked)}/></th>}
     {columns.map(c=><th key={c.key} scope="col" className={columnClass(c)} aria-sort={state.sortKey===c.key?state.sortDirection==='asc'?'ascending':'descending':'none'}>
      <div className="table-column-head">
       <button disabled={locked} onClick={()=>sort(c.key)} title={c.label+systemText(" · 切换排序")} aria-label={systemText("排序 ")+c.label}><span>{systemText(c.label)}</span>
        {state.sortKey===c.key?state.sortDirection==='asc'?<ArrowUp size={12}/>:<ArrowDown size={12}/>:<ArrowUpDown size={11}/>}
       </button>
       <button className={state.filters[c.key]?'filter-active':''} disabled={locked} data-usage-target="filter" aria-haspopup="dialog" aria-expanded={filterCol?.key===c.key} onClick={e=>setFilterCol(filterCol?.key===c.key?null:{...c,anchor:e.currentTarget})} aria-label={systemText("筛选 ")+c.label} title={systemText("筛选 ")+c.label}><Filter size={12}/></button>
      </div>
      <ResizeHandle column={c} width={layout.widths[c.key]} preview={layout.preview} resize={layout.resize}/>
     </th>)}
     <th scope="col" aria-label={systemText("操作")} className="review-actions"><div className="layout-action-head">{systemText("操作")}{layout.customized&&<button type="button" title={systemText("恢复当前视图默认列宽")} aria-label={systemText("恢复当前视图默认列宽")} onClick={layout.reset}><RotateCcw size={13}/></button>}</div></th>
    </tr></thead>
    <WindowedRows rows={ver.items} columns={columns.length+(editable||reviewing?2:1)}>{(r:any)=>{
     const marks=materialMarks(r)
     return <tr key={r.id} className={[selected.has(r.id)&&'selected',marks.special.length>0&&'special-row',marks.highlighted&&'large-row'].filter(Boolean).join(' ')}>
     {(editable||reviewing)&&<td className="check-cell"><input type="checkbox" aria-label={systemText("选择 ")+r.input.material_code} disabled={busy} checked={selected.has(r.id)} onChange={e=>{
      const checked=e.target.checked
      setSelected(current=>{const next=new Set(current);if(checked)next.add(r.id);else next.delete(r.id);return next})
     }}/></td>}
     {columns.map(c=><td key={c.key} className={columnClass(c)}>{cell(r,c,marks)}</td>)}
     <td className="review-actions"><div>{reviewing&&quickActions?.(r)}<button className="text-button" disabled={locked} onClick={()=>onDetail(r)} aria-label={systemText("查看 ")+r.input.material_code}>{systemText("查看")}<ExternalLink size={12}/></button></div></td>
    </tr>}}</WindowedRows>
   </table>
  </div>
 {!ver.items.length&&<div className="filtered-empty">{ver.summary.total?systemText("没有符合当前筛选条件的物料。"):systemText("暂无计划物料")}</div>}
 {filterCol&&<ColumnFilterMenu key={filterCol.key} anchor={filterCol.anchor} column={catalog.find(c=>c.key===filterCol.key)||filterCol} rule={state.filters[filterCol.key]||{}} options={ver.column_options?.[filterCol.key]||[]} onClose={()=>setFilterCol(null)} onApply={rule=>{const filters={...state.filters};if(rule)filters[filterCol.key]=rule;else delete filters[filterCol.key];onState({...state,filters});setFilterCol(null)}}/>}</>
}
