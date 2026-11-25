import {tr, systemText} from './i18n'
import {useEffect,useRef,useState} from 'react'
import {ChevronLeft,ChevronRight,RefreshCw,X} from 'lucide-react'
import {api,labels,planStateLabel} from './api'
import {Badge,Busy,Notice} from './ui'
import VersionChanges from './VersionChanges'

type Version={id:string;seq:number;state:string}
type EventDetail={operation?:string;outcome?:string;reviewed_approved?:number;reviewed_rejected?:number;unreviewed?:number;reason?:string;decision?:string;rows?:number;count?:number;approved?:number;rejected?:number;exception_approved?:number;batch_approved?:number;warning_rows?:number;selected_count?:number;filtered?:boolean;source_number?:string;source_seq?:number;material_codes?:string[]}
type Activity={id:string;action:string;actor:string;at:string;detail:EventDetail}
type ActivityPage={items:Activity[];total:number;page:number;page_size:number}
const timestamp=()=>new Intl.DateTimeFormat(tr('zh-CN','en-GB'),{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})

function activityTitle(event:Activity){
 if(event.detail.operation){
  if(event.action==='撤销明细操作')return systemText("撤销 · ")+systemText(event.detail.operation)
  if(event.action==='重做明细操作')return systemText("重做 · ")+systemText(event.detail.operation)
 }
 return systemText(event.action)
}

function eventSummary(detail:EventDetail,event:string,version:string){
 if(event==='撤销明细操作'||event==='重做明细操作')return detail.count?systemText("涉及 ")+detail.count+systemText(" 行"):''
 if(detail.outcome==='REJECTED')return [systemText("整单不批准"),detail.rejected+systemText(" 行均不执行"),detail.unreviewed ? detail.unreviewed+systemText(" 行未审") : ''].filter(Boolean).join(' · ')
 if(detail.outcome==='APPROVED')return [systemText("整单通过"),detail.approved+systemText(" 行"),detail.exception_approved ? systemText("含例外批准 ")+detail.exception_approved+systemText(" 行") : ''].filter(Boolean).join(' · ')
 if(event==='完成终审' && version==='PARTIALLY_APPROVED')return [planStateLabel(version),systemText("原行意见：批准 ")+(detail.approved??0)+systemText(" 行，不批准 ")+(detail.rejected??0)+systemText(" 行")].join(' · ')
 if(detail.source_number)return detail.source_number+tr(` · 第 ${detail.source_seq} 版`, ` · Version ${detail.source_seq}`)
 if(detail.decision&&detail.count!==undefined)return [(labels[detail.decision]||detail.decision)+' '+detail.count+systemText(" 行"),detail.exception_approved?systemText("含例外批准 ")+detail.exception_approved+systemText(" 行"):''].filter(Boolean).join(' · ')
 if(detail.approved!==undefined&&detail.rejected!==undefined)return [systemText("通过 ")+detail.approved+systemText(" 行"),systemText("不批准 ")+detail.rejected+systemText(" 行"),detail.exception_approved?systemText("含例外批准 ")+detail.exception_approved+systemText(" 行"):''].filter(Boolean).join(' · ')
 if(detail.decision&&detail.approved!==undefined)return (labels[detail.decision]||detail.decision)+' '+detail.approved+systemText(" 行")
 if(detail.filtered!==undefined)return (detail.filtered?systemText("筛选结果"):systemText("完整版本"))+' · '+detail.rows+systemText(" 行")
 if(detail.warning_rows!==undefined)return [detail.rows!==undefined?detail.rows+systemText(" 行"):'',detail.warning_rows+systemText(" 行有提醒"),detail.batch_approved?detail.batch_approved+systemText(" 行整批通过"):''].filter(Boolean).join(' · ')
 if(detail.rows!==undefined)return detail.rows+systemText(" 行")
 if(detail.operation)return [systemText(detail.operation),detail.count ? detail.count+systemText(" 行") : ''].filter(Boolean).join(' · ')
 if(detail.count!==undefined)return detail.count+systemText(" 行")
 if(detail.selected_count)return systemText("涉及 ")+detail.selected_count+systemText(" 行")
 return ''
}

export default function VersionHistory({versions,selected,current,revision,busy,onSelect,onClose}:{
 versions:Version[];selected:Version;current:string;revision:number;busy:boolean
 onSelect:(id:string)=>void;onClose:()=>void
}){
 const [page,setPage]=useState(1),[attempt,setAttempt]=useState(0)
 const [activity,setActivity]=useState<ActivityPage|null>(null),[error,setError]=useState('')
 const [diff,setDiff]=useState<any>(null),[diffError,setDiffError]=useState(''),[comparing,setComparing]=useState(false)
 const comparison=useRef(0)
 useEffect(()=>{
  let active=true
  setActivity(null);setError('')
  api<ActivityPage>('/versions/'+selected.id+'/activity?page='+page)
   .then(result=>{if(active)setActivity(result)}).catch(e=>{if(active)setError(e.message)})
  return()=>{active=false}
 },[selected.id,revision,page,attempt])
 useEffect(()=>()=>{comparison.current++},[])
 async function compare(other:Version){
  const seq=++comparison.current
  const [older,newer]=selected.seq<other.seq?[selected,other]:[other,selected]
  setComparing(true);setDiff(null);setDiffError('')
  try{const result=await api('/versions/'+newer.id+'/diff?against='+older.id);if(seq===comparison.current)setDiff(result)}
  catch(e:any){if(seq===comparison.current)setDiffError(e.message)}
  finally{if(seq===comparison.current)setComparing(false)}
 }
 const pages=activity?Math.ceil(activity.total/activity.page_size):0
 return <section className="panel history-panel"><div className="panel-heading"><h2>{systemText("版本记录")}</h2><button className="icon-button" aria-label={systemText("关闭版本记录")} onClick={onClose}><X size={18}/></button></div>
  <div className="history-grid"><div className="version-list">{versions.map(v=><div className={v.id===selected.id?'selected':''} key={v.id}>
   <button type="button" aria-current={v.id===selected.id?'true':undefined} disabled={busy} onClick={()=>onSelect(v.id)}><strong>{tr(`第 ${v.seq} 版`, `Version ${v.seq}`)}</strong><Badge value={v.state} label={planStateLabel(v.state)}/>{v.id===current&&<small>{systemText("最新版")}</small>}</button>
   {v.id!==selected.id&&<button className="text-button" disabled={busy||comparing} onClick={()=>compare(v)}>{tr(`与第 ${selected.seq} 版对比`, `Compare with version ${selected.seq}`)}</button>}
  </div>)}</div>
  <div className="version-activity"><div className="panel-heading"><h3>{tr(`第 ${selected.seq} 版动态`, `Version ${selected.seq} activity`)}</h3><button aria-label={systemText("刷新版本动态")} className="icon-button" onClick={()=>setAttempt(attempt+1)}><RefreshCw size={15}/></button></div>
   {error?<Notice message={error} tone="error"/>:!activity?<Busy/>:activity.total===0?<p className="muted">{systemText("本版暂无操作记录")}</p>:<div className="event-list">{activity.items.map(e=><div key={e.id}><i/><span><strong>{activityTitle(e)}</strong>{eventSummary(e.detail,e.action,selected.state)&&<p>{eventSummary(e.detail,e.action,selected.state)}</p>}{e.detail.reason&&<p>{e.detail.reason}</p>}
    {!!e.detail.material_codes?.length&&<details><summary>{systemText("指定物料 ·")} {e.detail.material_codes.length} {systemText("行")}</summary><p>{e.detail.material_codes.join('、')}</p></details>}
    <small>{e.actor} · {timestamp().format(new Date(e.at))}</small></span></div>)}</div>}
   {activity&&pages>1&&<div className="table-footer"><span>{systemText("共")} {activity.total} {systemText("条")}</span><span className="spacer"/><button className="icon-button" aria-label={systemText("上一页版本动态")} disabled={activity.page<=1} onClick={()=>setPage(activity.page-1)}><ChevronLeft size={15}/></button><span>{activity.page} / {pages}</span><button className="icon-button" aria-label={systemText("下一页版本动态")} disabled={activity.page>=pages} onClick={()=>setPage(activity.page+1)}><ChevronRight size={15}/></button></div>}
  </div></div>
  {comparing&&<Busy text={systemText("正在比较版本…")}/>}{diffError&&<Notice message={diffError} tone="error"/>}{diff&&<VersionChanges diff={diff}/>}
 </section>
}
