import {useEffect,useRef,useState} from 'react'
import {ChevronLeft,ChevronRight,RefreshCw,X} from 'lucide-react'
import {api,labels} from './api'
import {Badge,Busy,Notice} from './ui'
import VersionChanges from './VersionChanges'

type Version={id:string;seq:number;state:string}
type EventDetail={reason?:string;decision?:string;rows?:number;count?:number;approved?:number;batch_approved?:number;warning_rows?:number;selected_count?:number;filtered?:boolean;source_number?:string;source_seq?:number;material_codes?:string[]}
type Activity={id:string;action:string;actor:string;at:string;detail:EventDetail}
type ActivityPage={items:Activity[];total:number;page:number;page_size:number}
const timestamp=new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})

function eventSummary(detail:EventDetail){
 if(detail.source_number)return detail.source_number+' · 第 '+detail.source_seq+' 版'
 if(detail.decision&&detail.approved!==undefined)return (labels[detail.decision]||detail.decision)+' '+detail.approved+' 行'
 if(detail.filtered!==undefined)return (detail.filtered?'筛选结果':'完整版本')+' · '+detail.rows+' 行'
 if(detail.warning_rows!==undefined)return [detail.rows!==undefined?detail.rows+' 行':'',detail.warning_rows+' 行有提醒',detail.batch_approved?detail.batch_approved+' 行整批通过':''].filter(Boolean).join(' · ')
 if(detail.rows!==undefined)return detail.rows+' 行'
 if(detail.count!==undefined)return detail.count+' 行'
 if(detail.selected_count)return '涉及 '+detail.selected_count+' 行'
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
 return <section className="panel history-panel"><div className="panel-heading"><h2>版本记录</h2><button className="icon-button" aria-label="关闭版本记录" onClick={onClose}><X size={18}/></button></div>
  <div className="history-grid"><div className="version-list">{versions.map(v=><div className={v.id===selected.id?'selected':''} key={v.id}>
   <button type="button" aria-current={v.id===selected.id?'true':undefined} disabled={busy} onClick={()=>onSelect(v.id)}><strong>第 {v.seq} 版</strong><Badge value={v.state}/>{v.id===current&&<small>最新版</small>}</button>
   {v.id!==selected.id&&<button className="text-button" disabled={busy||comparing} onClick={()=>compare(v)}>与第 {selected.seq} 版对比</button>}
  </div>)}</div>
  <div className="version-activity"><div className="panel-heading"><h3>第 {selected.seq} 版动态</h3><button aria-label="刷新版本动态" className="icon-button" onClick={()=>setAttempt(attempt+1)}><RefreshCw size={15}/></button></div>
   {error?<Notice message={error} tone="error"/>:!activity?<Busy/>:activity.total===0?<p className="muted">本版暂无操作记录</p>:<div className="event-list">{activity.items.map(e=><div key={e.id}><i/><span><strong>{e.action}</strong>{eventSummary(e.detail)&&<p>{eventSummary(e.detail)}</p>}{e.detail.reason&&<p>{e.detail.reason}</p>}
    {!!e.detail.material_codes?.length&&<details><summary>指定物料 · {e.detail.material_codes.length} 行</summary><p>{e.detail.material_codes.join('、')}</p></details>}
    <small>{e.actor} · {timestamp.format(new Date(e.at))}</small></span></div>)}</div>}
   {activity&&pages>1&&<div className="table-footer"><span>共 {activity.total} 条</span><span className="spacer"/><button className="icon-button" aria-label="上一页版本动态" disabled={activity.page<=1} onClick={()=>setPage(activity.page-1)}><ChevronLeft size={15}/></button><span>{activity.page} / {pages}</span><button className="icon-button" aria-label="下一页版本动态" disabled={activity.page>=pages} onClick={()=>setPage(activity.page+1)}><ChevronRight size={15}/></button></div>}
  </div></div>
  {comparing&&<Busy text="正在比较版本…"/>}{diffError&&<Notice message={diffError} tone="error"/>}{diff&&<VersionChanges diff={diff}/>}
 </section>
}
