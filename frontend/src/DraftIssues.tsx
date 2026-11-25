import {tr, systemText} from './i18n'
import {planMessage} from './planMessages'
import {useEffect,useId,useState} from 'react'
import {CheckCircle2,ChevronDown,ChevronLeft,ChevronRight,CircleAlert} from 'lucide-react'
import {api} from './api'
import './draft-issues.css'

type Group='all'|'returned'|'required'|'advisory'
const labels={all:'全部',returned:'上轮未通过',required:'提交必填',advisory:'审核提醒'}
type Row={id:string;material_code:string;material_name:string;groups:Exclude<Group,'all'>[];messages:string[]}
type Report={affected:number;total:number;counts:Record<Exclude<Group,'all'>,number>;page:number;pages:number;rows:Row[];change_rule:boolean}
type Props={
 versionId:string;revision:number;edits:Record<string,Record<string,string>>;busy:boolean
 onRow:(id:string,ids:string[])=>void;onBasis:()=>void
}

export default function DraftIssues({versionId,revision,edits,busy,onRow,onBasis}:Props){
 const [expanded,setExpanded]=useState(false),[group,setGroup]=useState<Group>('all'),[page,setPage]=useState(1)
 const [report,setReport]=useState<Report|null>(null),[loading,setLoading]=useState(true)
 const [error,setError]=useState(''),[retry,setRetry]=useState(0)
 const listId=useId()
 useEffect(()=>{
  const controller=new AbortController()
  setLoading(true);setError('')
  const timer=window.setTimeout(async()=>{
   try{
    const data=await api<Report>(`/versions/${versionId}/issue-preview`,{revision,edits,group,page},undefined,undefined,controller.signal)
    if(!controller.signal.aborted)setReport(data)
   }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:systemText("核对失败"))}
   finally{if(!controller.signal.aborted)setLoading(false)}
  },Object.keys(edits).length?240:0)
  return ()=>{window.clearTimeout(timer);controller.abort()}
 },[versionId,revision,edits,group,page,retry])
 const summary=error?systemText("问题清单暂未更新"):loading?systemText("正在核对整份计划…"):report?.affected?tr(`${report.affected} / ${report.total} 行需关注`,`${report.affected} of ${report.total} rows need attention`):tr(`已核对 ${report?.total??0} 行`,`Checked ${report?.total??0} rows`)
 return <section className="draft-issues" aria-label={systemText("全计划问题")}>
  <div className="draft-issues-head">
   <button type="button" aria-expanded={expanded} aria-controls={listId} onClick={()=>{if(expanded){setGroup('all');setPage(1)}setExpanded(!expanded)}}>
    {report&&!report.affected&&!error?<CheckCircle2 size={16}/>:<CircleAlert size={16}/>}
    <strong>{systemText("待处理问题")}</strong><span role="status">{summary}</span><ChevronDown size={14} className={expanded?'turned':''}/>
   </button>
   {!expanded&&!error&&report?.rows[0]&&!loading&&<button type="button" className="issue-peek" disabled={busy}
    title={report.rows[0].messages.map(planMessage).join(' · ')} onClick={()=>onRow(report.rows[0].id,report.rows.map(row=>row.id))}>
    <b>{report.rows[0].material_code}</b><span>{planMessage(report.rows[0].messages[0])}</span><ChevronRight size={13}/>
   </button>}
   {!error&&report&&!loading&&<div className="issue-counts">{(['returned','required','advisory'] as const).filter(key=>report.counts[key]>0).map(key=><button type="button" key={key} onClick={()=>{setExpanded(true);setGroup(key);setPage(1)}}>{systemText(labels[key])} {report.counts[key]}</button>)}</div>}
   {error&&<button className="text-button" title={error} onClick={()=>setRetry(n=>n+1)}>{systemText("重试")}</button>}
  </div>
  {report?.change_rule&&<button className="text-button issue-basis" disabled={busy} onClick={onBasis}>{systemText("提交前需更换计算依据")}</button>}
  {expanded&&<div id={listId} className="issue-details">
   <div className="issue-groups">{(Object.keys(labels) as Group[]).map(key=><button type="button" key={key} aria-pressed={group===key} onClick={()=>{setGroup(key);setPage(1)}}>{systemText(labels[key])}</button>)}</div>
   {error?<p role="alert">{error}</p>:report&&<><ul aria-busy={loading}>{report.rows.map(row=><li key={row.id}>
    <button type="button" disabled={busy||loading} onClick={()=>onRow(row.id,report.rows.map(r=>r.id))}>
     <b>{row.material_code}</b><span>{row.material_name}</span><span>{row.messages.map(planMessage).join(' · ')}</span><ChevronRight size={14}/>
    </button></li>)}</ul>
    {!report.rows.length&&<p>{systemText("当前分类没有待处理问题")}</p>}
    {report.pages>1&&<div className="issue-pages"><button aria-label={systemText("上一页问题")} disabled={loading||report.page<=1} onClick={()=>setPage(report.page-1)}><ChevronLeft size={14}/></button><span>{report.page} / {report.pages}</span><button aria-label={systemText("下一页问题")} disabled={loading||report.page>=report.pages} onClick={()=>setPage(report.page+1)}><ChevronRight size={14}/></button></div>}
   </>}
  </div>}
 </section>
}
