import {tr, systemText} from './i18n'
import WarehouseLabel from './WarehouseLabel'
import {FormEvent,useRef,useState} from 'react'
import {api} from './api'
import {currentWeek,weekLabel} from './periods'
import {Modal,Notice,useFormExit} from './ui'

export default function CopyPlan({batch,version,onClose,onCreated}:{
 batch:{id:string;title:string;period:string;warehouse:string;warehouse_name:string}
 version:{id:string;seq:number;revision:number;summary:{total:number};snapshot:{name:string}|null;latest_rule_id:string;latest_rule_name?:string}
 onClose:()=>void;onCreated:(id:string)=>void
}){
 const [initialTitle]=useState(()=>batch.title.slice(0,113)+tr(' · 副本',' · Copy'))
 const [title,setTitle]=useState(initialTitle),[period,setPeriod]=useState(batch.period)
 const [kind,setKind]=useState(batch.period.includes('-W')?'week':'month')
 const [busy,setBusy]=useState(false),[error,setError]=useState('')
 const saving=useRef(false)
 const close=useFormExit(title!==initialTitle||period!==batch.period,busy,onClose)
 function changeKind(value:string){
  setKind(value)
  const original=value==='week'?/^\d{4}-W\d{2}$/:/^\d{4}-\d{2}$/
  setPeriod(original.test(batch.period)?batch.period:value==='week'?currentWeek():new Date().toLocaleDateString('sv-SE').slice(0,7))
 }
 async function copy(e:FormEvent){
  e.preventDefault()
  if(saving.current)return
  saving.current=true;setBusy(true);setError('')
  try{
   const result=await api('/batches/'+batch.id+'/copy',{version_id:version.id,revision:version.revision,rule_id:version.latest_rule_id,title:title.trim(),period})
   onCreated(result.id)
  }catch(e:any){setError(e.message)}finally{saving.current=false;setBusy(false)}
 }
 return <Modal title={systemText("复制为新计划")} onClose={close}><form className="modal-body" onSubmit={copy}>
  {error&&<Notice message={error} tone="error"/>}
  <p>{systemText("来源：")}<WarehouseLabel code={batch.warehouse} name={batch.warehouse_name}/> · {tr(`第 ${version.seq} 版`,`Version ${version.seq}`)} · {version.summary.total} {systemText("行")}</p>
  {version.snapshot && <p className="muted">{systemText("沿用")}{version.snapshot.name}{version.latest_rule_name?systemText("，按「")+version.latest_rule_name+systemText("」重算。"):systemText("，按当前已发布标准重算。")}</p>}
  <label>{systemText("新计划名称")}<input required maxLength={120} disabled={busy} value={title} onChange={e=>setTitle(e.target.value)}/></label>
  <div className="form-grid"><label>{systemText("周期类型")}<select value={kind} disabled={busy} onChange={e=>changeKind(e.target.value)}><option value="month">{systemText("月计划")}</option><option value="week">{systemText("周计划")}</option></select></label>
   <label>{systemText("计划周期")}<input aria-label={systemText("计划周期")} type={kind} disabled={busy} value={period} required onChange={e=>setPeriod(e.target.value)}/>{kind==='week'&&period&&<small>{weekLabel(period)}</small>}</label></div>
  <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>{systemText("取消")}</button><button className="primary" disabled={busy||!title.trim()||!period}>{busy?systemText("正在创建…"):systemText("创建新草稿")}</button></div>
 </form></Modal>
}
