import {createPortal} from 'react-dom'
import {useState,useEffect,useRef,FormEvent} from 'react'
import {ArrowLeft,ArrowRight,Download,Upload,Plus,Search,ChevronLeft,ChevronRight,Check,CheckCheck,Send,RotateCcw,Copy,History,Save,SlidersHorizontal,FileSpreadsheet,AlertCircle,X,RefreshCw} from 'lucide-react'
import ReviewTable,{ColumnPicker,TableViewControls,DEFAULT_COLUMNS,withMaterialColumns,EMPTY_TABLE,TableState} from './ReviewTable'
import BasisDialog from './BasisDialog'
import VersionHistory from './VersionHistory'
import CopyPlan from './CopyPlan'
import ConfirmationDialog from './ConfirmationDialog'
import {api,waitJob,BASE,fmt,date,flagLabels,reasonLabel,reasonLabels} from './api'
import {Badge,Busy,Empty,Modal,Notice,Stepper,useDialog,useFormExit} from './ui'

export default function PlanView({batchId,user,onBack,onUpdate,notify,onDirty,onOpenBatch,backLabel='返回计划列表'}:{backLabel?:string;onOpenBatch:(id:string)=>void;onDirty:(v:boolean)=>void;batchId:string;user:any;onBack:()=>void;onUpdate:()=>void;notify:(s:string)=>void}){
 const [batch,setBatch]=useState<any>(null),[ver,setVer]=useState<any>(null),[versionId,setVersionId]=useState(''),[q,setQ]=useState(''),[filter,setFilter]=useState('all'),[page,setPage]=useState(1),[busy,setBusy]=useState(false),[error,setError]=useState(''),[issueRows,setIssueRows]=useState<any[]>([])
 const [selected,setSelected]=useState<Set<string>>(new Set()),[edits,setEdits]=useState<Record<string,Record<string,string>>>({}),[detail,setDetail]=useState<any>(null),[dialog,setDialog]=useState(''),[history,setHistory]=useState(false),[exporting,setExporting]=useState(false),[reviewMeta,setReviewMeta]=useState<any>({flags:[],exception:false})
 const [visibleCols,setVisibleCols]=useState<string[]>(()=>{try{return withMaterialColumns(JSON.parse(localStorage.getItem('plan-columns-v2-'+user.id)||'null'))}catch{return DEFAULT_COLUMNS}})
 const [issueListOpen,setIssueListOpen]=useState(false)
 const [tableState,setTableState]=useState<TableState>(EMPTY_TABLE)
 useEffect(()=>{localStorage.setItem('plan-columns-v2-'+user.id,JSON.stringify(visibleCols))},[visibleCols])
 const [density,setDensity]=useState<'compact'|'standard'>(()=>localStorage.getItem('plan-density-'+user.id)==='compact'?'compact':'standard')
 useEffect(()=>{localStorage.setItem('plan-density-'+user.id,density)},[density,user.id])
 const [queue,setQueue]=useState<string[]>([]),[drawerDirty,setDrawerDirty]=useState(false)
 const [pending,setPending]=useState<{run:()=>void}|null>(null)
 const lock=useRef(false)
 const tableQuery=`&column_filters=${encodeURIComponent(JSON.stringify(tableState.filters))}&sort_key=${encodeURIComponent(tableState.sortKey)}&sort_direction=${tableState.sortDirection}`
 function changeTable(next:TableState){setTableState(next);setPage(1);setSelected(new Set())}
 const requestSeq=useRef(0)
 function selectVersion(id:string){
  if(id===ver.id)return
  proceed(()=>{setVersionId(id);setVer(null);setPage(1);setSelected(new Set());setError('')})
 }
 async function load(id?:string,refreshBatch=true){
  const seq=++requestSeq.current
  const overview='/batches/'+batchId+'?include_events=false'
  try{
   let summary=refreshBatch||!batch?await api(overview):batch
   const vid=id||versionId||summary.current_id
   const version=await api('/versions/'+vid+'?include_batch_context=true&q='+encodeURIComponent(q)+'&filter='+filter+'&page='+page+tableQuery)
   if(seq!==requestSeq.current)return
   if(summary.current_id!==version.batch_current_id||summary.state!==version.batch_state||summary.updated_at!==version.batch_updated_at){
    summary=await api(overview)
    if(seq!==requestSeq.current)return
   }
   setBatch(summary);setVer(version);setVersionId(vid)
   const last=Math.max(1,Math.ceil(version.total/version.page_size))
   if(page>last)setPage(last)
  }catch(e:any){if(seq===requestSeq.current)setError(e.message)}
 }
 useEffect(()=>{load(undefined,false)},[batchId,versionId,q,filter,page,tableQuery])
 const editable=ver?.state==='DRAFT'&&ver?.owner===user.id&&batch?.current_id===ver?.id&&user.roles.includes('PLANNER')
 const reviewing=['SUBMITTED','IN_REVIEW'].includes(ver?.state)&&user.roles.includes('REVIEWER')&&ver?.owner!==user.id
 useEffect(()=>{if(filter==='pending'&&ver&&!['SUBMITTED','IN_REVIEW'].includes(ver.state)){setFilter('all');setPage(1)}},[ver?.state])
 const dirty=Object.keys(edits).length>0
 const unsaved=dirty||drawerDirty
 useEffect(()=>{onDirty(unsaved);const unload=(e:BeforeUnloadEvent)=>{if(unsaved){e.preventDefault();e.returnValue=''}};window.addEventListener('beforeunload',unload);return()=>{onDirty(false);window.removeEventListener('beforeunload',unload)}},[unsaved,onDirty])
 async function execute(fn:()=>Promise<any>,message?:string){if(lock.current)throw new Error('操作正在处理');lock.current=true;setBusy(true);setError('');setIssueRows([]);setIssueListOpen(false);try{const result=await fn();if(message)notify(message);await load(result?.version_id||ver.id);onUpdate();return result}catch(e:any){setError(e.message);setIssueRows(e.detail?.issues||[]);throw e}finally{lock.current=false;setBusy(false)}}
 async function save(){await execute(()=>api(`/versions/${ver.id}/items`,{revision:ver.revision,changes:Object.entries(edits).map(([id,values])=>({id,values}))},'PATCH'),ver.snapshot?'修改已保存并重新计算':'修改已保存');setEdits({})}
 function setNumber(id:string,key:string,value:string){
  const original=ver.items.find((item:any)=>item.id===id)?.input[key]
  setEdits(old=>{
   const values={...old[id]}
   if(String(original??'')===value)delete values[key];else values[key]=value
   const next={...old}
   if(Object.keys(values).length)next[id]=values;else delete next[id]
   return next
  })
 }
 function proceed(action:()=>void){
  if(lock.current)return
  if(dirty)setPending({run:action});else action()
 }
 async function resume(saveFirst:boolean){
  const action=pending?.run
  if(!action||lock.current)return
  if(saveFirst){try{await save()}catch{return}}
  else setEdits({})
  setPending(null);action()
 }
 async function openDetail(row:any){
  setBusy(true);setError('')
  try{
   const [result,current]=await Promise.all([api(`/versions/${ver.id}/selection?q=${encodeURIComponent(q)}&filter=${filter}${tableQuery}`),api(`/versions/${ver.id}/items/${row.id}`)])
   setQueue(result.ids.includes(row.id)?result.ids:[row.id]);setDrawerDirty(false);setDetail(current)
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 async function openIssue(id:string,ids:string[]){
  const item=await api('/versions/'+ver.id+'/items/'+id)
  setDialog('');setQueue(ids);setDrawerDirty(false);setDetail(item)
 }
 async function openReviewSelection(){
  setBusy(true);setError('')
  try{
   const meta=await api('/versions/'+ver.id+'/review-summary',{ids:[...selected],only_pending:true})
   if(!meta.count){notify('所选物料已全部复审');return}
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
   notify('复审决定已保存')
  }else{
   const changed=Object.fromEntries(Object.entries(values).filter(([field,value])=>String(value??'')!==String(detail.input[field]??'')))
   if(Object.keys(changed).length)await execute(()=>api(`/versions/${ver.id}/items`,{revision:ver.revision,changes:[{id:detail.id,values:changed}]},'PATCH'),'修改已保存')
  }
  if(successor){setDrawerDirty(false);setDetail(successor)}else closeDetail()
 }
 async function doExport(scope:string){setExporting(true);setError('');try{const j=await api('/exports',{version_id:ver.id,scope,q,filter,column_filters:tableState.filters,sort_key:tableState.sortKey,sort_direction:tableState.sortDirection});const done=await waitJob(j.id);const link=document.createElement('a');link.href=done.download_url;link.download=done.filename;link.click();notify('结果文件已生成')}catch(e:any){setError(e.message)}finally{setExporting(false)}}
 async function confirmAction(values:any){
    let path='',body:any={revision:ver.revision,...values};let method='POST'
    if(dialog==='reason'){path=`/versions/${ver.id}/items`;body={revision:ver.revision,changes:[...selected].map(id=>({id,values}))};method='PATCH'}
    else if(dialog==='delete'){path=`/versions/${ver.id}/items`;body.ids=[...selected];method='DELETE'}
    else if(dialog==='void')path=`/batches/${batch.id}/void`
    else if(dialog==='review'){path=`/versions/${ver.id}/reviews`;body.ids=[...selected];body.only_pending=true}
    else {path=`/versions/${ver.id}/${dialog}`;if(dialog==='return')body.ids=[...selected]}
    const r=await execute(()=>api(path,body,method));setDialog('');setSelected(new Set())
    if(dialog==='review'){
     const result=[`本次批准 ${r.count} 行`]
     if(r.preserved)result.push(`已有决定 ${r.preserved} 行`)
     if(r.skipped?.length){
      result.push(`需单独处理 ${r.skipped.length} 行`)
      setIssueRows(r.skipped.map((item:any)=>({...item,message:item.reason})))
     }
     notify(result.join(' · '))
    }else notify(({submit:'已提交复审',finalize:'整批计划已通过',return:'已退回并生成新草稿',reason:'说明已保存',delete:'已移除所选计划行',void:'计划已作废'} as any)[dialog]||'复审决定已保存')

 }
 if(!ver||!batch)return error?<><Notice message={error} tone="error"/><button className="secondary" onClick={()=>{setError('');load()}}>重新读取</button></>:<Busy/>
 const counts=ver.summary
 const showReturned=editable&&batch.state==='RETURNED'&&counts.return_requested>0
 return <div className="plan-view">
  <button className="back-link" disabled={busy} onClick={()=>proceed(onBack)}><ArrowLeft size={15}/>{backLabel}</button>
  <div className="page-heading plan-heading"><div><div className="heading-inline"><h1>{batch.title}</h1><Badge value={ver.state}/></div><p>{batch.warehouse_name}<span className="separator">/</span>{batch.number}<span className="separator">/</span>第 {ver.seq} 版<span className="separator">/</span>{batch.owner_name}<span className="separator">/</span>{batch.period_info?.label||batch.period}</p></div><div className="actions"><button className="secondary" onClick={()=>setHistory(!history)} disabled={busy}><History size={16}/>版本记录</button><button className="secondary" onClick={()=>proceed(()=>doExport('all'))} disabled={exporting||busy}>{exporting?<RefreshCw size={16} className="spin"/>:<Download size={16}/>}导出</button>{editable&&<button className="primary" disabled={busy||!counts.total} onClick={()=>proceed(()=>setDialog('submit'))}><Send size={16}/>提交复审</button>}{reviewing&&<><button className="secondary" disabled={busy} onClick={()=>setDialog('return')}><RotateCcw size={16}/>退回</button><button className="primary" disabled={busy||!counts.total} onClick={()=>setDialog('finalize')}><CheckCheck size={17}/>完成终审</button></>}</div></div>
  {ver.id===batch.current_id&&batch.state!=='VOID'&&<Stepper current={ver.state==='APPROVED'?4:ver.state==='DRAFT'?(counts.total?2:1):3}/>}
  {batch.state==='RETURNED'&&editable&&<Notice message={'复审退回意见：'+(batch.events.find((e:any)=>e.action==='退回修改')?.detail.reason||'请核对计划后重新提交。')}/>} 
  {error&&<Notice message={error} tone="error"/>}
  {issueRows.length>0&&<div className="issue-list">{(issueListOpen?issueRows:issueRows.slice(0,6)).map((e,i)=><button key={i} disabled={busy} onClick={()=>proceed(()=>{if(e.id){setBusy(true);openIssue(e.id,issueRows.map(row=>row.id).filter(Boolean)).catch(err=>setError(err.message)).finally(()=>setBusy(false))}else{setQ(e.material_code||'');setFilter('all');changeTable(EMPTY_TABLE)}})}><span>{e.material_code}</span>{e.message}</button>)}{issueRows.length>6&&<button className="text-button" onClick={()=>setIssueListOpen(!issueListOpen)}>{issueListOpen?'收起':`查看全部 ${issueRows.length} 项`}</button>}</div>}
  {ver.id!==batch.current_id&&<div className="historical-context"><span>正在查看历史版本 · 第 {ver.seq} 版</span><button className="text-button" onClick={()=>selectVersion(batch.current_id)}>返回最新版</button></div>}
  {history&&<VersionHistory key={ver.id} versions={batch.versions} selected={ver} revision={ver.revision} current={batch.current_id} busy={busy} onSelect={selectVersion} onClose={()=>setHistory(false)}/>}
  <div className="basis-line"><span><span className="live-dot"/> {ver.rule.name}</span><span><DatabaseIcon/> {ver.snapshot?<>{ver.snapshot.name}<small>数据日期 {ver.snapshot.as_of}</small></>:'未关联快照 · 人工复审'}</span>{editable&&<button className="text-button" disabled={busy} onClick={()=>proceed(()=>setDialog('basis'))}>{ver.snapshot?'更换依据':'关联数据快照'}<SlidersHorizontal size={13}/></button>}<span className="spacer"/>{reviewing?<span className="review-progress">已复审 <b>{counts.reviewed}</b> / {counts.total} 行</span>:<span>{ver.id===batch.current_id?'已保存 '+date(batch.updated_at):'历史版本 · 只读'}</span>}</div>
  <section className={`panel plan-table-panel density-${density}`}><div className="plan-table-header"><div><h2>{reviewing?'核对与复审':'计划明细'}</h2><span>{counts.total} 行物料</span></div><div className="actions">{editable&&<><button className="text-button" disabled={busy} onClick={()=>proceed(()=>setDialog('add'))}><Plus size={15}/>添加物料</button><button className="secondary compact" disabled={busy} onClick={()=>proceed(()=>setDialog('import'))}><Upload size={15}/>导入计划</button></>}</div></div>
   <div className="filter-tabs">{[['all','全部',counts.total],...(showReturned?[['returned','指定修改',counts.return_requested]]:[]),['attention','需关注',counts.attention],...(ver.rule?.model==='V2'?[['delay','建议延迟',counts.delay||0]]:[]),['WITHIN','合理',counts.WITHIN],['BELOW','偏少',counts.BELOW],['ABOVE','偏多',counts.ABOVE],['MANUAL','人工判断',counts.MANUAL],['EXEMPT','免数量审核',counts.EXEMPT],[reviewing?'pending':'unexplained',reviewing?'未复审':'资料待补',reviewing?counts.total-counts.reviewed:counts.unexplained]].map(([key,name,count])=><button disabled={busy} key={String(key)} aria-pressed={filter===key} className={filter===key?'active':''} onClick={()=>proceed(()=>{setFilter(String(key));setPage(1);setSelected(new Set())})}>{name}<span>{count}</span></button>)}</div>
   <div className="list-toolbar"><label className="search"><Search size={16}/><input aria-label="搜索物料号或名称" value={q} disabled={busy} onChange={e=>{const value=e.target.value;proceed(()=>{setQ(value);setPage(1);setSelected(new Set())})}} placeholder="搜索物料号或名称"/></label><select aria-label="更多物料筛选" disabled={busy} value={['ERROR','air','modified','abc:A','abc:B','abc:C'].includes(filter)?filter:''} onChange={e=>{const value=e.target.value;proceed(()=>{setFilter(value||'all');setPage(1);setSelected(new Set())})}}><option value="">更多筛选</option><option value="ERROR">数据错误</option><option value="air">包含空运</option><option value="modified">已修改</option><option value="abc:A">物料分类 A</option><option value="abc:B">物料分类 B</option><option value="abc:C">物料分类 C</option></select><TableViewControls columns={visibleCols} onChange={setVisibleCols} density={density} onDensityChange={setDensity} disabled={busy} availableColumns={ver.columns.map((c:any)=>c.key)}/><ColumnPicker disabled={busy} columns={ver.columns||[]} visible={visibleCols} onChange={setVisibleCols}/><span className="spacer"/><button className="text-button" disabled={busy||exporting} onClick={()=>proceed(()=>doExport('filtered'))}><Download size={14}/>导出筛选</button></div>
   {selected.size>0&&<div className="selection-bar"><strong>已选 {selected.size} 行</strong><button className="text-button" onClick={async()=>{const r=await api(`/versions/${ver.id}/selection?q=${encodeURIComponent(q)}&filter=${filter}${tableQuery}`);setSelected(new Set(r.ids))}}>选择全部筛选结果 ({ver.total})</button><span className="spacer"/>{editable&&<><button disabled={busy} onClick={()=>proceed(()=>setDialog('reason'))}>批量填写说明</button><button disabled={busy} onClick={()=>proceed(()=>setDialog('delete'))}>移除</button></>}{reviewing&&<><button disabled={busy} onClick={openReviewSelection}>复审所选</button></>}<button aria-label="取消选择" onClick={()=>setSelected(new Set())}><X size={15}/></button></div>}
   <ReviewTable ver={ver} visible={visibleCols} state={tableState} onState={next=>proceed(()=>changeTable(next))} editable={editable} dirty={false} busy={busy} selected={selected} setSelected={setSelected} edits={edits} setNumber={setNumber} onDetail={row=>proceed(()=>openDetail(row))}/>
   {editable&&!counts.total&&<div className="empty-plan-import"><button className="primary" onClick={()=>setDialog('import')}><Upload size={16}/>导入计划</button></div>}
   <div className="table-footer"><span>显示 {ver.total?((page-1)*ver.page_size+1):0}–{Math.min(page*ver.page_size,ver.total)} / {ver.total} 行</span><span className="spacer"/><button className="icon-button" aria-label="上一页" disabled={busy||page<=1} onClick={()=>proceed(()=>setPage(page-1))}><ChevronLeft size={17}/></button><span>{page} / {Math.max(1,Math.ceil(ver.total/ver.page_size))}</span><button className="icon-button" aria-label="下一页" disabled={busy||page*ver.page_size>=ver.total} onClick={()=>proceed(()=>setPage(page+1))}><ChevronRight size={17}/></button></div>
  </section>
  <div className="plan-bottom-note"><span className="spacer"/>{user.roles.includes('PLANNER')&&<button className="text-button" disabled={busy} onClick={()=>proceed(()=>setDialog('copy'))}><Copy size={14}/>复制为新计划</button>}{editable&&<button className="text-button" disabled={busy} onClick={()=>proceed(()=>setDialog('void'))}>作废计划</button>}</div>
  {dirty&&<div className="save-bar"><span><span className="unsaved-dot"/>{Object.keys(edits).length} 行修改尚未保存</span><span className="spacer"/><button className="secondary" disabled={busy} onClick={()=>setEdits({})}>撤销本次修改</button><button className="primary" disabled={busy} onClick={()=>save().catch(()=>{})}><Save size={16}/>{busy?'正在保存…':ver.snapshot?'保存并重算':'保存修改'}</button></div>}
  {pending&&<Modal title={`保存这 ${Object.keys(edits).length} 行修改？`} onClose={()=>{if(!busy)setPending(null)}}><div className="modal-body">{error&&<Notice message={error} tone="error"/>}<div className="modal-actions"><button className="text-button" disabled={busy} onClick={()=>setPending(null)}>继续编辑</button><button className="secondary" disabled={busy} onClick={()=>resume(false)}>放弃并继续</button><button className="primary" disabled={busy} onClick={()=>resume(true)}>{busy?'正在保存…':'保存并继续'}</button></div></div></Modal>}
  {detail&&<ItemDrawer onReturn={()=>{setSelected(new Set([detail.id]));closeDetail();setDialog('return')}} key={detail.id} row={detail} ver={ver} editable={editable} reviewing={reviewing} position={position} total={queue.length} onMove={advance} onDirty={setDrawerDirty} onClose={closeDetail} onSave={(v,next)=>finishItem(v,next,false)} onReview={(v,next)=>finishItem(v,next,true)}/>}
  {['return','review','reason','delete','void'].includes(dialog)&&<ActionDialog kind={dialog} reviewMeta={reviewMeta} count={selected.size} onClose={()=>setDialog('')} onConfirm={confirmAction}/>} 
  {['submit','finalize'].includes(dialog)&&<ConfirmationDialog kind={dialog} ver={ver} onItem={openIssue} onClose={()=>setDialog('')} onConfirm={confirmAction}/>}
  {dialog==='add'&&<AddMaterial ver={ver} onClose={()=>setDialog('')} onAdd={async item=>{await execute(()=>api(`/versions/${ver.id}/items`,{revision:ver.revision,items:[item]}),'物料已添加');setDialog('')}}/>}
  {dialog==='import'&&<ImportPlan warehouse={batch.warehouse} ver={ver} onClose={()=>setDialog('')} onDone={async()=>{setDialog('');await load();onUpdate();notify('计划已导入，请开始自审')}}/>}
  {dialog==='copy'&&<CopyPlan batch={batch} version={ver} onClose={()=>setDialog('')} onCreated={id=>{setDialog('');onUpdate();onOpenBatch(id);notify('已创建计划副本')}}/>}
  {dialog==='basis'&&<BasisDialog warehouse={batch.warehouse} ver={ver} onClose={()=>setDialog('')} onDone={async()=>{setDialog('');await load();onUpdate();notify('计算依据已更新')}}/>}
 </div>
}

function DatabaseIcon(){return <FileSpreadsheet size={14}/>}


function ReasonOptions({current}:{current?:string}){
 return <>{current&&!reasonLabels.has(current)&&<option value={current}>{current}</option>}
  {Array.from(reasonLabels,([code,label])=><option key={code} value={code}>{label}</option>)}</>
}

function adjustmentValue(key:string, value:unknown){
 const text=String(value??'未填写')
 return key==='reason_code'?reasonLabel(text):text
}

function ItemDrawer({row,ver,editable,reviewing,position,total,onMove,onDirty,onClose,onSave,onReview,onReturn}:{
 row:any;ver:any;editable:boolean;reviewing:boolean;position:number;total:number
 onReturn:()=>void;onMove:(index:number)=>Promise<void>;onDirty:(v:boolean)=>void;onClose:()=>void
 onSave:(v:any,next:boolean)=>Promise<void>;onReview:(v:any,next:boolean)=>Promise<void>
}){
 const i=row.input,r=row.result
 const initial={sea_plan_qty:i.sea_plan_qty??'',air_plan_qty:i.air_plan_qty??'',reason_code:i.reason_code||'',reason:i.reason||'',air_reason:i.air_reason||''}
 const [tab,setTab]=useState('action'),[values,setValues]=useState(initial),[busy,setBusy]=useState(false),[error,setError]=useState(''),[reviewDirty,setReviewDirty]=useState(false)
 const dirty=reviewDirty||Object.keys(initial).some(k=>String(values[k as keyof typeof values])!==String(initial[k as keyof typeof initial]))
 useEffect(()=>{onDirty(dirty);return()=>onDirty(false)},[dirty,onDirty])
 function mayLeave(){return !busy&&(!dirty||window.confirm('放弃本条未保存的修改？'))}
 function close(){if(mayLeave())onClose()}
 const drawerRef=useDialog(close)
 async function run(action:()=>Promise<void>){
  if(busy)return
  setBusy(true);setError('')
  try{await action()}catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 function move(index:number){if(mayLeave())void run(()=>onMove(index))}
 function save(e:FormEvent){e.preventDefault();const next=((e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement)?.value==='next';void run(()=>onSave(values,next))}
 return createPortal(<div className="drawer-backdrop" onMouseDown={e=>e.target===e.currentTarget&&close()}><aside ref={drawerRef} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-label={'物料详情 '+i.material_code}><div className="drawer-head"><div><span className="material-code-value">{i.material_code}</span><h2>{i.material_name||'—'}</h2><span>{i.material_abc||'未分类'}</span></div><button className="icon-button" disabled={busy} onClick={close} aria-label="关闭物料详情"><X size={21}/></button></div>
 <div className="drawer-queue"><button className="text-button" disabled={busy||position<=0} onClick={()=>move(position-1)}><ChevronLeft size={15}/>上一条</button><span>{position+1} / {total}</span><button className="text-button" disabled={busy||position+1>=total} onClick={()=>move(position+1)}>下一条<ChevronRight size={15}/></button></div>
 <div className="drawer-tabs"><button disabled={busy} aria-pressed={tab==='action'} className={tab==='action'?'active':''} onClick={()=>setTab('action')}>计划与处理</button><button disabled={busy} aria-pressed={tab==='evidence'} className={tab==='evidence'?'active':''} onClick={()=>setTab('evidence')}>计算依据</button></div><div className="drawer-body">
  {error&&<Notice message={error} tone="error"/>}<div className="drawer-result"><Badge value={['ERROR','PENDING'].includes(r.data_status)?r.data_status:r.review_mode==='AUTO'?r.quantity_status:r.review_mode}/>{ver.snapshot&&<><span>未来库存 <b>{fmt(r.future_qty)}</b></span><span>合理区间 <b>{fmt(r.lower)} — {fmt(r.upper)}</b></span></>}</div>
  {row.submission_override&&(!row.submission_override.mode||row.submission_override.reason)&&<Notice message={'提交备注 · '+row.submission_override.user_name+'：'+row.submission_override.reason}/> }
  {row.decision?.forced&&<Notice message={'例外终审 · '+row.decision.reviewer_name+'：'+row.decision.reason}/>}
  {r.errors.map((e:any,n:number)=><Notice key={n} message={e.message} tone="error"/>)}
  {r.delay_replenishment&&<div className="advice-box exception"><strong>建议延迟补货</strong><p>{r.review_mode==='EXEMPT'?`近半年无销量，净库存 ${fmt(i.net_supply_before_plan)} 件。`:`在库周转 ${fmt(r.on_hand_months)} 个月，净库存周转 ${fmt(Number(r.pipeline_days)/30)} 个月。`}</p></div>}
  {r.manual_flags.length>0&&<div className="flag-list">{r.manual_flags.map((f:string)=><span key={f}><AlertCircle size={14}/>{flagLabels[f]}</span>)}</div>}
  <div hidden={tab!=='action'} inert={busy||undefined}>
   {row.adjustment&&<details className="adjustment"><summary>最近一次调整 · {date(row.adjustment.at)}</summary>{Object.entries(row.adjustment.after).map(([key,val])=><p key={key}>{({sea_plan_qty:'海运',air_plan_qty:'空运',reason:'说明',reason_code:'原因类别',air_reason:'空运说明'} as any)[key]}：{adjustmentValue(key,row.adjustment.before[key])} → {adjustmentValue(key,val)}</p>)}{row.adjustment.review_reason&&<p>数量已调整，请复核原说明是否仍适用。</p>}</details>}
   {r.review_mode==='AUTO'&&r.quantity_status!=='UNAVAILABLE'&&<div className={'advice-box '+((r.quantity_status!=='WITHIN'||r.sea_feasible===false)?'exception':'')}><strong>{r.quantity_status==='WITHIN'?'计划数量在合理区间内':r.sea_feasible===false?'已有供给需要进一步核对':r.quantity_status==='BELOW'?'建议适当增加海运计划':'建议适当减少海运计划'}</strong><p>{r.sea_feasible===false?`本次海运即使减到 0，仍有 ${fmt(r.residual_excess)} 件超出库存上限。`:r.sea_feasible?`保持空运不变时，海运可行范围为 ${fmt(r.sea_lower)}–${fmt(r.sea_upper)} 件，建议本次海运 ${fmt(r.suggested_sea_qty)} 件。`:r.explanation}</p>{editable&&r.sea_feasible&&r.quantity_status!=='WITHIN'&&<button type="button" className="text-button" onClick={()=>setValues({...values,sea_plan_qty:r.suggested_sea_qty})}>填入建议海运量 <ArrowRight size={13}/></button>}</div>}
   {ver.snapshot&&r.review_mode!=='AUTO'&&<p className="explanation">{r.review_mode==='EXEMPT'?'本物料免数量审核。':'按实际市场需求判断，可补充需求依据。'}</p>}
   {editable?<form onSubmit={save}><div className="form-grid"><label>本次海运<input type="number" min="0" step={i.quantity_step||1} value={values.sea_plan_qty} onChange={e=>setValues({...values,sea_plan_qty:e.target.value})}/></label><label>本次空运<input type="number" min="0" step={i.quantity_step||1} value={values.air_plan_qty} onChange={e=>setValues({...values,air_plan_qty:e.target.value})}/></label></div><label>原因类别<select value={values.reason_code} onChange={e=>setValues({...values,reason_code:e.target.value})}><option value="">选填</option><ReasonOptions current={values.reason_code}/></select></label><label>计划说明<textarea aria-label="计划说明" rows={4} value={values.reason} onChange={e=>setValues({...values,reason:e.target.value})} maxLength={2000}/></label>{Number(values.air_plan_qty)>0&&<label>空运必要性<textarea rows={3} value={values.air_reason} onChange={e=>setValues({...values,air_reason:e.target.value})} placeholder="选填"/></label>}<div className="modal-actions"><button className={position+1<total?'secondary':'primary'} disabled={busy}><Save size={16}/>保存并关闭</button>{position+1<total&&<button className="primary" value="next" disabled={busy}>保存并下一条<ChevronRight size={16}/></button>}</div></form>:<div className="read-reasons"><h3>计划员说明</h3>{i.reason_code&&<p>{reasonLabel(i.reason_code)}</p>}<p>{i.reason||'未填写例外说明'}</p>{i.air_reason&&<><h3>空运必要性</h3><p>{i.air_reason}</p></>}</div>}
   {editable&&row.previous_decision&&<details className="adjustment"><summary>上版复审意见</summary><Badge value={row.previous_decision.status}/>{row.previous_decision.reason_code&&<p>{reasonLabel(row.previous_decision.reason_code)}</p>}{row.previous_decision.reason&&<p>{row.previous_decision.reason}</p>}<small>{row.previous_decision.reviewer_name} · {date(row.previous_decision.reviewed_at)}</small></details>}
   {row.decision&&<div className="decision-box"><Badge value={row.decision.status}/>{row.decision.reason_code&&<p>{reasonLabel(row.decision.reason_code)}</p>}{row.decision.reason&&<p>{row.decision.reason}</p>}<small>{row.decision.reviewer_name} · {date(row.decision.reviewed_at)}</small></div>}
   {reviewing&&r.data_status==='ERROR'&&<button className="secondary" disabled={busy} onClick={()=>{if(mayLeave())onReturn()}}><RotateCcw size={15}/>退回整批并标记此行</button>}
   {reviewing&&<ReviewForm previous={row.decision} flags={r.manual_flags} exception={['BELOW','ABOVE'].includes(r.quantity_status)} hasNext={position+1<total} onDirty={setReviewDirty} onConfirm={(v,next)=>run(()=>onReview(v,next))}/>}
  </div>{tab==='evidence'&&!ver.snapshot&&<p className="muted">本版未关联仓库数据，暂无自动审核结果。</p>}
  {tab==='evidence'&&ver.snapshot&&<><h3>本行计算过程</h3><div className="formula-chain"><div><span>01</span><section><strong>审核前净额</strong><b>{fmt(i.net_supply_before_plan)}</b><p>{ver.snapshot.basis}</p></section></div><div><span>02</span><section><strong>本次下单后的未来库存</strong><p className="formula">{fmt(i.net_supply_before_plan)} + {fmt(i.sea_plan_qty)} + {fmt(i.air_plan_qty)} = <b>{fmt(r.future_qty)}</b></p><small>审核前净额 + 海运 + 空运</small></section></div><div><span>03</span><section><strong>{r.rule_id||'人工判断'}</strong><p>{r.explanation}</p><dl><dt>更换率目标 X</dt><dd>{fmt(i.replacement_target)}</dd><dt>销量目标 Y</dt><dd>{fmt(i.sales_target)}</dd><dt>月均销量较大值 m</dt><dd>{fmt(r.m)}</dd><dt>装车量</dt><dd>{fmt(i.fleet_qty)}</dd>{'advice' in r&&<><dt>备件保有量</dt><dd>{fmt(i.vehicle_parc)}</dd><dt>车型</dt><dd>{i.vehicle_model||'—'}</dd><dt>在库周转（月）</dt><dd>{r.m==='0'?'无销量':fmt(r.on_hand_months)}</dd><dt>补货后周转（天）</dt><dd>{r.m==='0'?'无销量':fmt(r.future_days)}</dd><dt>审批建议</dt><dd>{r.advice}</dd>{i.source_note&&<><dt>备注</dt><dd>{i.source_note}</dd></>}</>}<dt>稳态更换率</dt><dd>{i.replacement_rate==null?'未提供':fmt(Number(i.replacement_rate)*100)+'%'}</dd><dt>重点车型</dt><dd>{i.is_key_model===true?'是':i.is_key_model===false?'否':'未提供'}</dd><dt>原始区间</dt><dd>{fmt(r.lower_raw)} — {fmt(r.upper_raw)}</dd><dt>取整后区间</dt><dd>{fmt(r.lower)} — {fmt(r.upper)}</dd></dl></section></div></div><details className="evidence-details"><summary>命中关键词与分类</summary>{Object.entries(r.matched_keywords).map(([group,words]:[string,any])=>words.length>0&&<p key={group}>{({small:'小件',maintenance:'保养件',dangerous:'危包',manual:'用品精品',no_stock:'不备货'} as any)[group]}：{words.join('、')}</p>)}{r.override&&<p>按当前规则版本覆盖为：{r.override}</p>}</details><details className="evidence-details"><summary>数据来源与审核参数</summary><p>{i.source?.file} / {i.source?.sheet} / 第 {i.source?.row} 行</p><p>快照：{ver.snapshot.name}</p><p>规则：{ver.rule.name}</p>{i.plan_source&&<p>计划来源：{i.plan_source.file} / {i.plan_source.sheet} / 第 {i.plan_source.row} 行</p>}<p>目标库存沿用所选数据快照中的提供值。</p><small>{r.precision_version}</small><dl>{Object.entries(ver.rule.params).map(([key,val])=><div className="parameter-evidence" key={key}><dt>{key}</dt><dd>{fmt(val)}</dd></div>)}</dl></details></>}
 </div></aside></div>,document.body)
}

function ReviewForm({flags,exception,onConfirm,onDirty,hasNext=false,previous}:{previous?:any;flags:string[];exception:boolean;onDirty?:(v:boolean)=>void;hasNext?:boolean;onConfirm:(v:any,next:boolean)=>Promise<void>}){
 const initialDecision=previous?.status||'APPROVED'
 const [decision,setDecision]=useState(initialDecision),[reasonCode,setReasonCode]=useState(previous?.reason_code||''),[reason,setReason]=useState(previous?.reason||'')
 const [acks,setAcks]=useState<string[]>(previous?.ack_flags||[]),[air,setAir]=useState(!!previous?.air_confirmed),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const dirty=decision!==initialDecision||reasonCode!==(previous?.reason_code||'')||reason!==(previous?.reason||'')||
  air!==!!previous?.air_confirmed||acks.length!==(previous?.ack_flags?.length||0)||acks.some(f=>!previous?.ack_flags?.includes(f))
 useEffect(()=>{onDirty?.(dirty);return()=>onDirty?.(false)},[dirty,onDirty])
 async function confirm(e:FormEvent){
  e.preventDefault();if(busy)return
  const next=((e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement)?.value==='next'
  setBusy(true);setError('')
  try{await onConfirm({decision,reason,reason_code:reasonCode,ack_flags:acks,air_confirmed:air},next)}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 return <form className="review-form" onSubmit={confirm}>
  {error&&<Notice message={error} tone="error"/>}
  {(exception||flags.length>0)&&<p className="muted">{[...(exception?['数量超出范围']:[]),...flags.map(f=>flagLabels[f]||f)].join(' · ')}</p>}
  <details open={previous?true:undefined}><summary>补充复审记录（选填）</summary>
   <label>处理方式<select value={decision} onChange={e=>setDecision(e.target.value)}><option value="APPROVED">批准</option><option value="EXCEPTION_APPROVED">例外批准</option></select></label>
   {decision==='EXCEPTION_APPROVED'&&<label>原因类别<select value={reasonCode} onChange={e=>setReasonCode(e.target.value)}><option value="">选填</option><ReasonOptions current={reasonCode}/></select></label>}
   {flags.filter(f=>f!=='AIR').map(f=><label key={f} className="check-row"><input type="checkbox" checked={acks.includes(f)} onChange={e=>setAcks(e.target.checked?[...acks,f]:acks.filter(x=>x!==f))}/><span>已核对 {flagLabels[f]}</span></label>)}
   {flags.includes('AIR')&&<label className="check-row"><input type="checkbox" checked={air} onChange={e=>setAir(e.target.checked)}/><span>已单独确认空运必要性</span></label>}
   <label>复审备注<textarea aria-label="复审备注" maxLength={2000} rows={2} value={reason} onChange={e=>setReason(e.target.value)}/></label>
  </details>
  <div className="modal-actions"><button className={hasNext?'secondary':'primary'} disabled={busy}><Check size={16}/>{previous?'保存复审决定':'确认批准'}</button>{hasNext&&<button className="primary" disabled={busy} value="next">批准并下一条<ChevronRight size={16}/></button>}</div>
 </form>
}

function ActionDialog({kind,count,reviewMeta,onClose,onConfirm}:{kind:string;reviewMeta:any;count:number;onClose:()=>void;onConfirm:(v:any)=>Promise<void>}){
 const [text,setText]=useState(''),[code,setCode]=useState(''),[airReason,setAirReason]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const [reviewDirty,setReviewDirty]=useState(false)
 const close=useFormExit(!!(text||code||airReason||reviewDirty),busy,onClose)
 const names:Record<string,string>={return:'退回计划',review:'复审所选 '+count+' 行',reason:'批量填写说明',delete:'移除所选计划行',void:'作废计划'}
 return <Modal title={names[kind]} onClose={close}><div className="modal-body" inert={busy||undefined}>{error&&<Notice message={error} tone="error"/>}{kind==='review'?<><p className="muted">待复审 {reviewMeta.count} 行{reviewMeta.preserved>0&&` · 已有决定 ${reviewMeta.preserved} 行`}</p>{(reviewMeta.errors>0||reviewMeta.delayed>0)&&<Notice message={[reviewMeta.errors>0&&('数据错误 '+reviewMeta.errors+' 行'),reviewMeta.delayed>0&&('建议延迟补货 '+reviewMeta.delayed+' 行')].filter(Boolean).join(' · ')}/>}<ReviewForm flags={reviewMeta.flags} exception={reviewMeta.exception} onDirty={setReviewDirty} onConfirm={async v=>{setBusy(true);try{await onConfirm(v)}finally{setBusy(false)}}}/></>:<form onSubmit={async e=>{e.preventDefault();setBusy(true);try{await onConfirm(kind==='reason'?{reason:text,reason_code:code,...(airReason?{air_reason:airReason}:{})}:{reason:text})}catch(e:any){setError(e.message)}finally{setBusy(false)}}}>
  
  {kind==='return'&&<p>整份计划将退回。{count>0?`已标记 ${count} 行需修改。`:'本次未指定物料。'}</p>}
  {kind==='delete'&&<p>将从当前草稿移除 {count} 行物料。</p>}
  {kind==='reason'&&<><p>说明将应用于已选中的 {count} 行，请确保需求依据一致。</p><label>原因类别<select required value={code} onChange={e=>setCode(e.target.value)}><option value="">请选择</option><ReasonOptions/></select></label></>}
  {['return','void','reason'].includes(kind)&&<label>{kind==='return'?'退回原因':kind==='void'?'作废原因':'计划说明'}<textarea rows={4} required value={text} onChange={e=>setText(e.target.value)} maxLength={2000}/></label>}
  {kind==='reason'&&<label>空运说明（仅在需要统一补充时填写）<textarea rows={2} value={airReason} onChange={e=>setAirReason(e.target.value)}/></label>}
  <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>返回</button><button className="primary" disabled={busy}>{busy?'正在处理…':'确认'}</button></div>
 </form>}</div></Modal>
}

function AddMaterial({ver,onClose,onAdd}:{ver:any;onClose:()=>void;onAdd:(v:any)=>Promise<void>}){
 const [q,setQ]=useState(''),[rows,setRows]=useState<any[]>([]),[code,setCode]=useState(''),[name,setName]=useState(''),[sea,setSea]=useState('0'),[air,setAir]=useState('0')
 const snapshotId=ver.snapshot?.id
 const [error,setError]=useState(''),[busy,setBusy]=useState(false)
 const close=useFormExit(!!code||!!name||sea!=='0'||air!=='0',busy,onClose)
 useEffect(()=>{
  let active=true
  if(!snapshotId)return
  api('/snapshots/'+snapshotId+'/materials?q='+encodeURIComponent(q)).then(data=>{if(active)setRows(data)}).catch(e=>{if(active)setError(e.message)})
  return()=>{active=false}
 },[q,snapshotId])
 async function add(e:FormEvent){
  e.preventDefault();setBusy(true);setError('')
  try{await onAdd({material_code:code.trim(),...(!snapshotId&&name.trim()?{material_name:name.trim()}:{}),sea_plan_qty:sea,air_plan_qty:air})}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 return <Modal title={snapshotId?"从快照添加物料":"添加物料"} onClose={close}><form className="modal-body" onSubmit={add}>
  {error&&<Notice message={error} tone="error"/>}
  {snapshotId?<><label>搜索物料<input disabled={busy} value={q} onChange={e=>{setQ(e.target.value);setCode('')}} placeholder="物料号或名称"/></label>
  <label>物料<select disabled={busy} required value={code} onChange={e=>setCode(e.target.value)}><option value="">请选择物料</option>{rows.map(r=><option key={r.material_code} value={r.material_code}>{r.material_code} · {r.material_name}</option>)}</select></label></>:<>
   <label>物料号<input autoFocus required disabled={busy} value={code} onChange={e=>setCode(e.target.value)}/></label>
   <label>物料名称（选填）<input disabled={busy} value={name} onChange={e=>setName(e.target.value)}/></label>
  </>}
  <div className="form-grid"><label>海运数量<input required disabled={busy} type="number" min="0" value={sea} onChange={e=>setSea(e.target.value)}/></label><label>空运数量<input required disabled={busy} type="number" min="0" value={air} onChange={e=>setAir(e.target.value)}/></label></div>
  <div className="modal-actions"><button className="primary" disabled={!code.trim()||busy}>{busy?'正在添加…':'添加物料'}</button></div>
 </form></Modal>
}

function ImportPlan({warehouse,ver,onClose,onDone}:{warehouse:string;ver:any;onClose:()=>void;onDone:()=>void|Promise<void>}){
 const [file,setFile]=useState<File|null>(null),[job,setJob]=useState<any>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const issues=job?.issues_total??job?.issues?.length??0, validation=job?.validation_total??job?.validation?.length??0
 const close=useFormExit(false,busy,onClose)
 async function check(){
  if(!file)return
  const form=new FormData();form.append('file',file);form.append('warehouse',warehouse);form.append('kind','plan')
  setBusy(true);setError('')
  try{const created=await api('/imports',form);setJob(await waitJob(created.id))}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 async function commit(){
  setBusy(true);setError('')
  try{await api('/imports/'+job.id+'/commit',{version_id:ver.id,revision:ver.revision});await onDone()}
  catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 return <Modal title="导入本次计划" onClose={close} wide><div className="modal-body">
  {error&&<Notice message={error} tone="error"/>}
  <div className="upload-area"><FileSpreadsheet size={27}/><label><strong>{file?.name||'选择计划文件'}</strong><span>.xlsx 或 UTF-8 .csv · 最多 10,000 行</span><input disabled={busy} type="file" accept=".xlsx,.csv" onChange={e=>{setFile(e.target.files?.[0]||null);setJob(null);setError('')}}/></label></div>
  <a className="text-button" href={BASE+'/template?kind=plan'}><Download size={14}/>下载计划模板</a>
  {job&&<div className="preview-box"><h3>检查完成 · {job.rows} 行</h3>
   {issues>0?<Notice message={'结构问题 '+issues+' 项，修正后可导入。'} tone="error"/>:<Notice message="确认导入将替换当前草稿的计划行。" tone="info"/>}
   {(issues>0||validation>0)&&<p>{validation>0&&<span>字段问题 {validation} 项　</span>}<a href={BASE+'/imports/'+job.id+'/errors'}>下载错误明细</a></p>}
   <table><thead><tr><th>物料号</th><th>海运</th><th>空运</th></tr></thead><tbody>{job.preview?.map((i:any,n:number)=><tr key={n}><td>{i.material_code}</td><td>{i.sea_plan_qty}</td><td>{i.air_plan_qty}</td></tr>)}</tbody></table>
  </div>}
  <div className="modal-actions"><button className="secondary" disabled={busy} onClick={close}>取消</button>
   {job?<button className="primary" disabled={busy||issues>0} onClick={commit}>{busy?'正在导入…':'确认导入'}</button>:<button className="primary" disabled={!file||busy} onClick={check}>{busy?'正在检查…':'检查文件'}<ArrowRight size={15}/></button>}
  </div>
 </div></Modal>
}
