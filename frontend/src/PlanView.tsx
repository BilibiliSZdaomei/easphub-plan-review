import {tr, systemText, getLanguage} from './i18n'
import {periodLabel} from './periods'
import {planMessage} from './planMessages'
import DraftIssues from './DraftIssues'
import {PlanHistoryControls,useQuantityDraft,type HistoryDirection} from './PlanUndo'
import {canPlan,canReview} from './roles'
import {FocusControls,usePlanFocus} from './PlanFocus'
import WarehouseLabel from './WarehouseLabel'
import {createPortal} from 'react-dom'
import {useState,useEffect,useRef,FormEvent} from 'react'
import {ArrowLeft,ArrowRight,Download,Upload,Plus,Search,ChevronLeft,ChevronRight,Check,CheckCheck,Send,RotateCcw,Copy,History,Save,SlidersHorizontal,FileSpreadsheet,AlertCircle,X,RefreshCw,Ban} from 'lucide-react'
import ReviewTable,{ColumnPicker,TableViewControls,DEFAULT_COLUMNS,withMaterialColumns,EMPTY_TABLE,TableState} from './ReviewTable'
import BasisDialog from './BasisDialog'
import V3TemplateDownload from './V3TemplateDownload'
import PlanReference,{referenceLabels} from './PlanReference'
import VersionHistory from './VersionHistory'
import CopyPlan from './CopyPlan'
import ConfirmationDialog from './ConfirmationDialog'
import ReviewTransfer from './ReviewTransfer'
import {api,waitJob,BASE,fmt,date,planStateLabel,flagLabels,reasonLabel,reasonLabels,completedStates} from './api'
import {Badge,Busy,Empty,Modal,Notice,Stepper,useDialog,useFormExit} from './ui'

const pageCapacities=['15','50','100','300','500','1000','all']
export default function PlanView({batchId,user,onBack,onUpdate,notify,onDirty,onOpenBatch,backLabel=systemText("返回计划列表")}:{backLabel?:string;onOpenBatch:(id:string)=>void;onDirty:(v:boolean)=>void;batchId:string;user:any;onBack:()=>void;onUpdate:()=>void;notify:(s:string)=>void}){
 const focus=usePlanFocus(notify)
 const [batch,setBatch]=useState<any>(null),[ver,setVer]=useState<any>(null),[versionId,setVersionId]=useState(''),[q,setQ]=useState(''),[filter,setFilter]=useState('all'),[page,setPage]=useState(1),[busy,setBusy]=useState(false),[error,setError]=useState(''),[issueRows,setIssueRows]=useState<any[]>([])
 const [selected,setSelected]=useState<Set<string>>(new Set()),[detail,setDetail]=useState<any>(null),[dialog,setDialog]=useState(''),[history,setHistory]=useState(false),[exporting,setExporting]=useState(false),[reviewMeta,setReviewMeta]=useState<any>({flags:[],exception:false})
 const draft=useQuantityDraft()
 const edits=draft.edits
 // A local redo stays anchored to the saved state from which the quantities were edited.
 const [savedStepsToDraft,setSavedStepsToDraft]=useState(0)
 function clearLocalHistory(){draft.clear();setSavedStepsToDraft(0)}
 const [visibleCols,setVisibleCols]=useState<string[]>(()=>{try{return withMaterialColumns(JSON.parse(localStorage.getItem('plan-columns-v2-'+user.id)||'null'))}catch{return DEFAULT_COLUMNS}})
 const [bulkMode,setBulkMode]=useState(false)
 const [issueListOpen,setIssueListOpen]=useState(false)
 const [tableState,setTableState]=useState<TableState>(EMPTY_TABLE)
 const [capacity,setCapacity]=useState(()=>{
  const saved=localStorage.getItem('plan-page-size-'+user.id)||''
  return pageCapacities.includes(saved)?saved:'15'
 })
 function changeCapacity(value:string){
  setCapacity(value);setPage(1);localStorage.setItem('plan-page-size-'+user.id,value)
 }
 useEffect(()=>{localStorage.setItem('plan-columns-v2-'+user.id,JSON.stringify(visibleCols))},[visibleCols])
 const [density,setDensity]=useState<'compact'|'standard'>(()=>localStorage.getItem('plan-density-'+user.id)==='compact'?'compact':'standard')
 useEffect(()=>{localStorage.setItem('plan-density-'+user.id,density)},[density,user.id])
 const [queue,setQueue]=useState<string[]>([]),[drawerDirty,setDrawerDirty]=useState(false)
 const [pending,setPending]=useState<{run:()=>void}|null>(null)
 const lock=useRef(false)
 const tableQuery=`&column_filters=${encodeURIComponent(JSON.stringify(tableState.filters))}&sort_key=${encodeURIComponent(tableState.sortKey)}&sort_direction=${tableState.sortDirection}`
 const versionQuery='?table_view=true&include_batch_context=true&q='+encodeURIComponent(q)+'&filter='+filter+'&page='+page+'&page_size='+(capacity==='all'?10000:capacity)+tableQuery
 function changeTable(next:TableState){setTableState(next);setPage(1);setSelected(new Set())}
 const requestSeq=useRef(0)
 const loadedPath=useRef('')
 const draftBase=useRef<{scope:string;revision:number}|null>(null)
 const dirtyRef=useRef(false)
 dirtyRef.current=Object.keys(edits).length>0
 function selectVersion(id:string){
  if(id===ver.id)return
  proceed(()=>{clearLocalHistory();setVersionId(id);setVer(null);setPage(1);setSelected(new Set());setError('')})
 }
 async function load(id?:string,refreshBatch=true,move?:{direction:HistoryDirection;from:number;to:number}){
  const seq=++requestSeq.current
  const overview='/batches/'+batchId+'?include_events=false'
  try{
   let summary=refreshBatch||!batch?await api(overview):batch
   const vid=id||versionId||summary.current_id
   const version=await api('/versions/'+vid+versionQuery)
   if(seq!==requestSeq.current)return
   if(summary.current_id!==version.batch_current_id||summary.state!==version.batch_state||summary.updated_at!==version.batch_updated_at){
    summary=await api(overview)
    if(seq!==requestSeq.current)return
   }
   const scope=[user.id,vid,version.batch_current_id,version.state,version.reviewer_id].join('/')
   const previous=draftBase.current
   if(previous&&(previous.scope!==scope||previous.revision!==version.revision)){
    if(previous.scope===scope&&dirtyRef.current&&!lock.current){
     setError(systemText("计划已在其他页面更新。请核对未保存的数量，放弃修改并刷新后可重新填写。"))
     return
    }
    if(move&&draft.redoHint&&previous.scope===scope&&previous.revision===move.from&&version.revision===move.to){
     setSavedStepsToDraft(depth=>move.direction==='undo'?depth+1:Math.max(0,depth-1))
    }else clearLocalHistory()
   }
   draftBase.current={scope,revision:version.revision}
   loadedPath.current=vid+versionQuery
   setBatch(summary);setVer(version);setVersionId(vid)
   const last=Math.max(1,Math.ceil(version.total/version.page_size))
   if(page>last)setPage(last)
  }catch(e:any){if(seq===requestSeq.current)setError(e.message)}
 }
 useEffect(()=>{
  if(ver?.id===versionId&&loadedPath.current===versionId+versionQuery){
   ++requestSeq.current
   return
  }
  load(undefined,false)
 },[batchId,versionId,versionQuery])
 const editable=ver?.state==='DRAFT'&&ver?.owner===user.id&&batch?.current_id===ver?.id&&canPlan(user.roles)
 const reviewStage=batch?.current_id===ver?.id&&['SUBMITTED','IN_REVIEW'].includes(ver?.state)
 const eligible=reviewStage&&canReview(user.roles)&&ver.owner!==user.id
 const canClaim=eligible&&!ver.reviewer_id
 const reviewing=eligible&&ver.reviewer_id===user.id
 useEffect(()=>{if(filter==='pending'&&ver&&!['SUBMITTED','IN_REVIEW'].includes(ver.state)){setFilter('all');setPage(1)}},[ver?.state])
 const dirty=Object.keys(edits).length>0
 const unsaved=dirty||drawerDirty
 useEffect(()=>{onDirty(unsaved);const unload=(e:BeforeUnloadEvent)=>{if(unsaved){e.preventDefault();e.returnValue=''}};window.addEventListener('beforeunload',unload);return()=>{onDirty(false);window.removeEventListener('beforeunload',unload)}},[unsaved,onDirty])
 async function execute(fn:()=>Promise<any>,message?:string,direction?:HistoryDirection){
  if(lock.current)throw new Error(systemText("操作正在处理"))
  lock.current=true;setBusy(true);setError('');setIssueRows([]);setIssueListOpen(false)
  try{
   const result=await fn()
   if(message)notify(message)
   const move=direction?{direction,from:ver.revision,to:result.revision}:undefined
   await load(result?.version_id||ver.id,true,move)
   onUpdate()
   return result
  }catch(e:any){
   setError(e.message);setIssueRows(e.detail?.issues||[])
   if((reviewStage||!dirty)&&[403,409].includes(e.status)){await load(ver.id);onUpdate()}
   throw e
  }finally{lock.current=false;setBusy(false)}
 }
 async function save(){await execute(()=>api(`/versions/${ver.id}/items`,{revision:ver.revision,changes:Object.entries(edits).map(([id,values])=>({id,values}))},'PATCH'),systemText("修改已保存"));clearLocalHistory()}
 function setNumber(id:string,key:string,value:string){
  const original=ver.items.find((item:any)=>item.id===id)?.input[key]
  const baseline=String(original??'')
  if((edits[id]?.[key]??baseline)===value)return
  if(savedStepsToDraft)clearLocalHistory()
  draft.change(id,key,value,baseline)
 }
 const localUndo=editable?draft.undoHint:null
 const localRedo=editable&&savedStepsToDraft===0?draft.redoHint:null
 const undoHint=localUndo||(!dirty?ver?.undo:null)
 const redoHint=localRedo||(!dirty&&!localUndo?ver?.redo:null)
 const historyLocked=busy||!!dialog||!!detail||drawerDirty||!!pending
 async function replayLatest(direction:HistoryDirection){
  if(lock.current||historyLocked||(!editable&&!reviewing))return
  const local=direction==='undo'?localUndo:localRedo
  if(local){draft.replay(direction);return}
  const hint=direction==='undo'?undoHint:redoHint
  if(dirty||!hint)return
  const message=(direction==='undo'?systemText("已撤销"):systemText("已重做"))+systemText(hint.label)
  try{
   const result=await execute(()=>api(`/versions/${ver.id}/${direction}`,{revision:ver.revision}),message,direction)
   setSelected(new Set<string>(result.affected_ids))
  }catch{ /* execute shows permission and revision conflicts. */ }
 }
 function proceed(action:()=>void){
  if(lock.current)return
  if(dirty)setPending({run:action});else action()
 }
 async function resume(saveFirst:boolean){
  const action=pending?.run
  if(!action||lock.current)return
  if(saveFirst){try{await save()}catch{return}}
  else clearLocalHistory()
  setPending(null);action()
 }
 async function openDetail(row:any){
  setBusy(true);setError('')
  try{
   const [result,current]=await Promise.all([api(`/versions/${ver.id}/selection?q=${encodeURIComponent(q)}&filter=${filter}${tableQuery}`),api(`/versions/${ver.id}/items/${row.id}`)])
   setQueue(result.ids.includes(row.id)?result.ids:[row.id]);setDrawerDirty(false);setDetail(current)
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 async function selectFiltered(){
  const seq=requestSeq.current
  setBusy(true);setError('')
  try{
   const result=await api(`/versions/${ver.id}/selection?q=${encodeURIComponent(q)}&filter=${filter}${tableQuery}`)
   if(seq===requestSeq.current)setSelected(new Set(result.ids))
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 async function openIssue(id:string,ids:string[]){
  const item=await api('/versions/'+ver.id+'/items/'+id)
  setDialog('');setQueue(ids);setDrawerDirty(false);setDetail(item)
 }
 async function takeReview(){
  try{await execute(()=>api('/versions/'+ver.id+'/claim',{revision:ver.revision}),systemText("已领取复审"))}catch{/* execute displays the error */}
 }
 async function transferReview(reviewerId:string){
  await execute(()=>api('/versions/'+ver.id+'/transfer',{revision:ver.revision,reviewer_id:reviewerId}),systemText("复审已转交"))
  setSelected(new Set());setDialog('')
 }
 async function quickDecision(row:any,decision:'APPROVED'|'REJECTED',reason=''){
  const saved=await execute(()=>api('/versions/'+ver.id+'/reviews',{
   revision:ver.revision,ids:[row.id],only_pending:true,decision,reason,
  }))
  notify(saved.count?row.input.material_code+' · '+(decision==='REJECTED'?systemText("不批准"):saved.exception_count?systemText("例外批准"):systemText("已批准")):systemText("该行已有复审决定"))
 }
 function quickActions(row:any){
  if(!reviewing||row.decision)return null
  const code=row.input.material_code
  return <span className="quick-row-actions">
   <button type="button" data-usage-target="approve" className="quick-approve" title={systemText("批准")} aria-label={systemText("批准 ")+code} disabled={busy} onClick={()=>quickDecision(row,'APPROVED').catch(()=>{})}><Check size={16}/></button>
   <button type="button" data-usage-target="reject" className="quick-reject" title={tr('不批准','Reject')} aria-label={systemText("不批准 ")+code} disabled={busy} onClick={()=>quickDecision(row,'REJECTED').catch(()=>{})}><Ban size={16}/></button>
  </span>
 }
 async function openReviewSelection(){
  setBusy(true);setError('')
  try{
   const meta=await api('/versions/'+ver.id+'/review-summary',{ids:[...selected],only_pending:true})
   if(!meta.count){notify(systemText("所选物料已全部复审"));return}
   setReviewMeta(meta);setDialog('review')
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 const position=detail?queue.indexOf(detail.id):-1
 function closeDetail(){setDetail(null);setQueue([]);setDrawerDirty(false)}
 async function advance(target:number){
  const item=await api(`/versions/${ver.id}/items/${queue[target]}`)
  setDrawerDirty(false);setDetail(item)
 }
 async function finishItem(values:any,next:boolean,review:boolean){
  const successor=next&&position+1<queue.length?await api(`/versions/${ver.id}/items/${queue[position+1]}`):null
  if(review){
   const result=await execute(()=>api(`/versions/${ver.id}/reviews`,{revision:ver.revision,ids:[detail.id],...values}))
   if(result.skipped?.length)throw new Error(result.skipped[0].reason)
   notify(result.exception_count?systemText("已保存为例外批准"):systemText("复审决定已保存"))
  }else{
   const {reference,...plan}=values
   const changed=Object.fromEntries(Object.entries(plan).filter(([field,value])=>String(value??'')!==String(detail.input[field]??'')))
   if(Object.keys(changed).length||Object.keys(reference||{}).length)await execute(()=>api(`/versions/${ver.id}/items`,{revision:ver.revision,changes:[{id:detail.id,values:changed,reference}]},'PATCH'),systemText("修改已保存"))
  }
  if(successor){setDrawerDirty(false);setDetail(successor)}else closeDetail()
 }
 async function doExport(scope:string){setExporting(true);setError('');try{const j=await api('/exports',{version_id:ver.id,scope,q,filter,column_filters:tableState.filters,sort_key:tableState.sortKey,sort_direction:tableState.sortDirection});const done=await waitJob(j.id,undefined,'export');const link=document.createElement('a');link.href=done.download_url;link.download=done.filename;link.click();notify(systemText("结果文件已生成"))}catch(e:any){setError(e.message)}finally{setExporting(false)}}
 async function confirmAction(values:any){
    let path='',body:any={revision:ver.revision,...values};let method='POST'
    if(dialog==='reason'){path=`/versions/${ver.id}/items`;body={revision:ver.revision,changes:[...selected].map(id=>({id,values}))};method='PATCH'}
    else if(dialog==='delete'){path=`/versions/${ver.id}/items`;body.ids=[...selected];method='DELETE'}
    else if(dialog==='void')path=`/batches/${batch.id}/void`
    else if(dialog==='review'){path=`/versions/${ver.id}/reviews`;body.ids=[...selected];body.only_pending=true}
    else if(dialog==='rejectPlan')path=`/versions/${ver.id}/finalize`
    else path=`/versions/${ver.id}/${dialog}`
    const r=await execute(()=>api(path,body,method));setDialog('');setSelected(new Set())
    if(dialog==='review'){
     setBulkMode(false)
     const result=[tr(`已保存 ${r.count} 行复审决定`,`Saved decisions for ${r.count} rows`)]
     if(r.exception_count)result.push(tr(`例外批准 ${r.exception_count} 行`,`${r.exception_count} approved by exception`))
     if(r.preserved)result.push(tr(`已有决定 ${r.preserved} 行`,`${r.preserved} existing decisions kept`))
     if(r.skipped?.length){
      result.push(tr(`需单独处理 ${r.skipped.length} 行`,`${r.skipped.length} rows require individual review`))
      setIssueRows(r.skipped.map((item:any)=>({...item,message:item.reason})))
     }
     notify(result.join(' · '))
    }else notify(({submit:systemText("已提交复审"),finalize:systemText("已整单通过"),rejectPlan:systemText("已整单不批准"),return:systemText("已退回并生成新草稿"),reason:systemText("说明已保存"),delete:systemText("已移除所选计划行"),void:systemText("计划已作废")} as any)[dialog]||systemText("复审决定已保存"))

 }
 if(!ver||!batch)return error?<><button className="text-button" onClick={onBack}>{backLabel}</button><Notice message={error} tone="error"/><button className="secondary" onClick={()=>{setError('');load()}}>{systemText("重新读取")}</button></>:<Busy/>
 const counts=ver.summary
 const showReturned=editable&&batch.state==='RETURNED'&&counts.return_requested>0
 const rejectedCount=counts.rejected+counts.return_marked
 const workflowButtons=<>
   {editable&&<button className="primary" disabled={busy||!counts.total} data-usage-target="submit" onClick={()=>proceed(()=>setDialog('submit'))}><Send size={16}/>{systemText("提交复审")}</button>}{canClaim&&<button className="primary" disabled={busy} onClick={takeReview}><Check size={16}/>{systemText("领取复审")}</button>}
   {reviewing&&<><button className="secondary" disabled={busy} data-usage-target="transfer" onClick={()=>setDialog('transfer')}>{systemText("转交复审")}</button>
    {rejectedCount>0
     ?<button className="secondary" disabled={busy} data-usage-target="reject" onClick={()=>setDialog('rejectPlan')}><Ban size={16}/>{systemText("整单不批准")}</button>
     :<button className="primary" disabled={busy||!counts.total} data-usage-target="approve" onClick={()=>setDialog('finalize')}><CheckCheck size={17}/>{systemText("整单通过")}</button>}
    <button className={rejectedCount?'primary':'secondary'} disabled={busy} data-usage-target="return" onClick={()=>setDialog('return')}><RotateCcw size={16}/>{systemText("退回计划")}</button>
   </>}
  </>
 return <div className={"plan-view"+(focus.active?" is-focused":"")}>
  <button className="back-link" disabled={busy} onClick={()=>proceed(onBack)}><ArrowLeft size={15}/>{systemText(backLabel)}</button>
  <div className="page-heading plan-heading"><div><div className="heading-inline"><h1>{batch.title}</h1><Badge value={ver.state} label={reviewStage&&!ver.reviewer_id?systemText("待领取"):planStateLabel(ver.state)}/></div><p><WarehouseLabel code={batch.warehouse} name={batch.warehouse_name}/><span className="separator">/</span>{batch.number}<span className="separator">/</span>{tr(`第 ${ver.seq} 版`, `Version ${ver.seq}`)}<span className="separator">/</span>{batch.owner_name}<span className="separator">/</span>{periodLabel(batch.period,batch.period_info?.label)}{ver.reviewer_name&&<><span className="separator">/</span>{systemText("复审人 ·")} {ver.reviewer_name}</>}</p></div><div className="actions"><button className="secondary" onClick={()=>setHistory(!history)} disabled={busy}><History size={16}/>{systemText("版本记录")}</button><button className="secondary" data-usage-target="export" onClick={()=>proceed(()=>doExport('all'))} disabled={exporting||busy}>{exporting?<RefreshCw size={16} className="spin"/>:<Download size={16}/>}{systemText("导出")}</button>{workflowButtons}</div></div>
  {ver.id===batch.current_id&&batch.state!=='VOID'&&<Stepper current={completedStates.includes(ver.state)?4:ver.state==='DRAFT'?(counts.total?2:1):3}/>}
  {ver.state==='REJECTED'&&<Notice tone="info" message={tr(`本版已整单不批准，全部 ${counts.total} 行均不执行。明细保留各行复审意见。`,`This plan was rejected in full. None of its ${counts.total} rows will proceed. Individual decisions are retained below.`)}/>}
  {ver.state==='PARTIALLY_APPROVED'&&<Notice tone="info" message={systemText("本版已按旧规则结案。明细保留当时的逐行复审意见。")}/>}
  {showReturned&&<Notice message={tr(`${counts.return_requested} 行需修改，已在明细中优先显示。`,`${counts.return_requested} rows need changes and appear first in the table.`)}/>}
  {editable&&batch.state==='RETURNED'&&batch.events?.find((e:any)=>e.action==='退回修改')?.detail.reason&&<Notice raw message={batch.events.find((e:any)=>e.action==='退回修改').detail.reason}/>}
  {error&&<Notice message={error} tone="error"/>}
  {issueRows.length>0&&<div className="issue-list">{(issueListOpen?issueRows:issueRows.slice(0,6)).map((e,i)=><button key={i} disabled={busy} onClick={()=>proceed(()=>{if(e.id){setBusy(true);openIssue(e.id,issueRows.map(row=>row.id).filter(Boolean)).catch(err=>setError(err.message)).finally(()=>setBusy(false))}else{setQ(e.material_code||'');setFilter('all');changeTable(EMPTY_TABLE)}})}><span>{e.material_code}</span>{planMessage(e.message)}</button>)}{issueRows.length>6&&<button className="text-button" onClick={()=>setIssueListOpen(!issueListOpen)}>{issueListOpen?systemText("收起"):tr(`查看全部 ${issueRows.length} 项`,`View all ${issueRows.length} issues`)}</button>}</div>}
  {ver.id!==batch.current_id&&<div className="historical-context"><span>{systemText("正在查看历史版本 ·")} {tr(`第 ${ver.seq} 版`, `Version ${ver.seq}`)}</span><button className="text-button" onClick={()=>selectVersion(batch.current_id)}>{systemText("返回最新版")}</button></div>}
  {history&&<VersionHistory key={ver.id} versions={batch.versions} selected={ver} revision={ver.revision} current={batch.current_id} busy={busy} onSelect={selectVersion} onClose={()=>setHistory(false)}/>}
  <div className="basis-line"><span><span className="live-dot"/> {ver.rule.name}</span><span><DatabaseIcon/> {ver.snapshot?<>{ver.snapshot.name}<small>{systemText("数据日期")} {ver.snapshot.as_of}{counts.plan_reference?' · '+counts.plan_reference+systemText(" 行已维护"):''}</small></>:counts.plan_reference?systemText("本计划基础数据"):counts.total?systemText("待补基础数据"):systemText("待导入计划")}</span>{editable&&<button className="text-button" disabled={busy} onClick={()=>proceed(()=>setDialog('basis'))}>{ver.latest_rule_id!==ver.rule.id?systemText("更换计算依据"):ver.snapshot?systemText("更换仓库数据"):systemText("使用仓库数据")}<SlidersHorizontal size={13}/></button>}<span className="spacer"/>{reviewing?<span className="review-progress">{tr(`已复审 ${counts.reviewed} / ${counts.total} 行`, `Reviewed ${counts.reviewed} of ${counts.total} rows`)}</span>:<span>{ver.id===batch.current_id?systemText("已保存 ")+date(batch.updated_at):systemText("历史版本 · 只读")}</span>}</div>
  <section className={`panel plan-table-panel density-${density}`}><div className="plan-table-header"><div><h2 title={focus.active?batch.title:undefined}>{focus.active?batch.title:reviewing?systemText("核对与复审"):systemText("计划明细")}</h2>{focus.active&&<><WarehouseLabel code={batch.warehouse} name={batch.warehouse_name}/><span className="plan-version-label">{tr(`第 ${ver.seq} 版`, `Version ${ver.seq}`)}</span><Badge value={ver.state} label={canClaim?systemText("待领取"):planStateLabel(ver.state)}/></>}<span>{focus.active&&reviewing?tr(`已复审 ${counts.reviewed}/${counts.total} 行`,`Reviewed ${counts.reviewed}/${counts.total} rows`):tr(`${counts.total} 行物料`,`${counts.total} line items`)}</span></div><div className="actions">{reviewing&&<button className="secondary compact" aria-pressed={bulkMode||selected.size>0} disabled={busy||!ver.total} onClick={()=>selected.size?openReviewSelection():setBulkMode(!bulkMode)}><CheckCheck size={16}/>{systemText("批量复审")}</button>}{editable&&<><button className="text-button" disabled={busy} data-usage-target="create" onClick={()=>proceed(()=>setDialog('add'))}><Plus size={15}/>{systemText("添加物料")}</button><button className="secondary compact" disabled={busy} data-usage-target="import" onClick={()=>proceed(()=>setDialog('import'))}><Upload size={15}/>{systemText("导入计划")}</button></>}{focus.active&&workflowButtons}{(editable||reviewing)&&<PlanHistoryControls undo={undoHint} redo={redoHint} disabled={historyLocked} onAction={replayLatest}/>}<FocusControls focus={focus}/></div></div>
   {editable&&counts.total>0&&<DraftIssues key={ver.id} versionId={ver.id} revision={ver.revision} edits={edits} busy={busy}
    onBasis={()=>proceed(()=>setDialog('basis'))}
    onRow={(id,ids)=>proceed(()=>{setBusy(true);openIssue(id,ids).catch(e=>setError(e.message)).finally(()=>setBusy(false))})}/>}
   <div className="filter-tabs" data-usage-target="filter">{[['all',systemText("全部"),counts.total],...(showReturned?[['returned',systemText("需修改"),counts.return_requested]]:[]),...(counts.return_marked>0?[['return_marked',systemText("退回修改"),counts.return_marked]]:[]),...(counts.rejected>0?[['rejected',systemText("不批准"),counts.rejected]]:[]),['attention',systemText("需关注"),counts.attention],...(ver.rule?.model==='V3'?[['turnover',systemText("周转预警"),counts.turnover||0]]:[]),...(['V2','V3'].includes(ver.rule?.model)?[['delay',systemText("建议延迟"),counts.delay||0]]:[]),['WITHIN',systemText("合理"),counts.WITHIN],['BELOW',systemText("偏少"),counts.BELOW],['ABOVE',systemText("偏多"),counts.ABOVE],['MANUAL',systemText("人工判断"),counts.MANUAL],['EXEMPT',systemText("免数量审核"),counts.EXEMPT],[reviewStage?'pending':'unexplained',reviewStage?systemText("未复审"):systemText("资料待补"),reviewStage?counts.total-counts.reviewed:counts.unexplained]].map(([key,name,count])=><button disabled={busy} key={String(key)} aria-pressed={filter===key} className={filter===key?'active':''} onClick={()=>proceed(()=>{setFilter(String(key));setPage(1);setSelected(new Set())})}>{name}<span>{count}</span></button>)}</div>
   <div className="list-toolbar"><label className="search"><Search size={16}/><input aria-label={systemText("搜索物料号或名称")} value={q} disabled={busy} onChange={e=>{const value=e.target.value;proceed(()=>{setQ(value);setPage(1);setSelected(new Set())})}} placeholder={systemText("搜索物料号或名称")}/></label><select aria-label={systemText("更多物料筛选")} disabled={busy} value={['ERROR','air','modified','abc:A','abc:B','abc:C'].includes(filter)?filter:''} onChange={e=>{const value=e.target.value;proceed(()=>{setFilter(value||'all');setPage(1);setSelected(new Set())})}}><option value="">{systemText("更多筛选")}</option><option value="ERROR">{systemText("数据错误")}</option><option value="air">{systemText("包含空运")}</option><option value="modified">{systemText("已修改")}</option><option value="abc:A">{systemText("物料分类 A")}</option><option value="abc:B">{systemText("物料分类 B")}</option><option value="abc:C">{systemText("物料分类 C")}</option></select><TableViewControls columns={visibleCols} onChange={setVisibleCols} density={density} onDensityChange={setDensity} disabled={busy} availableColumns={ver.columns.map((c:any)=>c.key)}/><ColumnPicker disabled={busy} columns={ver.columns||[]} visible={visibleCols} onChange={setVisibleCols}/><span className="spacer"/><button className="text-button" disabled={busy||exporting} data-usage-target="export" onClick={()=>proceed(()=>doExport('filtered'))}><Download size={14}/>{systemText("导出筛选")}</button></div>
   {(editable||reviewing)&&(selected.size>0||(reviewing&&bulkMode))&&<div className="selection-bar"><strong>{selected.size?tr(`已选 ${selected.size} 行`,`${selected.size} rows selected`):systemText("勾选要复审的物料")}</strong><button className="text-button" disabled={busy||!ver.total} onClick={selectFiltered}>{systemText("选择全部筛选结果 (")}{ver.total})</button><span className="spacer"/>{editable&&<><button disabled={busy} onClick={()=>proceed(()=>setDialog('reason'))}>{systemText("批量填写说明")}</button><button disabled={busy} onClick={()=>proceed(()=>setDialog('delete'))}>{systemText("移除")}</button></>}{reviewing&&<><button disabled={busy||!selected.size} onClick={openReviewSelection}>{systemText("复审所选")}</button></>}<button aria-label={systemText("取消选择")} onClick={()=>{setSelected(new Set());setBulkMode(false)}}><X size={15}/></button></div>}
   <ReviewTable layoutOwner={user.id} ver={ver} visible={visibleCols} state={tableState} onState={next=>proceed(()=>changeTable(next))} editable={editable} reviewing={reviewing} dirty={false} busy={busy} selected={selected} setSelected={setSelected} edits={edits} setNumber={setNumber} onDetail={row=>proceed(()=>openDetail(row))} quickActions={quickActions}/>
   {editable&&!counts.total&&<div className="empty-plan-import"><button className="primary" data-usage-target="import" onClick={()=>setDialog('import')}><Upload size={16}/>{systemText("导入计划")}</button></div>}
   <div className="table-footer"><label className="page-capacity">{systemText("每页")}<select aria-label={systemText("每页显示行数")} disabled={busy} value={capacity} onChange={e=>{const value=e.target.value;proceed(()=>changeCapacity(value))}}>{pageCapacities.map(n=><option key={n} value={n}>{n==='all'?systemText("全部"):n+systemText(" 行")}</option>)}</select></label><span>{systemText("显示")} {ver.total?((page-1)*ver.page_size+1):0}–{Math.min(page*ver.page_size,ver.total)} / {ver.total} {systemText("行")}</span><span className="spacer"/><button className="icon-button" aria-label={systemText("上一页")} disabled={busy||page<=1} onClick={()=>proceed(()=>setPage(page-1))}><ChevronLeft size={17}/></button><span>{page} / {Math.max(1,Math.ceil(ver.total/ver.page_size))}</span><button className="icon-button" aria-label={systemText("下一页")} disabled={busy||page*ver.page_size>=ver.total} onClick={()=>proceed(()=>setPage(page+1))}><ChevronRight size={17}/></button></div>
  </section>
  <div className="plan-bottom-note"><span className="spacer"/>{canPlan(user.roles)&&<button className="text-button" disabled={busy} onClick={()=>proceed(()=>setDialog('copy'))}><Copy size={14}/>{systemText("复制为新计划")}</button>}{editable&&<button className="text-button" disabled={busy} onClick={()=>proceed(()=>setDialog('void'))}>{systemText("作废计划")}</button>}</div>
  {dirty&&<div className="save-bar" data-usage-target="save"><span><span className="unsaved-dot"/>{Object.keys(edits).length} {systemText("行修改尚未保存")}</span><span className="spacer"/><button className="secondary" disabled={busy} onClick={draft.undoAll}>{systemText("撤销本次修改")}</button><button className="primary" disabled={busy} onClick={()=>save().catch(()=>{})}><Save size={16}/>{busy?systemText("正在保存…"):systemText("保存修改")}</button></div>}
  {pending&&<Modal title={tr(`保存这 ${Object.keys(edits).length} 行修改？`,`Save changes to ${Object.keys(edits).length} rows?`)} onClose={()=>{if(!busy)setPending(null)}}><div className="modal-body">{error&&<Notice message={error} tone="error"/>}<div className="modal-actions"><button className="text-button" disabled={busy} onClick={()=>setPending(null)}>{systemText("继续编辑")}</button><button className="secondary" disabled={busy} onClick={()=>resume(false)}>{systemText("放弃并继续")}</button><button className="primary" disabled={busy} onClick={()=>resume(true)}>{busy?systemText("正在保存…"):systemText("保存并继续")}</button></div></div></Modal>}
  {detail&&<ItemDrawer key={detail.id} row={detail} ver={ver} editable={editable} reviewing={reviewing} position={position} total={queue.length} onMove={advance} onDirty={setDrawerDirty} onClose={closeDetail} onSave={(v,next)=>finishItem(v,next,false)} onReview={(v,next)=>finishItem(v,next,true)}/>}
  {['return','review','reason','delete','void'].includes(dialog)&&<ActionDialog kind={dialog} reviewMeta={reviewMeta} count={dialog==='return'?rejectedCount:selected.size} onClose={()=>setDialog('')} onConfirm={confirmAction}/>}
  {dialog==='transfer'&&reviewing&&<ReviewTransfer versionId={ver.id} onClose={()=>setDialog('')} onTransfer={transferReview}/>}
  {['submit','finalize','rejectPlan'].includes(dialog)&&<ConfirmationDialog kind={dialog} ver={ver} onChanged={()=>{setDialog('');load(ver.id)}} onItem={openIssue} onClose={()=>setDialog('')} onConfirm={confirmAction}/>}
  {dialog==='add'&&<AddMaterial ver={ver} onClose={()=>setDialog('')} onAdd={async item=>{await execute(()=>api(`/versions/${ver.id}/items`,{revision:ver.revision,items:[item]}),systemText("物料已添加"));setDialog('')}}/>}
  {dialog==='import'&&<ImportPlan warehouse={batch.warehouse} legacyPeriod={batch.period_info?.kind==='legacy'} ver={ver} onClose={()=>setDialog('')} onDone={async()=>{setDialog('');await load();onUpdate();notify(systemText("计划已导入，请开始自审"))}}/>}
  {dialog==='copy'&&<CopyPlan batch={batch} version={ver} onClose={()=>setDialog('')} onCreated={id=>{setDialog('');onUpdate();onOpenBatch(id);notify(systemText("已创建计划副本"))}}/>}
  {dialog==='basis'&&<BasisDialog warehouse={batch.warehouse} ver={ver} onClose={()=>setDialog('')} onDone={async()=>{setDialog('');await load();onUpdate();notify(systemText("计算依据已更新"))}}/>}
 </div>
}

function DatabaseIcon(){return <FileSpreadsheet size={14}/>}


function ReasonOptions({current}:{current?:string}){
 return <>{current&&!reasonLabels.has(current)&&<option value={current}>{current}</option>}
  {Array.from(reasonLabels,([code])=><option key={code} value={code}>{reasonLabel(code)}</option>)}</>
}

function adjustmentValue(key:string, value:unknown){
 if(key==='monthly_sales'&&value&&typeof value==='object')return Object.values(value).map(v=>v??'—').join(' / ')
 if(key==='is_key_model'&&typeof value==='boolean')return value?systemText("是"):systemText("否")
 const text=String(value??systemText("未填写"))
 return key==='reason_code'?reasonLabel(text):text
}

function ItemDrawer({row,ver,editable,reviewing,position,total,onMove,onDirty,onClose,onSave,onReview}:{
 row:any;ver:any;editable:boolean;reviewing:boolean;position:number;total:number
 onMove:(index:number)=>Promise<void>;onDirty:(v:boolean)=>void;onClose:()=>void
 onSave:(v:any,next:boolean)=>Promise<void>;onReview:(v:any,next:boolean)=>Promise<void>
}){
 const i=row.input,r=row.result
 const initial={sea_plan_qty:i.sea_plan_qty??'',air_plan_qty:i.air_plan_qty??'',reason_code:i.reason_code||'',reason:i.reason||'',air_reason:i.air_reason||''}
 const [tab,setTab]=useState('action'),[values,setValues]=useState(initial),[busy,setBusy]=useState(false),[error,setError]=useState(''),[reviewDirty,setReviewDirty]=useState(false)
 const [reference,setReference]=useState<Record<string,string|string[]>>({})
 const dirty=reviewDirty||Object.keys(reference).length>0||Object.keys(initial).some(k=>String(values[k as keyof typeof values])!==String(initial[k as keyof typeof initial]))
 useEffect(()=>{onDirty(dirty);return()=>onDirty(false)},[dirty,onDirty])
 function mayLeave(){return !busy&&(!dirty||window.confirm(systemText("放弃本条未保存的修改？")))}
 function close(){if(mayLeave())onClose()}
 const drawerRef=useDialog(close)
 async function run(action:()=>Promise<void>){
  if(busy)return
  setBusy(true);setError('')
  try{await action()}catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 function move(index:number){if(mayLeave())void run(()=>onMove(index))}
 function save(e:FormEvent){e.preventDefault();const next=((e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement)?.value==='next';void run(()=>onSave({...values,reference},next))}
 return createPortal(<div className="drawer-backdrop" onMouseDown={e=>e.target===e.currentTarget&&close()}><aside ref={drawerRef} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-label={systemText("物料详情 ")+i.material_code}><div className="drawer-head"><div><span className="material-code-value">{i.material_code}</span><h2>{i.material_name||'—'}</h2><span>{i.material_abc||systemText("未分类")}</span></div><button className="icon-button" disabled={busy} onClick={close} aria-label={systemText("关闭物料详情")}><X size={21}/></button></div>
 <div className="drawer-queue"><button className="text-button" disabled={busy||position<=0} onClick={()=>move(position-1)}><ChevronLeft size={15}/>{systemText("上一条")}</button><span>{position+1} / {total}</span><button className="text-button" disabled={busy||position+1>=total} onClick={()=>move(position+1)}>{systemText("下一条")}<ChevronRight size={15}/></button></div>
 <div className="drawer-tabs"><button disabled={busy} aria-pressed={tab==='action'} className={tab==='action'?'active':''} onClick={()=>setTab('action')}>{systemText("计划与处理")}</button><button disabled={busy} aria-pressed={tab==='reference'} className={tab==='reference'?'active':''} onClick={()=>setTab('reference')}>{systemText("基础数据")}</button><button disabled={busy} aria-pressed={tab==='evidence'} className={tab==='evidence'?'active':''} onClick={()=>setTab('evidence')}>{systemText("计算依据")}</button></div><div className="drawer-body">
  {error&&<Notice message={error} tone="error"/>}<div className="drawer-result"><Badge value={['ERROR','PENDING'].includes(r.data_status)?r.data_status:r.review_mode==='AUTO'?r.quantity_status:r.review_mode}/>{!r.basis_pending&&<><span>{systemText("未来库存")} <b>{fmt(r.future_qty)}</b></span><span>{systemText("合理区间")} <b>{fmt(r.lower)} — {fmt(r.upper)}</b></span></>}</div>
  {row.submission_override&&(!row.submission_override.mode||row.submission_override.reason)&&<Notice message={systemText("提交备注 · ")+row.submission_override.user_name+'：'+row.submission_override.reason}/> }
  {row.decision?.forced&&<Notice message={systemText("例外终审 · ")+row.decision.reviewer_name+'：'+row.decision.reason}/>}
  {r.errors.map((e:any,n:number)=><Notice key={n} message={planMessage(e.message)} tone="error"/>)}
  {r.turnover_warning&&<div className="advice-box exception"><strong>{planMessage(r.turnover_warning)}</strong><p>{systemText("补货后可用")} {fmt(r.future_days)} {systemText("天。")}</p></div>}
  {r.delay_replenishment&&<div className="advice-box exception"><strong>{systemText("建议延迟补货")}</strong><p>{r.review_mode==='EXEMPT'?tr(`近半年无销量，净库存 ${fmt(i.net_supply_before_plan)} 件。`,`No sales in six months. Net stock is ${fmt(i.net_supply_before_plan)} units.`):tr(`在库周转 ${fmt(r.on_hand_months)} 个月，净库存周转 ${fmt(Number(r.pipeline_days)/30)} 个月。`,`On-hand cover is ${fmt(r.on_hand_months)} months. Net stock cover is ${fmt(Number(r.pipeline_days)/30)} months.`)}</p></div>}
  {r.manual_flags.length>0&&<div className="flag-list">{r.manual_flags.map((f:string)=><span key={f}><AlertCircle size={14}/>{flagLabels[f]}</span>)}</div>}
  <div hidden={tab!=='action'} inert={busy||undefined}>
   {row.adjustment&&<details className="adjustment"><summary>{systemText("最近一次调整 ·")} {date(row.adjustment.at)}</summary>{Object.entries(row.adjustment.after).filter(([key])=>key!=='month_labels').map(([key,val])=><p key={key}>{({sea_plan_qty:systemText("海运"),air_plan_qty:systemText("空运"),reason:systemText("说明"),reason_code:systemText("原因类别"),air_reason:systemText("空运说明")} as any)[key]||systemText(referenceLabels[key]||key)}：{adjustmentValue(key,row.adjustment.before[key])} → {adjustmentValue(key,val)}</p>)}{row.adjustment.review_reason&&<p>{systemText("数量已调整，请复核原说明是否仍适用。")}</p>}</details>}
   {r.review_mode==='AUTO'&&r.quantity_status!=='UNAVAILABLE'&&<div className={'advice-box '+((r.quantity_status!=='WITHIN'||r.sea_feasible===false)?'exception':'')}><strong>{r.quantity_status==='WITHIN'?systemText("计划数量在合理区间内"):r.sea_feasible===false?systemText("已有供给需要进一步核对"):r.quantity_status==='BELOW'?systemText("建议适当增加海运计划"):systemText("建议适当减少海运计划")}</strong><p>{r.sea_feasible===false?tr(`本次海运即使减到 0，仍有 ${fmt(r.residual_excess)} 件超出库存上限。`,`Even with no sea freight, stock exceeds the maximum by ${fmt(r.residual_excess)} units.`):r.sea_feasible?tr(`海运可行范围为 ${fmt(r.sea_lower)}–${fmt(r.sea_upper)} 件，建议本次海运 ${fmt(r.suggested_sea_qty)} 件。`,`Sea freight range: ${fmt(r.sea_lower)}–${fmt(r.sea_upper)} units. Suggested quantity: ${fmt(r.suggested_sea_qty)}.`):planMessage(r.explanation)}</p>{editable&&r.sea_feasible&&r.quantity_status!=='WITHIN'&&<button type="button" className="text-button" onClick={()=>setValues({...values,sea_plan_qty:r.suggested_sea_qty})}>{systemText("填入建议海运量")} <ArrowRight size={13}/></button>}</div>}
   {!r.basis_pending&&r.data_status!=='ERROR'&&r.review_mode!=='AUTO'&&<p className="explanation">{r.review_mode==='EXEMPT'?systemText("本物料免数量审核。"):systemText("按实际市场需求判断，可补充需求依据。")}</p>}
   {editable?<form onSubmit={save}><div className="form-grid"><label>{systemText("本次海运")}<input type="number" min="0" step={i.quantity_step||1} value={values.sea_plan_qty} onChange={e=>setValues({...values,sea_plan_qty:e.target.value})}/></label><label>{systemText("本次空运")}<input type="number" min="0" step={i.quantity_step||1} value={values.air_plan_qty} onChange={e=>setValues({...values,air_plan_qty:e.target.value})}/></label></div><label>{systemText("原因类别")}<select value={values.reason_code} onChange={e=>setValues({...values,reason_code:e.target.value})}><option value="">{systemText("选填")}</option><ReasonOptions current={values.reason_code}/></select></label><label>{systemText("计划说明")}<textarea aria-label={systemText("计划说明")} rows={4} value={values.reason} onChange={e=>setValues({...values,reason:e.target.value})} maxLength={2000}/></label>{Number(values.air_plan_qty)>0&&<label>{systemText("空运必要性")}<textarea rows={3} value={values.air_reason} onChange={e=>setValues({...values,air_reason:e.target.value})} placeholder={systemText("选填")}/></label>}<div className="modal-actions"><button className={position+1<total?'secondary':'primary'} disabled={busy}><Save size={16}/>{systemText("保存并关闭")}</button>{position+1<total&&<button className="primary" value="next" disabled={busy}>{systemText("保存并下一条")}<ChevronRight size={16}/></button>}</div></form>:<div className="read-reasons"><h3>{systemText("计划员说明")}</h3>{i.reason_code&&<p>{reasonLabel(i.reason_code)}</p>}<p>{i.reason||systemText("未填写例外说明")}</p>{i.air_reason&&<><h3>{systemText("空运必要性")}</h3><p>{i.air_reason}</p></>}</div>}
   {editable&&row.return_requested&&row.return_reason&&<Notice message={systemText("本行退回原因 · ")+row.return_reason}/>}
   {editable&&row.previous_decision&&<details className="adjustment"><summary>{systemText("上版复审意见")}</summary><Badge value={row.previous_decision.status}/>{row.previous_decision.reason_code&&<p>{reasonLabel(row.previous_decision.reason_code)}</p>}{row.previous_decision.reason&&<p>{row.previous_decision.reason}</p>}<small>{row.previous_decision.reviewer_name} · {date(row.previous_decision.reviewed_at)}</small></details>}
   {row.decision&&<div className={'decision-box '+row.decision.status.toLowerCase()}><Badge value={row.decision.status}/>{row.decision.reason_code&&<p>{reasonLabel(row.decision.reason_code)}</p>}{row.decision.reason&&<p>{row.decision.reason}</p>}<small>{row.decision.reviewer_name} · {date(row.decision.reviewed_at)}</small></div>}

   {reviewing&&<ReviewForm previous={row.decision} flags={r.manual_flags} exceptionCount={row.approval_status==='EXCEPTION_APPROVED'?1:0} hasNext={position+1<total} onDirty={setReviewDirty} onConfirm={(v,next)=>run(()=>onReview(v,next))}/>}
  </div>{tab==='reference'&&<form onSubmit={save}><PlanReference requireSales={!!ver.rule.v3_revision} input={i} basis={r.master_basis} changes={reference} onChange={setReference} readOnly={!editable||busy} componentNet={ver.snapshot?.net_mode==='COMPONENTS'}/>{editable&&<div className="modal-actions"><button className="primary" disabled={busy}><Save size={16}/>{systemText("保存并重算")}</button></div>}</form>}
  {tab==='evidence'&&r.basis_pending&&<p className="muted">{systemText("补充本行基础数据后可查看计算结果。")}</p>}
  {tab==='evidence'&&!r.basis_pending&&<><h3>{systemText("本行计算过程")}</h3><div className="formula-chain"><div><span>01</span><section><strong>{systemText("审核前净额")}</strong><b>{fmt(i.net_supply_before_plan)}</b><p>{ver.snapshot?.basis||systemText("本次计划提供的库存、在途、在订减需求净额")}</p></section></div><div><span>02</span><section><strong>{systemText("本次下单后的未来库存")}</strong><p className="formula">{ver.rule?.model==='V3'&&!ver.rule.v3_revision?<>{fmt(i.on_hand_qty)} + {fmt(i.net_supply_before_plan)} + {fmt(i.sea_plan_qty)}</>:<>{fmt(i.net_supply_before_plan)} + {fmt(i.sea_plan_qty)} + {fmt(i.air_plan_qty)}</>} = <b>{fmt(r.future_qty)}</b></p><small>{ver.rule?.model==='V3'&&!ver.rule.v3_revision?systemText("在库数量 + 审核前净额 + 海运"):systemText("审核前净额 + 海运 + 空运")}</small></section></div><div><span>03</span><section><strong>{r.rule_id||systemText("人工判断")}</strong><p>{planMessage(r.explanation)}</p><dl><dt>{systemText("更换率目标库存")}</dt><dd>{fmt(i.replacement_target)}</dd><dt>{systemText("销量目标库存")}</dt><dd>{fmt(i.sales_target)}</dd><dt>{systemText("月均销量较大值 m")}</dt><dd>{fmt(r.m)}</dd><dt>{systemText("装车量")}</dt><dd>{fmt(i.fleet_qty)}</dd>{'advice' in r&&<><dt>{systemText("备件保有量")}</dt><dd>{fmt(i.vehicle_parc)}</dd><dt>{systemText("车型")}</dt><dd>{i.vehicle_model||'—'}</dd><dt>{systemText("在库周转（月）")}</dt><dd>{r.m==='0'?systemText("无销量"):fmt(r.on_hand_months)}</dd><dt>{systemText("补货后周转（天）")}</dt><dd>{r.m==='0'?systemText("无销量"):fmt(r.future_days)}</dd><dt>{systemText("审批建议")}</dt><dd>{planMessage(r.advice)}</dd>{i.source_note&&<><dt>{systemText("备注")}</dt><dd>{i.source_note}</dd></>}</>}<dt>{systemText("稳态更换率")}</dt><dd>{i.replacement_rate==null?systemText("未提供"):fmt(Number(i.replacement_rate)*100)+'%'}</dd><dt>{systemText("重点车型")}</dt><dd>{i.is_key_model===true?systemText("是"):i.is_key_model===false?systemText("否"):systemText("未提供")}</dd><dt>{systemText("原始区间")}</dt><dd>{fmt(r.lower_raw)} — {fmt(r.upper_raw)}</dd><dt>{systemText("取整后区间")}</dt><dd>{fmt(r.lower)} — {fmt(r.upper)}</dd></dl></section></div></div><details className="evidence-details"><summary>{systemText("命中关键词与分类")}</summary>{Object.entries(r.matched_keywords).map(([group,words]:[string,any])=>words.length>0&&<p key={group}>{({small:systemText("小件"),maintenance:systemText("保养件"),dangerous:systemText("危包"),manual:systemText("用品精品"),no_stock:systemText("不备货")} as any)[group]}：{words.join(tr('、', ', '))}</p>)}{r.override&&<p>{systemText("按当前规则版本覆盖为：")}{r.override}</p>}</details><details className="evidence-details"><summary>{systemText("数据来源与审核参数")}</summary><p>{i.source?.file&&[i.source.file,i.source.sheet,tr(`第 ${i.source.row} 行`,`row ${i.source.row}`)].join(' / ')}</p><p>{i.reference_origin==='planner'?systemText("计划员已维护本行基础数据"):ver.snapshot?.name||systemText("基础数据来自本次计划")}</p><p>{systemText("规则：")}{ver.rule.name}</p>{i.plan_source&&<p>{systemText("计划来源：")}{i.plan_source.file} / {i.plan_source.sheet} / {tr(`第 ${i.plan_source.row} 行`,`row ${i.plan_source.row}`)}</p>}<small>{r.precision_version}</small><dl>{Object.entries(ver.rule.params).map(([key,val])=><div className="parameter-evidence" key={key}><dt>{key}</dt><dd>{fmt(val)}</dd></div>)}</dl></details></>}
 </div></aside></div>,document.body)
}

function ReviewForm({flags,exceptionCount,onConfirm,onDirty,hasNext=false,previous}:{previous?:any;flags:string[];exceptionCount:number;onDirty?:(v:boolean)=>void;hasNext?:boolean;onConfirm:(v:any,next:boolean)=>Promise<void>}){
 const initialDecision=['REJECTED','RETURNED'].includes(previous?.status)?'REJECTED':'APPROVED'
 const [decision,setDecision]=useState(initialDecision),[reasonCode,setReasonCode]=useState(previous?.reason_code||''),[reason,setReason]=useState(previous?.reason||'')
 const [acks,setAcks]=useState<string[]>(previous?.ack_flags||[]),[air,setAir]=useState(!!previous?.air_confirmed),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const dirty=decision!==initialDecision||reasonCode!==(previous?.reason_code||'')||reason!==(previous?.reason||'')||
  air!==!!previous?.air_confirmed||acks.length!==(previous?.ack_flags?.length||0)||acks.some(f=>!previous?.ack_flags?.includes(f))
 useEffect(()=>{onDirty?.(dirty);return()=>onDirty?.(false)},[dirty,onDirty])
 const rejected=decision==='REJECTED'
 async function confirm(e:FormEvent){
  e.preventDefault();if(busy)return
  const next=((e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement)?.value==='next'
  setBusy(true);setError('')
  try{await onConfirm({decision,reason:reason.trim(),reason_code:!rejected&&exceptionCount?reasonCode:'',ack_flags:rejected?[]:acks,air_confirmed:!rejected&&air},next)}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 return <form data-usage-target="save" className="review-form" onSubmit={confirm}>
  {error&&<Notice message={error} tone="error"/>}
  {flags.length>0&&<p className="muted">{flags.map(f=>flagLabels[f]||f).join(' · ')}</p>}
  <fieldset className="review-outcomes"><legend>{systemText("本次决定")}</legend><div>
   {[['APPROVED',systemText("批准")],['REJECTED',tr('不批准','Reject')]].map(([value,label])=>
    <label key={value} className={decision===value?'chosen':''}><input type="radio" name="review-outcome" value={value} checked={decision===value} onChange={()=>{setDecision(value);setError('')}}/>{label}</label>)}
  </div></fieldset>
  {!rejected&&exceptionCount>0&&<p className="muted">{systemText("批准后，")}{exceptionCount} {systemText("行将记为例外批准。")}</p>}
  {rejected
   ?<label>{systemText("不批准原因（选填）")}<textarea maxLength={2000} rows={2} value={reason} onChange={e=>setReason(e.target.value)}/></label>
   :<details open={previous?true:undefined}><summary>{systemText("补充复审记录（选填）")}</summary>
    {exceptionCount>0&&<label>{systemText("原因类别")}<select value={reasonCode} onChange={e=>setReasonCode(e.target.value)}><option value="">{systemText("选填")}</option><ReasonOptions current={reasonCode}/></select></label>}
    {flags.filter(f=>f!=='AIR').map(f=><label key={f} className="check-row"><input type="checkbox" checked={acks.includes(f)} onChange={e=>setAcks(e.target.checked?[...acks,f]:acks.filter(x=>x!==f))}/><span>{systemText("已核对")} {flagLabels[f]}</span></label>)}
    {flags.includes('AIR')&&<label className="check-row"><input type="checkbox" checked={air} onChange={e=>setAir(e.target.checked)}/><span>{systemText("已单独确认空运必要性")}</span></label>}
    <label>{systemText("复审备注")}<textarea aria-label={systemText("复审备注")} maxLength={2000} rows={2} value={reason} onChange={e=>setReason(e.target.value)}/></label>
   </details>}
  <div className="modal-actions"><button className={hasNext?'secondary':'primary'} disabled={busy}><Check size={16}/>{systemText("保存决定")}</button>{hasNext&&<button className="primary" disabled={busy} value="next">{systemText("保存并下一条")}<ChevronRight size={16}/></button>}</div>
 </form>
}

function ActionDialog({kind,count,reviewMeta,onClose,onConfirm}:{kind:string;reviewMeta:any;count:number;onClose:()=>void;onConfirm:(v:any)=>Promise<void>}){
 const [text,setText]=useState(''),[code,setCode]=useState(''),[airReason,setAirReason]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const [reviewDirty,setReviewDirty]=useState(false)
 const close=useFormExit(!!(text||code||airReason||reviewDirty),busy,onClose)
 const changes=Object.fromEntries(Object.entries({reason:text.trim(),reason_code:code,air_reason:airReason.trim()}).filter(([,value])=>value!==''))
 const canSave=kind!=='reason'||Object.keys(changes).length>0
 const names:Record<string,string>={return:systemText("退回计划"),review:tr(`复审所选 ${count} 行`,`Review ${count} selected rows`),reason:systemText("批量填写说明"),delete:systemText("移除所选计划行"),void:systemText("作废计划")}
 return <Modal title={names[kind]} onClose={close}><div className="modal-body" inert={busy||undefined}>{error&&<Notice message={error} tone="error"/>}{kind==='review'?<><p className="muted">{systemText("待复审")} {reviewMeta.count} {systemText("行")}{reviewMeta.preserved>0&&tr(` · 已有决定 ${reviewMeta.preserved} 行`,` · ${reviewMeta.preserved} decisions already recorded`)}</p>{(reviewMeta.errors>0||reviewMeta.delayed>0)&&<Notice message={[reviewMeta.errors>0&&(systemText("数据错误 ")+reviewMeta.errors+systemText(" 行")),reviewMeta.delayed>0&&(systemText("建议延迟补货 ")+reviewMeta.delayed+systemText(" 行"))].filter(Boolean).join(' · ')}/>}<ReviewForm flags={reviewMeta.flags} exceptionCount={reviewMeta.exception_count} onDirty={setReviewDirty} onConfirm={async v=>{setBusy(true);try{await onConfirm(v)}finally{setBusy(false)}}}/></>:<form onSubmit={async e=>{e.preventDefault();if(!canSave||busy)return;setBusy(true);try{await onConfirm(kind==='reason'?changes:{reason:text.trim()})}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>
  
  {kind==='return'&&<p>{systemText("退回后，计划员会收到整份计划，并在新草稿中修改。")}{count>0&&<>{count} {systemText("行不批准将排在新草稿最前面。")}</>}{systemText("已批准的物料保留决定，修改后重新复审。")}</p>}
  {kind==='void'&&<p>{systemText("确认作废这份计划？作废后无法继续提交。")}</p>}
  {kind==='delete'&&<p>{systemText("将从当前草稿移除")} {count} {systemText("行物料。")}</p>}
  {kind==='reason'&&<><p>{systemText("更新所选")} {count} {systemText("行，留空的字段保留原值。")}</p><label>{systemText("原因类别")}<select value={code} onChange={e=>setCode(e.target.value)}><option value="">{systemText("选填")}</option><ReasonOptions/></select></label></>}
  {['return','void','reason'].includes(kind)&&<label>{kind==='return'?systemText("整份计划备注（选填）"):kind==='void'?systemText("作废原因（选填）"):systemText("计划说明（选填）")}<textarea rows={4} value={text} onChange={e=>setText(e.target.value)} maxLength={2000}/></label>}
  {kind==='reason'&&<label>{systemText("空运说明（仅在需要统一补充时填写）")}<textarea rows={2} value={airReason} onChange={e=>setAirReason(e.target.value)}/></label>}
  <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>{systemText("返回")}</button><button className="primary" disabled={busy||!canSave}>{busy?systemText("正在处理…"):systemText("确认")}</button></div>
 </form>}</div></Modal>
}

function AddMaterial({ver,onClose,onAdd}:{ver:any;onClose:()=>void;onAdd:(v:any)=>Promise<void>}){
 const [q,setQ]=useState(''),[rows,setRows]=useState<any[]>([]),[code,setCode]=useState(''),[name,setName]=useState(''),[sea,setSea]=useState('0'),[air,setAir]=useState('0')
 const [reference,setReference]=useState<Record<string,string|string[]>>({})
 const snapshotId=ver.snapshot?.id
 const [match,setMatch]=useState<{code:string;basis:any}|null>(null)
 const key=code.trim(), basis=match?.code===key?match?.basis:null
 useEffect(()=>{
  if(!key||snapshotId||!ver.rule.has_material_basis)return
  let active=true
  const timer=window.setTimeout(()=>api('/versions/'+ver.id+'/material-basis?code='+encodeURIComponent(key))
   .then(data=>{if(active)setMatch(data)}).catch(e=>{if(active)setError(e.message)}),180)
  return()=>{active=false;window.clearTimeout(timer)}
 },[key,snapshotId,ver.id,ver.rule.has_material_basis])
 const [error,setError]=useState(''),[busy,setBusy]=useState(false)
 const close=useFormExit(!!code||!!name||Object.keys(reference).length>0||sea!=='0'||air!=='0',busy,onClose)
 useEffect(()=>{
  let active=true
  if(!snapshotId)return
  api('/snapshots/'+snapshotId+'/materials?q='+encodeURIComponent(q)).then(data=>{if(active)setRows(data)}).catch(e=>{if(active)setError(e.message)})
  return()=>{active=false}
 },[q,snapshotId])
 async function add(e:FormEvent){
  e.preventDefault();setBusy(true);setError('')
  const source=Object.fromEntries(Object.entries(reference).filter(([k])=>!Object.hasOwn(basis?.values||{},k)))
  try{await onAdd({material_code:code.trim(),reference:source,...(!snapshotId&&!basis?.values.material_name&&name.trim()?{material_name:name.trim()}:{}),sea_plan_qty:sea,air_plan_qty:air})}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 return <Modal title={snapshotId?systemText("从快照添加物料"):systemText("添加物料")} onClose={close}><form className="modal-body" onSubmit={add}>
  {error&&<Notice message={error} tone="error"/>}
  {snapshotId?<><label>{systemText("搜索物料")}<input disabled={busy} value={q} onChange={e=>{setQ(e.target.value);setCode('')}} placeholder={systemText("物料号或名称")}/></label>
  <label>{systemText("物料")}<select disabled={busy} required value={code} onChange={e=>{setCode(e.target.value);setReference({})}}><option value="">{systemText("请选择物料")}</option>{rows.map(r=><option key={r.material_code} value={r.material_code}>{r.material_code} · {r.material_name}</option>)}</select></label></>:<>
   <label>{systemText("物料号")}<input autoFocus required disabled={busy} value={code} onChange={e=>setCode(e.target.value)}/></label>
   <label>{basis?.values.material_name?systemText("备件描述 · 仓库主数据"):systemText("备件描述（选填）")}<input disabled={busy||!!basis?.values.material_name} value={basis?.values.material_name??name} onChange={e=>setName(e.target.value)}/></label>
  </>}
  <div className="form-grid"><label>{systemText("海运数量")}<input required disabled={busy} type="number" min="0" value={sea} onChange={e=>setSea(e.target.value)}/></label><label>{systemText("空运数量")}<input required disabled={busy} type="number" min="0" value={air} onChange={e=>setAir(e.target.value)}/></label></div>
  {snapshotId&&ver.rule.v3_revision&&code&&<PlanReference salesOnly requireSales input={rows.find(r=>r.material_code===code)||{}} changes={reference} onChange={setReference} readOnly={busy}/>}
  {!snapshotId&&<details className="reuse-data" open={ver.rule.v3_revision?true:undefined}><summary>{systemText("填写基础数据")}</summary><PlanReference requireSales={!!ver.rule.v3_revision} input={basis?.values||{}} basis={basis} changes={reference} onChange={setReference} readOnly={busy} omitDescription/></details>}
  <div className="modal-actions"><button className="primary" disabled={!code.trim()||busy}>{busy?systemText("正在添加…"):systemText("添加物料")}</button></div>
 </form></Modal>
}

function ImportPlan({warehouse,legacyPeriod,ver,onClose,onDone}:{warehouse:string;legacyPeriod:boolean;ver:any;onClose:()=>void;onDone:()=>void|Promise<void>}){
 const [file,setFile]=useState<File|null>(null),[job,setJob]=useState<any>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const full=['v3','v2','legacy'].includes(job?.plan_format)
 const issues=job?.issues_total??job?.issues?.length??0, validation=job?.validation_total??job?.validation?.length??0
 const firstIssue=job?.issues?.[0]
 const close=useFormExit(false,busy,onClose)
 async function check(){
  if(!file)return
  const form=new FormData();form.append('file',file);form.append('warehouse',warehouse);form.append('kind','plan');form.append('version_id',ver.id)
  setBusy(true);setError('')
  try{const created=await api('/imports',form);setJob(await waitJob(created.id))}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 async function commit(){
  setBusy(true);setError('')
  try{await api('/imports/'+job.id+'/commit',{version_id:ver.id,revision:ver.revision,mode:full?'replace':'update_quantities'});await onDone()}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 return <Modal title={systemText("导入本次计划")} onClose={close} wide><div className="modal-body" data-usage-target="import">
  {error&&<Notice message={error} tone="error"/>}
  <div className="upload-area"><FileSpreadsheet size={27}/><label><strong>{file?.name||systemText("选择 V3 原表或计划文件")}</strong><span>{systemText(".xlsx 或 UTF-8 .csv · 最多 10,000 行")}</span><input disabled={busy} type="file" accept=".xlsx,.csv" onChange={e=>{setFile(e.target.files?.[0]||null);setJob(null);setError('')}}/></label></div>
  <div className="plan-templates"><V3TemplateDownload versionId={ver.id} chooseMonth={legacyPeriod}/><a className="text-button" href={BASE+'/template?kind=plan'+(getLanguage()==='en'?'&lang=en':'')}>{systemText("仅更新数量模板")}</a></div>
  {job&&<div className="preview-box"><h3>{full?systemText("完整计划 · 含基础数据"):systemText("计划数量")} · {job.rows} {systemText("行")}</h3>
   {firstIssue?<Notice message={tr(`第 ${firstIssue.row} 行 ${firstIssue.material_code||''} · ${firstIssue.message}${issues>1?`（共 ${issues} 项）`:''}`,`Row ${firstIssue.row} ${firstIssue.material_code||""} · ${planMessage(firstIssue.message)}${issues>1?" ("+issues+" issues)":""}`)} tone="error"/>:<Notice message={full?systemText("按此表替换当前草稿的全部明细和基础数据。"):systemText("已有物料留空保留原量，填 0 清零。新增物料留空按 0。")} tone="info"/>}
   {(issues>0||validation>0)&&<p>{validation>0&&<span>{systemText("字段问题")} {validation} {systemText("项")} </span>}<a href={BASE+'/imports/'+job.id+'/errors'}>{systemText("下载错误明细")}</a></p>}
   <table><thead><tr><th>{systemText("物料号")}</th>{full&&<th>{systemText("在库")}</th>}<th>{systemText("海运")}</th><th>{systemText("空运")}</th></tr></thead><tbody>{job.preview?.map((i:any,n:number)=><tr key={n}><td>{i.material_code}</td>{full&&<td>{i.on_hand_qty??'—'}</td>}<td>{(i.source_values??i).sea_plan_qty||'—'}</td><td>{(i.source_values??i).air_plan_qty||'—'}</td></tr>)}</tbody></table>
  </div>}
  <div className="modal-actions"><button className="secondary" disabled={busy} onClick={close}>{systemText("取消")}</button>
   {job?<button className="primary" disabled={busy||issues>0} data-usage-target="import" onClick={commit}>{busy?systemText("正在导入…"):systemText("确认导入")}</button>:<button className="primary" disabled={!file||busy} data-usage-target="import" onClick={check}>{busy?systemText("正在检查…"):systemText("检查文件")}<ArrowRight size={15}/></button>}
  </div>
 </div></Modal>
}
