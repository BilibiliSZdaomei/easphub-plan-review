import {tr, systemText} from './i18n'
import {planMessage} from './planMessages'
import {useEffect,useRef,useState} from 'react'
import {ChevronLeft,ChevronRight} from 'lucide-react'
import {api,flagLabels} from './api'
import {Modal,Notice,Busy,useFormExit} from './ui'

type IssueRow = {id:string; material_code:string; material_name:string; issues:{message:string}[]; flags:string[]}
type Report = {revision:number; total:number; unreviewed:number; approval_blocked:boolean; reviewed_approved:number; reviewed_exception:number; unreviewed_exception:number; exception_approved:number; rejected:number; affected_count:number; error_rows:number; air_rows:number; rows:IssueRow[]; issue_hash:string}

function IssueList({report,disabled,onItem}:{report:Report;disabled:boolean;onItem:(row:string,ids:string[])=>void}){
  const [page,setPage]=useState(1)
  const [search,setSearch]=useState('')
  const query=search.trim().toLowerCase()
  const matches=report.rows.filter(row=>(row.material_code+' '+row.material_name).toLowerCase().includes(query))
  const size=20
  const pages=Math.max(1,Math.ceil(matches.length/size))
  const position=Math.min(page,pages)
  const start=(position-1)*size
  return <details className="confirmation-issues">
    <summary>{systemText("查看提醒 ·")} {report.affected_count} {systemText("行")}</summary>
    {report.rows.length>size&&<div className="list-toolbar"><input type="search" aria-label={systemText("搜索提醒物料")} placeholder={systemText("搜索物料号或名称")} value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}}/></div>}
    <div key={position}>{matches.slice(start,start+size).map(row=><article key={row.id}><button type="button" className="text-button" aria-label={systemText("处理 ")+row.material_code} disabled={disabled} onClick={()=>onItem(row.id,matches.map(item=>item.id))}>{row.material_code} · {row.material_name}</button><p>{row.issues.map(i=>planMessage(i.message)).join(tr('；','; '))}</p>{row.flags.length>0&&<small>{row.flags.map(f=>flagLabels[f]||f).join(' · ')}</small>}</article>)}
    {!matches.length && <p>{systemText("无匹配物料")}</p>}</div>
    {pages>1&&<footer className="table-footer"><span>{start+1}–{Math.min(start+size,matches.length)} / {matches.length} {systemText("行")}</span><div className="pagination"><button type="button" aria-label={systemText("上一页问题")} className="icon-button" disabled={position===1} onClick={()=>setPage(position-1)}><ChevronLeft size={16}/></button><span>{position} / {pages}</span><button type="button" aria-label={systemText("下一页问题")} className="icon-button" disabled={position===pages} onClick={()=>setPage(position+1)}><ChevronRight size={16}/></button></div></footer>}
  </details>
}

export default function ConfirmationDialog({kind,ver,onClose,onConfirm,onItem,onChanged}:{onChanged:()=>void;onItem:(id:string,ids:string[])=>Promise<void>;kind:string;ver:any;onClose:()=>void;onConfirm:(v:any)=>Promise<any>}){
  const [report,setReport]=useState<Report|null>(null)
  const [reason,setReason]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const saving=useRef(false)
  const leaveForm=useFormExit(!!reason,busy,onClose)
  const [attempt,setAttempt]=useState(0)
  useEffect(()=>{
    let active=true
    setReport(null);setError('')
    api<Report>('/versions/'+ver.id+'/confirmation?all=true&stage='+(kind==='submit'?'submit':'finalize'))
      .then(result=>{if(active)setReport(result)})
      .catch(e=>{if(active)setError(e.message)})
    return ()=>{active=false}
  },[ver.id,ver.revision,kind,attempt])
  const submitting=kind==='submit',rejecting=kind==='rejectPlan',hasIssues=!!report&&report.affected_count>0
  const staleAction=!!report&&!submitting&&(rejecting!==report.approval_blocked)
  const title=submitting?systemText("提交复审"):rejecting?systemText("整单不批准"):systemText("整单通过")
  function close(){if(!saving.current)leaveForm()}
  async function editIssue(id:string,ids:string[]){
    if(saving.current||busy||(reason&&!window.confirm(systemText("放弃本次确认说明并处理物料？"))))return
    saving.current=true;setBusy(true);setError('')
    try{await onItem(id,ids)}catch(e:any){setError(e.message)}finally{saving.current=false;setBusy(false)}
  }
  async function confirm(e:React.FormEvent){
    e.preventDefault()
    if(saving.current||!report||staleAction)return
    saving.current=true;setBusy(true);setError('')
    try {
      await onConfirm({revision:report.revision,issue_hash:report.issue_hash,reason,
        ...(!submitting?{outcome:rejecting?'REJECTED':'APPROVED'}:{})})
    } catch(e:any) {
      setError(e.message)
      if(e.status===409)setReport(null)
    } finally {saving.current=false;setBusy(false)}
  }
  return <Modal title={title} onClose={close} wide><form className="modal-body" onSubmit={confirm}>
    {error&&<Notice message={error} tone="error"/>}
    {!report?(error?<button type="button" className="text-button" onClick={()=>setAttempt(n=>n+1)}>{systemText("刷新提醒")}</button>:<Busy/>):<>
      {staleAction?<Notice message={systemText("行复审意见已更新，请返回明细重新选择结案方式。")}/>:<>
       {submitting?<p>{tr(`第 ${ver.seq} 版，共`, `Version ${ver.seq} contains`)}  <strong>{report.total}</strong> {systemText("行。提交后由本仓复审人员领取。")}</p>
        :rejecting?<><p>{systemText("本版")} <strong>{report.total}</strong> {systemText("行均不执行。结案后，计划员不会收到修改草稿。")}</p>
          <p className="muted">{tr(`现有行意见将保留：批准 ${report.reviewed_approved} 行，不批准 ${report.rejected} 行，未审 ${report.unreviewed} 行。`, `Existing decisions will be retained. Approved: ${report.reviewed_approved}. Rejected: ${report.rejected}. Not reviewed: ${report.unreviewed}.`)}</p></>
        :<><p>{tr(`本版将整单通过，共 ${report.total} 行，含例外批准 ${report.exception_approved} 行。`, `All ${report.total} rows will be approved, including ${report.exception_approved} by exception.`)}</p>
          {report.unreviewed>0&&<p className="muted">{tr(`${report.unreviewed} 行尚未单独复审。确认后将批量批准 ${report.unreviewed-report.unreviewed_exception} 行、例外批准 ${report.unreviewed_exception} 行。`, `${report.unreviewed} rows have no individual decision. Confirming will approve ${report.unreviewed-report.unreviewed_exception} of them in bulk and ${report.unreviewed_exception} by exception.`)}</p>}</>}
       {!rejecting&&ver.summary.PENDING>0&&<Notice message={ver.summary.PENDING+systemText(" 行尚缺基础数据，需人工核对。")} tone="info"/>}
       {!rejecting&&hasIssues&&<><Notice message={tr(`其中 ${report.affected_count} 行有审核提醒，可继续${submitting?'提交':'终审'}。`,`${report.affected_count} rows have alerts. You may still ${submitting?"submit this plan":"complete the final review"}.`)}/>
         <IssueList key={report.issue_hash} report={report} disabled={busy} onItem={editIssue}/></>}
      </>}
      {!staleAction&&<details><summary>{systemText("添加备注（选填）")}</summary><label>{systemText("备注")}<textarea disabled={busy} rows={2} maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label></details>}
    </>}
    <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={staleAction?onChanged:close}>{systemText("返回明细")}</button><button className={rejecting?"primary reject-entire-plan":"primary"} disabled={busy||!report||staleAction}>{busy?systemText("正在保存…"):submitting?systemText("确认提交"):rejecting?systemText("确认整单不批准"):systemText("确认整单通过")}</button></div>
  </form></Modal>
}
