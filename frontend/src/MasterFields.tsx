import {systemText, tr} from './i18n'
import {useEffect, useRef, useState, type FormEvent} from 'react'
import {api, BASE} from './api'
import {Modal, Notice} from './ui'

type MasterRow = Record<string,string|boolean>
type Items = Record<string,MasterRow>
type Months = {replacement_months?:string; sales_months?:string}
type Policy = {window:string; rounding:string; classes:Record<string,Months>}
export type GovernanceConfig = {master_data?:{warehouse:string;items:Items};target_policy?:Policy}
const fields:Record<string,string> = {
  material_name:'备件描述',material_type:'物料类型',vehicle_model:'车型',local_abc:'本地 ABC',material_abc:'物料分类 ABC',
  is_key_model:'重点车型',large_value_flag:'高单价大体积识别',replacement_rate:'稳态更换率',
  replacement_target:'来源目标 · 更换率',sales_target:'来源目标 · 销量',
  replacement_months:'更换率储备月数',sales_months:'销量储备月数',use_fixed_targets:'沿用来源目标',
}
const monthNames = [['replacement_months','更换率储备月数'],['sales_months','销量储备月数']] as const
const rates = (v:string|boolean|undefined) => v===undefined?'—':String(v).endsWith('%')?String(v):Number.isFinite(Number(v))?new Intl.NumberFormat(tr('zh-CN','en'),{style:'percent',maximumFractionDigits:9}).format(Number(v)):String(v)
const windows:Record<string,string>={'3m':'近三个月月均','6m':'近六个月月均',max:'两者较大值'}
const roundings:Record<string,string>={up:'向上取整',nearest:'四舍五入',down:'向下取整',raw:'保留小数'}

function EditMaterial({code,items,onClose,onSave}:{code:string;items:Items;onClose:()=>void;onSave:(code:string,row:MasterRow)=>void}){
  const [nextCode,setCode]=useState(code), [row,setRow]=useState<MasterRow>({...items[code]}), [error,setError]=useState('')
  function save(e:FormEvent){
    e.preventDefault();e.stopPropagation()
    const key=nextCode.trim()
    if(!code&&Object.hasOwn(items,key)){setError('物料号已存在，请从列表中编辑');return}
    const entry=Object.fromEntries(Object.entries(row).filter(([,v])=>String(v).trim()!==''))
    if(!Object.keys(entry).length){setError('请至少填写一项物料数据');return}
    const rate=entry.replacement_rate
    if(rate!==undefined){
      const raw=String(rate).trim(), amount=raw.endsWith('%')?Number(raw.slice(0,-1))/100:Number(raw)
      if(!Number.isFinite(amount)||amount<0||amount>1){setError('更换率可填 0 至 1 的小数或百分数');return}
    }
    onSave(key,entry)
  }
  return <Modal title={code?systemText("编辑物料主数据"):systemText("新增物料主数据")} onClose={onClose} wide><form onSubmit={save} className="modal-body">
    <div className="form-grid"><label>{systemText("物料号")}<input autoFocus disabled={!!code} required maxLength={120} value={nextCode} onChange={e=>setCode(e.target.value)}/></label>
    {Object.entries(fields).map(([field,label])=>{
      const value=String(row[field]??'')
      const set=(v:string|boolean)=>setRow(old=>({...old,[field]:v}))
      const numeric=field.endsWith('_target')||field.endsWith('_months')
      return <label key={field}>{systemText(label)}{field==='is_key_model'||field==='use_fixed_targets'?
        <select value={value} onChange={e=>set(e.target.value===''?'':e.target.value==='true')}><option value="">{systemText("未设置")}</option><option value="true">{systemText("是")}</option><option value="false">{systemText("否")}</option></select>:
        <input type={numeric?'number':'text'} min={field.endsWith('_months')?'0.000000001':'0'} step="any" maxLength={300}
          placeholder={field==='replacement_rate'?systemText("例如 0.15%"):undefined} value={value} onChange={e=>set(e.target.value)}/>}</label>
    })}</div>{error&&<Notice tone="error" message={error}/>}
    <div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>{systemText("取消")}</button><button className="primary">{systemText("应用到草稿")}</button></div>
  </form></Modal>
}

function ImportMaster({warehouse,items,onClose,onApply}:{warehouse:string;items:Items;onClose:()=>void;onApply:(rows:Items)=>void}){
  const [rows,setRows]=useState<Items|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const active=useRef(true)
  useEffect(()=>{active.current=true;return ()=>{active.current=false}},[])
  async function read(file?:File){
    setRows(null);setError('')
    if(!file)return
    setBusy(true)
    try{
      const body=new FormData();body.append('warehouse',warehouse);body.append('file',file)
      const result=await api<{items:Items}>('/rules/master-preview',body)
      if(active.current)setRows(result.items)
    }catch(e:any){if(active.current)setError(e.message)}finally{if(active.current)setBusy(false)}
  }
  const keys=Object.keys(rows||{}),updated=keys.filter(k=>Object.hasOwn(items,k)).length
  return <Modal title={systemText("导入物料主数据")} onClose={onClose}><div className="modal-body">
    <label>{systemText("V3 审核表或主数据模板")}<input type="file" disabled={busy} accept=".xlsx,.csv" onChange={e=>void read(e.target.files?.[0])}/></label>
    <a className="text-button" href={BASE+'/rules/master-template?lang='+tr('zh','en')}>{systemText("下载空白主数据模板")}</a>
    {busy&&<p role="status">{systemText("正在检查物料…")}</p>}{error&&<Notice tone="error" message={error}/>}
    {rows&&<p role="status">{tr(`新增 ${keys.length-updated} 项，更新 ${updated} 项。空白字段保留原值。`,`New: ${keys.length-updated}. Updated: ${updated}. Blank fields keep existing values.`)}</p>}
    <div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>{systemText("取消")}</button><button type="button" className="primary" disabled={!rows||busy} onClick={()=>rows&&onApply(rows)}>{systemText("应用到草稿")}</button></div>
  </div></Modal>
}

function EditClass({name,policy,onClose,onApply}:{name:string;policy:Policy;onClose:()=>void;onApply:(key:string,m:Months)=>void}){
  const [key,setKey]=useState(name),[months,setMonths]=useState<Months>({...policy.classes[name]}),[error,setError]=useState('')
  function save(e:FormEvent){
    e.preventDefault();e.stopPropagation()
    const normalized=key.trim().toUpperCase()
    if(!normalized||(!name&&Object.hasOwn(policy.classes,normalized))){setError('请填写新的分类，已有分类可直接编辑');return}
    const values=Object.fromEntries(Object.entries(months).filter(([,v])=>!!v))
    if(!Object.keys(values).length){setError('请至少填写一种储备月数');return}
    onApply(normalized,values)
  }
  return <Modal title={systemText("分类储备周期")} onClose={onClose}><form className="modal-body" onSubmit={save}>
    <label>{systemText("物料分类 ABC")}<input required disabled={!!name} maxLength={30} placeholder={systemText("例如 A，通用填 *")} value={key} onChange={e=>setKey(e.target.value)}/></label>
    <div className="form-grid">{monthNames.map(([field,label])=><label key={field}>{systemText(label)}<input type="number" step="any" min="0.000000001" value={months[field]||''} onChange={e=>setMonths({...months,[field]:e.target.value})}/></label>)}</div>
    {error&&<Notice tone="error" message={error}/>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>{systemText("取消")}</button><button className="primary">{systemText("应用到草稿")}</button></div>
  </form></Modal>
}

export default function MasterFields({config,warehouse,disabled,onChange}:{config:GovernanceConfig;warehouse?:string;disabled:boolean;onChange:(patch:GovernanceConfig)=>void}){
  const [q,setQ]=useState(''),[page,setPage]=useState(0),[edit,setEdit]=useState<string|null>(null),[importing,setImport]=useState(false),[group,setGroup]=useState<string|null>(null)
  const items=config.master_data?.items||{}, policy=config.target_policy
  const keys=Object.keys(items),filtered=keys.filter(k=>(k+' '+(items[k].material_name||'')).toLowerCase().includes(q.trim().toLowerCase()))
  const pages=Math.max(1,Math.ceil(filtered.length/12)), current=Math.min(page,pages-1), visible=filtered.slice(current*12,current*12+12)
  function applyItems(next:Items){if(warehouse)onChange({master_data:Object.keys(next).length?{warehouse,items:next}:undefined})}
  function applyPolicy(next?:Policy){onChange({target_policy:next})}
  return <>
    <details className="rule-details"><summary>{systemText("物料主数据")}{warehouse?tr(` · ${keys.length} 项`,` · ${keys.length} materials`):''}</summary>
      {!warehouse?<p>{systemText("选择「指定仓库」后可维护物料主数据。")}</p>:<>
        <div className="actions master-actions"><input aria-label={systemText("查找物料主数据")} placeholder={systemText("物料号或备件描述")} value={q} onChange={e=>{setQ(e.target.value);setPage(0)}}/>
          {!disabled&&<><button type="button" className="secondary" onClick={()=>setEdit('')}>{systemText("新增物料")}</button><button type="button" className="secondary" onClick={()=>setImport(true)}>{systemText("批量导入")}</button></>}</div>
        {visible.length>0?<div className="table-scroll"><table><thead><tr><th>{systemText("物料号")}</th><th>{systemText("备件描述")}</th><th>{systemText("分类")}</th><th>{systemText("稳态更换率")}</th><th>{systemText("两项目标")}<br/>{systemText("更换率 / 销量")}</th><th/></tr></thead>
          <tbody>{visible.map(k=><tr key={k}><td>{k}</td><td>{items[k].material_name||'—'}</td><td>{items[k].material_abc||'—'}</td><td>{rates(items[k].replacement_rate)}</td><td>{items[k].replacement_target??'—'} / {items[k].sales_target??'—'}</td><td>{!disabled&&<><button type="button" className="text-button" onClick={()=>setEdit(k)}>{systemText("编辑")}</button><button type="button" className="text-button" onClick={()=>{if(window.confirm(tr('从本草稿移除物料 '+k+'？','Remove '+k+' from this draft?'))){const next={...items};delete next[k];applyItems(next)}}}>{systemText("移除")}</button></>}</td></tr>)}</tbody></table></div>:<p>{q?systemText("未找到匹配物料"):systemText("尚未录入物料")}</p>}
        {filtered.length>12&&<div className="actions master-actions"><button type="button" disabled={!current} onClick={()=>setPage(current-1)}>{systemText("上一页")}</button><span>{current+1} / {pages}</span><button type="button" disabled={current+1>=pages} onClick={()=>setPage(current+1)}>{systemText("下一页")}</button></div>}
      </>}
    </details>
    <details className="rule-details"><summary>{systemText("目标库存计算 ·")} {policy?systemText("按储备周期"):systemText("沿用来源目标")}</summary>
      <label className="check-row"><input type="checkbox" checked={!!policy} disabled={disabled} onChange={e=>{
        if(e.target.checked)applyPolicy({window:'max',rounding:'up',classes:{}})
        else if(window.confirm(systemText('停用目标计算并移除本草稿的分类周期？')))applyPolicy()
      }}/>{systemText("按储备周期自动计算")}</label>
      {policy&&<><div className="form-grid"><label>{systemText("销量窗口")}<select disabled={disabled} value={policy.window} onChange={e=>applyPolicy({...policy,window:e.target.value})}>{Object.entries(windows).map(([k,v])=><option value={k} key={k}>{systemText(v)}</option>)}</select></label>
        <label>{systemText("目标取整")}<select disabled={disabled} value={policy.rounding} onChange={e=>applyPolicy({...policy,rounding:e.target.value})}>{Object.entries(roundings).map(([k,v])=><option value={k} key={k}>{systemText(v)}</option>)}</select></label></div>
        <p>{systemText("物料专用周期优先，其次取分类周期，再取通用周期。缺少计算依据时沿用来源目标。")}</p>
        <table><thead><tr><th>{systemText("物料分类")}</th><th>{systemText("更换率储备月数")}</th><th>{systemText("销量储备月数")}</th><th/></tr></thead><tbody>
          {Object.entries(policy.classes).map(([k,m])=><tr key={k}><td>{k==='*'?systemText("通用"):k}</td><td>{m.replacement_months??'—'}</td><td>{m.sales_months??'—'}</td><td>{!disabled&&<><button type="button" className="text-button" onClick={()=>setGroup(k)}>{systemText("编辑")}</button><button type="button" className="text-button" onClick={()=>{const classes={...policy.classes};delete classes[k];applyPolicy({...policy,classes})}}>{systemText("移除")}</button></>}</td></tr>)}</tbody></table>
        {!disabled&&<button type="button" className="secondary" onClick={()=>setGroup('')}>{systemText("新增分类周期")}</button>}</>}
    </details>
    {!disabled&&warehouse&&edit!==null&&<EditMaterial code={edit} items={items} onClose={()=>setEdit(null)} onSave={(code,row)=>{applyItems({...items,[code]:row});setQ(code);setPage(0);setEdit(null)}}/>}
    {!disabled&&warehouse&&importing&&<ImportMaster warehouse={warehouse} items={items} onClose={()=>setImport(false)} onApply={rows=>{
      const merged=Object.fromEntries(Object.entries(rows).map(([code,row])=>[code,{...items[code],...row}]))
      const next={...items,...merged}
      applyItems(next);setImport(false);setQ('');setPage(0)
    }}/>}
    {!disabled&&policy&&group!==null&&<EditClass name={group} policy={policy} onClose={()=>setGroup(null)} onApply={(key,m)=>{applyPolicy({...policy,classes:{...policy.classes,[key]:m}});setGroup(null)}}/>}
  </>
}
