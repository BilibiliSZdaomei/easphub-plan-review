import {systemText} from './i18n'
import {useEffect, useState} from 'react'
import {api} from './api'
import {Modal, Notice} from './ui'

type Reviewer = {id:string; name:string; username:string}

export default function ReviewTransfer({versionId,onClose,onTransfer}:{
 versionId:string; onClose:()=>void; onTransfer:(id:string)=>Promise<void>
}){
 const [reviewers,setReviewers]=useState<Reviewer[]|null>(null)
 const [recipient,setRecipient]=useState('')
 const [error,setError]=useState('')
 const [busy,setBusy]=useState(false)
 useEffect(()=>{
  let active=true
  api<Reviewer[]>('/versions/'+versionId+'/reviewers')
   .then(list=>{if(active)setReviewers(list)})
   .catch(e=>{if(active)setError(e.message)})
  return ()=>{active=false}
 },[versionId])
 return <Modal title={systemText("转交复审")} onClose={()=>{if(!busy)onClose()}}>
  <form className="modal-body" onSubmit={async e=>{
   e.preventDefault()
   if(!recipient||busy)return
   setBusy(true);setError('')
   try{await onTransfer(recipient)}catch(e:any){setError(e.message)}finally{setBusy(false)}
  }}>
   {error&&<Notice tone="error" message={error}/>}
   <label>{systemText("接手人")}<select value={recipient} required disabled={busy||!reviewers?.length}
    onChange={e=>setRecipient(e.target.value)}>
    <option value="">{reviewers===null?systemText("正在读取…"):reviewers.length?systemText("选择复审员"):systemText("暂无其他可接手的复审员")}</option>
    {reviewers?.map(u=><option key={u.id} value={u.id}>{u.name}（{u.username}）</option>)}
   </select></label>
   <p className="muted">{systemText("已保存的逐行决定随计划转交。")}</p>
   <div className="modal-actions">
    <button className="secondary" type="button" disabled={busy} onClick={onClose}>{systemText("取消")}</button>
    <button className="primary" disabled={!recipient||busy}>{systemText("确认转交")}</button>
   </div>
  </form>
 </Modal>
}
