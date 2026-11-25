import MailDeliveryStatus from './MailDeliveryStatus'
import {systemText,tr,warehouseName,getLanguage} from './i18n'
import {useCallback,useEffect,useRef,useState} from 'react'
import {ArrowRight,Bell,Check,CheckCheck,ChevronLeft,ChevronRight,RefreshCw} from 'lucide-react'
import {api,date,planStateLabel} from './api'
import WarehouseLabel,{WarehouseSelect} from './WarehouseLabel'
import {Empty,Notice} from './ui'
import './notification-center.css'

type Kind = 'SUBMITTED'|'TRANSFERRED'|'RETURNED'|'CLAIMED'|'FINALIZED'|'REMINDER'|'GENERAL'
export type InboxItem = {id:string;batch_id:string;warehouse:string;warehouse_name:string;title:string;number:string;
 state:string;reviewer_name:string|null;text:string;seen:boolean;at:string;kind:Kind;action:'CLAIM'|'REVIEW'|'EDIT'|null}
type Tab='all'|'unread'|'action'
export type InboxFilters={tab:Tab;kind:string;warehouse:string;page:number}
export type InboxPage={items:InboxItem[];counts:Record<Tab,number>;page:number;size:number;total:number;unread_in_filter:number;before:string}
export const defaultInbox:InboxFilters={tab:'all',kind:'',warehouse:'',page:1}
const kinds:Record<Kind,string>={SUBMITTED:'计划提交',TRANSFERRED:'复审转交',RETURNED:'退回修改',CLAIMED:'复审领取',FINALIZED:'终审结果',REMINDER:'审核提醒',GENERAL:'计划动态'}
const actions={CLAIM:'查看并领取',REVIEW:'继续复审',EDIT:'继续编辑'}
const tabs:[Tab,string][]=[['all','全部'],['unread','未读'],['action','待我处理']]

function detail(n:InboxItem){
 const text=n.text.startsWith(n.title+' ')?n.text.slice(n.title.length+1):n.text
 if(n.kind==='FINALIZED' && n.state==='PARTIALLY_APPROVED')return tr('历史结案（旧规则），逐行意见可在计划明细中查看。','Closed under previous rules. See plan details for each line decision.')
 if(getLanguage()==='en'){
  if(n.kind==='SUBMITTED' && text==='已提交，等待复审')return 'Submitted and awaiting review.'
  if(n.kind==='CLAIMED' && text.endsWith(' 已领取「'+n.title+'」的复审'))return text.slice(0,-(' 已领取「'+n.title+'」的复审').length)+' claimed this plan for review.'
  if(n.kind==='TRANSFERRED' && text.endsWith(' 将「'+n.title+'」转交给你复审'))return text.slice(0,-(' 将「'+n.title+'」转交给你复审').length)+' transferred this review to you.'
  const returned=/^已整单退回(?:，(\d+) 行需修改)?$/.exec(text)
  if(returned)return returned[1]?'Plan returned. Lines to revise: '+returned[1]+'.':'Plan returned for changes.'
  const approved=/^已通过终审，核准 (\d+) 行$/.exec(text)
  if(approved)return 'Plan approved. Lines approved: '+approved[1]+'.'
  const rejected=/^已整单不批准，(\d+) 行均不执行$/.exec(text)
  if(rejected)return 'Plan rejected. No lines will be executed ('+rejected[1]+' lines).'
  const reminders=/^有 (\d+) 行审核提醒$/.exec(text)
  if(reminders)return 'Lines flagged for review: '+reminders[1]+'.'
 }
 return text || systemText(kinds[n.kind])
}
export function NotificationPreview({data,onOpen,onAll}:{data:InboxPage|null;onOpen:(n:InboxItem)=>void;onAll:()=>void}){
 return <aside><section className="panel inbox-preview"><div className="panel-heading"><div><Bell size={17}/><h2>{systemText("通知")}</h2>
  {!!data?.counts.unread&&<span className="count-dot">{data.counts.unread}</span>}</div><button type="button" className="text-button" onClick={onAll}>{systemText("查看全部")}<ArrowRight size={14}/></button></div>
  {data?.items.length?<div className="inbox-preview-list">{data.items.map(n=><button key={n.id} type="button" onClick={()=>onOpen(n)}>
   <span aria-label={n.seen?systemText("已读"):systemText("未读")} className={'inbox-dot'+(n.seen?' seen':'')}/>
   <span><strong>{n.title}</strong><small><WarehouseLabel code={n.warehouse} name={n.warehouse_name}/> · {n.kind==='FINALIZED'?planStateLabel(n.state):systemText(kinds[n.kind])}</small></span>
   <time>{date(n.at)}</time></button>)}</div>:<div className="quiet-state"><Bell size={22}/><strong>{data?systemText("暂无通知"):systemText("正在读取通知…")}</strong></div>}
 </section></aside>
}

export default function NotificationCenter({filters,onFilter,warehouses,onOpen,onChanged,admin}:{
 admin:boolean;
 filters:InboxFilters;onFilter:(f:InboxFilters)=>void;warehouses:{code:string;name:string}[];onOpen:(n:InboxItem)=>Promise<void>;onChanged:()=>void
}){
 const [data,setData]=useState<InboxPage|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[writing,setWriting]=useState(false)
 const seq=useRef(0),writeLock=useRef(false)
 const {tab,kind,warehouse,page}=filters
 const load=useCallback(async(quiet=false)=>{
  const request=++seq.current
  if(!quiet)setLoading(true)
  try{
   const r=await api<InboxPage>('/notification-inbox?'+new URLSearchParams({tab,kind,warehouse,page:String(page)}))
   if(request===seq.current){setData(r);setError('')}
  }catch(e:any){if(request===seq.current){setData(null);setError(e.message)}}
  finally{if(request===seq.current)setLoading(false)}
 },[tab,kind,warehouse,page])
 useEffect(()=>{
  setData(null);load()
  const refresh=()=>{if(document.visibilityState==='visible'&&!writeLock.current)load(true)}
  const timer=window.setInterval(refresh,30000)
  document.addEventListener('visibilitychange',refresh)
  return ()=>{seq.current++;clearInterval(timer);document.removeEventListener('visibilitychange',refresh)}
 },[load])
 function filter(part:Partial<InboxFilters>){onFilter({...filters,page:1,...part})}
 async function mark(n?:InboxItem){
  if(writeLock.current||!data)return
  writeLock.current=true;setWriting(true);setError('')
  try{
   if(n)await api('/notifications/'+n.id+'/seen',{})
   else await api('/notification-inbox/seen',{tab,warehouse,kind,before:data.before})
   await load(true);onChanged()
  }catch(e:any){setError(e.message)}finally{writeLock.current=false;setWriting(false)}
 }
 const last=data?Math.max(1,Math.ceil(data.total/data.size)):1
 const currentPage=data?.page??1
 const unreadOnView=!!data?.unread_in_filter
 return <section className="inbox-center"><div className="page-heading"><h1>{systemText("通知中心")}</h1>
  <button className="secondary compact" aria-label={systemText("刷新通知")} disabled={loading||writing} onClick={()=>{load();onChanged()}}><RefreshCw size={16}/></button></div>
  {admin&&<MailDeliveryStatus/>}
  <div className="panel"><div className="inbox-controls"><div className="inbox-tabs" aria-label={systemText("通知范围")}>
   {tabs.map(([id,name])=><button type="button" key={id} aria-pressed={id===tab} disabled={writing} onClick={()=>filter({tab:id})}>{systemText(name)}{data&&<span>{data.counts[id]}</span>}</button>)}</div>
   <div className="inbox-filters"><WarehouseSelect aria-label={systemText("通知仓库")} value={warehouse} disabled={writing} onChange={e=>filter({warehouse:e.target.value})}><option value="">{systemText("全部授权仓库")}</option>{warehouses.map(w=><option value={w.code} key={w.code}>{warehouseName(w.name)}</option>)}</WarehouseSelect>
   <select aria-label={systemText("通知类别")} value={kind} disabled={writing} onChange={e=>filter({kind:e.target.value})}><option value="">{systemText("全部类别")}</option>{Object.entries(kinds).map(([v,label])=><option key={v} value={v}>{systemText(label)}</option>)}</select>
   <button type="button" className="text-button" disabled={writing||loading||!unreadOnView} onClick={()=>mark()}><CheckCheck size={15}/>{systemText("此筛选全部已读")}</button></div></div>
   {error&&<Notice tone="error" message={error}/>}
   {data?.items.length?<ul className="inbox-list">{data.items.map(n=><li key={n.id} className={n.seen?'seen':'unread'}>
    <span className={'inbox-dot'+(n.seen?' seen':'')} aria-label={n.seen?systemText("已读"):systemText("未读")}/>
    <div className="inbox-body"><div className="inbox-meta"><span className="inbox-kind" data-kind={n.kind}>{systemText(kinds[n.kind])}</span><WarehouseLabel code={n.warehouse} name={n.warehouse_name}/><time>{date(n.at)}</time></div>
     <button className="inbox-title" onClick={()=>onOpen(n)}>{n.title}</button><div className="inbox-text">{detail(n)}</div></div>
    <div className="inbox-actions"><span className="inbox-plan-state">{n.action==='CLAIM'?systemText("待领取"):n.state==='IN_REVIEW'&&n.reviewer_name?tr(n.reviewer_name+' 复审中','In review · '+n.reviewer_name):planStateLabel(n.state)}</span>
      <button className="text-button" id={'notice-'+n.id} onClick={()=>onOpen(n)}>{n.action?systemText(actions[n.action]):systemText("查看计划")}<ArrowRight size={14}/></button>
      {!n.seen&&<button className="inbox-mark" disabled={writing} onClick={()=>mark(n)} aria-label={tr('标为已读 '+n.title,'Mark as read: '+n.title)} title={systemText("标为已读")}><Check size={15}/></button>}</div>
    </li>)}</ul>:!error&&<Empty title={loading?systemText("正在读取通知…"):tab==='action'?systemText("暂无待处理通知"):tab==='unread'?systemText("暂无未读通知"):systemText("暂无通知")}/>}
   {!!data?.total&&<div className="table-footer"><span>{systemText("共")} {data.total} {systemText("条")}</span><span className="spacer"/><button className="icon-button" disabled={loading||writing||currentPage===1} aria-label={systemText("上一页通知")} onClick={()=>filter({page:currentPage-1})}><ChevronLeft size={16}/></button><span>{currentPage} / {last}</span><button className="icon-button" disabled={loading||writing||currentPage>=last} aria-label={systemText("下一页通知")} onClick={()=>filter({page:currentPage+1})}><ChevronRight size={16}/></button></div>}
  </div>
 </section>
}
