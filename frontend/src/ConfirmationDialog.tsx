import {useEffect,useRef,useState} from 'react'
import {ChevronLeft,ChevronRight} from 'lucide-react'
import {api,flagLabels} from './api'
import {Modal,Notice,Busy,useFormExit} from './ui'

type IssueRow = {id:string; material_code:string; material_name:string; issues:{message:string}[]; flags:string[]}
type Report = {revision:number; total:number; unreviewed:number; rejected:number; affected_count:number; error_rows:number; air_rows:number; rows:IssueRow[]; issue_hash:string}

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
    <summary>查看提醒 · {report.affected_count} 行</summary>
    {report.rows.length>size&&<div className="list-toolbar"><input type="search" aria-label="搜索提醒物料" placeholder="搜索物料号或名称" value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}}/></div>}
    <div key={position}>{matches.slice(start,start+size).map(row=><article key={row.id}><button type="button" className="text-button" aria-label={'处理 '+row.material_code} disabled={disabled} onClick={()=>onItem(row.id,matches.map(item=>item.id))}>{row.material_code} · {row.material_name}</button><p>{row.issues.map(i=>i.message).join('；')}</p>{row.flags.length>0&&<small>{row.flags.map(f=>flagLabels[f]||f).join(' · ')}</small>}</article>)}
    {!matches.length && <p>无匹配物料</p>}</div>
    {pages>1&&<footer className="table-footer"><span>{start+1}–{Math.min(start+size,matches.length)} / {matches.length} 行</span><div className="pagination"><button type="button" aria-label="上一页问题" className="icon-button" disabled={position===1} onClick={()=>setPage(position-1)}><ChevronLeft size={16}/></button><span>{position} / {pages}</span><button type="button" aria-label="下一页问题" className="icon-button" disabled={position===pages} onClick={()=>setPage(position+1)}><ChevronRight size={16}/></button></div></footer>}
  </details>
}

export default function ConfirmationDialog({kind,ver,onClose,onConfirm,onItem}:{onItem:(id:string,ids:string[])=>Promise<void>;kind:string;ver:any;onClose:()=>void;onConfirm:(v:any)=>Promise<any>}){
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
    api<Report>('/versions/'+ver.id+'/confirmation?all=true&stage='+kind)
      .then(result=>{if(active)setReport(result)})
      .catch(e=>{if(active)setError(e.message)})
    return ()=>{active=false}
  },[ver.id,ver.revision,kind,attempt])
  const submitting=kind==='submit',hasIssues=!!report&&report.affected_count>0
  function close(){if(!saving.current)leaveForm()}
  async function editIssue(id:string,ids:string[]){
    if(saving.current||busy||(reason&&!window.confirm('放弃本次确认说明并处理物料？')))return
    saving.current=true;setBusy(true);setError('')
    try{await onItem(id,ids)}catch(e:any){setError(e.message)}finally{saving.current=false;setBusy(false)}
  }
  async function confirm(e:React.FormEvent){
    e.preventDefault()
    if(saving.current||!report)return
    saving.current=true;setBusy(true);setError('')
    try {
      await onConfirm({revision:report.revision,issue_hash:report.issue_hash,reason})
    } catch(e:any) {
      setError(e.message)
      if(e.status===409)setReport(null)
    } finally {saving.current=false;setBusy(false)}
  }
  return <Modal title={submitting?'提交复审':'完成终审'} onClose={close} wide><form className="modal-body" onSubmit={confirm}>
    {error&&<Notice message={error} tone="error"/>}
    {!report?(error?<button type="button" className="text-button" onClick={()=>setAttempt(n=>n+1)}>刷新提醒</button>:<Busy/>):<>
      <p>第 {ver.seq} 版，共 <strong>{report.total}</strong> 行。{submitting?'提交后由本仓复审人员领取。':`本次结案：通过 ${report.total-report.rejected} 行，不批准 ${report.rejected} 行。`}</p>
      {ver.summary.PENDING>0&&<Notice message={ver.summary.PENDING+' 行尚缺基础数据，需人工核对。'} tone="info"/>}
      {hasIssues&&<Notice message={`其中 ${report.affected_count} 行有审核提醒，可继续${submitting?'提交':'终审'}。`}/>}
      {!submitting&&report.unreviewed>0&&<p className="muted">{report.unreviewed} 行尚未单独复审，将记为「整批通过」。</p>}
      {hasIssues&&<IssueList key={report.issue_hash} report={report} disabled={busy} onItem={editIssue}/>}
      <details><summary>添加备注（选填）</summary><label>备注<textarea disabled={busy} rows={2} maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label></details>
    </>}
    <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>返回明细</button><button className="primary" disabled={busy||!report}>{busy?'正在保存…':submitting?'确认提交':'确认终审'}</button></div>
  </form></Modal>
}
