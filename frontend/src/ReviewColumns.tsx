import {tr, systemText} from './i18n'
import {useLayoutEffect, useRef, useState, type CSSProperties} from 'react'

type Column = {key:string; label:string; type:string}
type Widths = Record<string,number>
const defaults: Widths = {material_code:142, material_name:236, status:142, sea_plan_qty:146, air_plan_qty:146,
  decision:146, attention:176, reason:184, air_reason:184, advice:220, source_note:180}
const maximum = 740
function minimum(key:string) {
  return key==='sea_plan_qty' || key==='air_plan_qty' ? 116 : 76
}
function widthFor(column:Column, saved:Widths) {
  const fallback = defaults[column.key] ?? Math.max(112, column.label.length*15+60)
  const value = saved[column.key]
  return Number.isFinite(value) ? Math.max(minimum(column.key), Math.min(maximum,value)) : fallback
}
function readWidths(storageKey:string):Widths {
  try { const value = JSON.parse(localStorage.getItem(storageKey)||'{}'); return value && typeof value==='object' ? value : {} }
  catch { return {} }
}
function updatePinning(table:HTMLTableElement, check:number, code:number, name:number) {
  const available = table.parentElement?.clientWidth || 0
  table.dataset.pinCode = String(check+code <= available*0.55)
  table.dataset.pinName = String(check+code+name <= available*0.55)
  table.dataset.pinActions = String(available >= 760)
}

export function useReviewWidths(owner:string, view:string, columns:Column[], check:number, actions:number) {
  const storageKey = 'plan-review-widths-v1:'+owner+':'+view
  const [profile,setProfile] = useState(()=>({key:storageKey, widths:readWidths(storageKey)}))
  const saved = profile.key===storageKey ? profile.widths : readWidths(storageKey)
  const tableRef = useRef<HTMLTableElement>(null)
  const widths:Widths = Object.fromEntries(columns.map(c=>[c.key,widthFor(c,saved)]))
  const total = check + actions + Object.values(widths).reduce((a,b)=>a+b,0)
  const pinCode = widths.material_code || 0, pinName = widths.material_name || 0
  useLayoutEffect(()=>{
    const table=tableRef.current, parent=table?.parentElement
    if(!table || !parent) return
    const sync=()=>updatePinning(table,check,pinCode,pinName)
    sync()
    const observer=new ResizeObserver(sync)
    observer.observe(parent)
    return ()=>observer.disconnect()
  },[check,pinCode,pinName])
  const style = {width:total,'--check-width':check+'px', ...Object.fromEntries(
    Object.entries(widths).map(([key,value])=>['--width-'+key,value+'px'])
  )} as CSSProperties
  function preview(key:string,width:number) {
    const table=tableRef.current
    if(!table) return
    table.style.setProperty('--width-'+key,width+'px')
    table.style.width=(total-widths[key]+width)+'px'
    updatePinning(table,check,key==='material_code'?width:pinCode,key==='material_name'?width:pinName)
  }
  function save(widths:Widths) {
    setProfile({key:storageKey,widths})
    try {localStorage.setItem(storageKey,JSON.stringify(widths))} catch { /* Local storage is optional. */ }
  }
  function resize(key:string,width:number) {
    const column=columns.find(c=>c.key===key)
    if(!column) return
    const next={...saved,[key]:width}
    if(width===widthFor(column,{})) delete next[key]
    save(next)
  }
  return {tableRef, style, widths, preview, resize, reset:()=>save({}), customized:Object.keys(saved).length>0}
}

type ResizeProps = {column:Column; width:number; preview:(key:string,width:number)=>void; resize:(key:string,width:number)=>void}
export function ResizeHandle({column,width,preview,resize}:ResizeProps) {
  const drag=useRef<{x:number;start:number;next:number}|null>(null)
  const key=column.key
  function clamp(value:number) {return Math.max(minimum(key),Math.min(maximum,Math.round(value)))}
  return <span className="review-column-grip" role="separator" aria-orientation="vertical" tabIndex={0}
    aria-label={tr(`调整${column.label}列宽`,`Resize ${column.label} column`)} aria-valuemin={minimum(key)} aria-valuemax={maximum} aria-valuenow={width}
    title={systemText("拖动调整列宽，双击恢复默认")} onDoubleClick={()=>resize(key,widthFor(column,{}))}
    onKeyDown={e=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) return
      e.preventDefault()
      resize(key,e.key==='Home'?widthFor(column,{}):e.key==='End'?maximum:clamp(width+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?32:8)))
    }}
    onPointerDown={e=>{
      if(e.button!==0 || !e.isPrimary) return
      e.preventDefault()
      e.currentTarget.setPointerCapture(e.pointerId)
      drag.current={x:e.clientX,start:width,next:width}
    }}
    onPointerMove={e=>{
      const d=drag.current
      if(!d) return
      d.next=clamp(d.start+e.clientX-d.x)
      preview(key,d.next)
    }}
    onPointerUp={e=>{
      if(!drag.current) return
      const {start,next}=drag.current
      drag.current=null
      e.currentTarget.releasePointerCapture(e.pointerId)
      if(start!==next) resize(key,next)
    }}
    onLostPointerCapture={()=>{if(drag.current) {preview(key,width);drag.current=null}}}
  />
}
