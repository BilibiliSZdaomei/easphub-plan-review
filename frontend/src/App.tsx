import PersonalAccount from './PersonalAccount'
import UsageInsights from './UsageInsights'
import {useUsageTracking} from './useUsageTracking'
import BrandLoading,{useDelayedLoading} from './BrandLoading'
import LanguageSwitcher from './LanguageSwitcher'
import {tr,systemText,systemMessage,useLanguage,warehouseName} from './i18n'
import {periodLabel,defaultPlanTitle} from './periods'
import WarehouseLabel,{WarehouseCatalog,WarehouseSelect} from './WarehouseLabel'
import { easphubPlatformUrl } from "./platformLink";
import signInCover from './sign-in-port.webp'
import './sign-in.css'
import {useState,useEffect,FormEvent,useCallback,useRef,type CSSProperties} from 'react'
import {SidebarResize,useSidebarSize} from './SidebarResize'
import {canPlan,canReview as hasReviewRole} from './roles'
import {ArrowRight,ArrowUpRight,Plus,Search,ClipboardCheck,CheckCircle2,SlidersHorizontal,Database,Users,ChevronDown,Bell,RefreshCw,Layers3,Eye,EyeOff,LayoutDashboard,History,Menu,PanelLeftClose,PanelLeftOpen,Sun,Moon,ChartColumn,UserRound,LockKeyhole} from 'lucide-react'
import {api,setCsrf,planStateLabel,date,localDay,completedStates} from './api'
import {Badge,Empty,Modal,Notice,useFormExit} from './ui'
import PlanView from './PlanView'
import NotificationCenter,{NotificationPreview,defaultInbox,type InboxItem,type InboxPage} from './NotificationCenter'
import {currentWeek,weekLabel} from './periods'
import DataCenter from './DataCenter'
import RuleCenter from './RuleCenter'
import Accounts from './Accounts'
import PasswordField from './PasswordField'
import SnapshotPicker from './SnapshotPicker'

export default function App(){
 useLanguage()
 const [user,setUser]=useState<any>(null),[checking,setChecking]=useState(true)
 const [signingIn,setSigningIn]=useState(false),[openingWorkspace,setOpeningWorkspace]=useState(true)
 const showBrand=useDelayedLoading(checking||signingIn||Boolean(user&&openingWorkspace))
 const [passwordChangedFor,setPasswordChangedFor]=useState('')
 const [view,setView]=useState('home'),[unsaved,setUnsaved]=useState(false),[scopeWarehouse,setScopeWarehouse]=useState(''),[fromDay,setFromDay]=useState(''),[toDay,setToDay]=useState(''),[batchId,setBatchId]=useState<string|null>(null),[batches,setBatches]=useState<any[]>([]),[warehouses,setWarehouses]=useState<any[]>([])
 const [error,setError]=useState(''),[toast,setToast]=useState(''),[newOpen,setNewOpen]=useState(false),[passwordOpen,setPasswordOpen]=useState<false|'manual'|'account-password'>(false),[refresh,setRefresh]=useState(false),[search,setSearch]=useState(''),[state,setState]=useState('all')
 const [eaTheme,setEaTheme]=useState<'light'|'dark'>(()=>document.documentElement.dataset.eaMode==='dark'?'dark':'light')
 const [eaNavOpen,setEaNavOpen]=useState(false)
 const sidebar=useSidebarSize()
 const [inboxPreview,setInboxPreview]=useState<InboxPage|null>(null),[inboxFilters,setInboxFilters]=useState(defaultInbox)
 const inboxEpoch=useRef(0)
 const [scopePeriod,setScopePeriod]=useState('')
 const [profileOpen,setProfileOpen]=useState(false)
 const flushUsage=useUsageTracking(checking||openingWorkspace?undefined:user?.id,profileOpen?'profile':view,batchId)
 const [planOrigin,setPlanOrigin]=useState('plans')
 const listPosition=useRef({scroll:0,focusId:''})
 const restorePosition=useRef(false)
 useEffect(()=>{
  if(!restorePosition.current||view==='plan')return
  restorePosition.current=false
  const previous=listPosition.current
  const frame=requestAnimationFrame(()=>{
   window.scrollTo(0,previous.scroll)
   document.getElementById(previous.focusId)?.focus({preventScroll:true})
  })
  return()=>cancelAnimationFrame(frame)
 },[view])
 const loadEpoch=useRef(0)
 useEffect(()=>{if(!eaNavOpen)return;const dismiss=(e:KeyboardEvent)=>{if(e.key==='Escape'){setEaNavOpen(false);document.getElementById('ea-nav-toggle')?.focus()}};window.addEventListener('keydown',dismiss);return()=>window.removeEventListener('keydown',dismiss)},[eaNavOpen])
 useEffect(()=>{document.documentElement.dataset.eaMode=eaTheme;window.localStorage.setItem('easphub.app.theme',eaTheme)},[eaTheme])
 const notify=useCallback((s:string)=>{setToast(s);setTimeout(()=>setToast(''),5000)},[])
 const fail=useCallback((e:any)=>{setError(e.message||String(e));if(e.status===401){setSigningIn(false);setUser(null);setBatchId(null)}},[])
 const refreshInbox=useCallback(async()=>{
  const epoch=++inboxEpoch.current
  try{const next=await api<InboxPage>('/notification-inbox?size=5')
   if(epoch===inboxEpoch.current)setInboxPreview(next)
  }catch(e:any){if(epoch===inboxEpoch.current){setInboxPreview(null);fail(e)}}
 },[fail])
 useEffect(()=>{
  if(!user)return
  const refresh=()=>{if(document.visibilityState==='visible')refreshInbox()}
  const timer=window.setInterval(refresh,30000)
  document.addEventListener('visibilitychange',refresh)
  return ()=>{inboxEpoch.current++;window.clearInterval(timer);document.removeEventListener('visibilitychange',refresh)}
 },[user,refreshInbox])
 async function load(){const epoch=++loadEpoch.current;setRefresh(true);refreshInbox();try{const [b,w]=await Promise.all([api('/batches'),api('/warehouses')]);if(epoch!==loadEpoch.current)return;setBatches(b);setWarehouses(w)}catch(e){if(epoch===loadEpoch.current)fail(e)}finally{if(epoch===loadEpoch.current){setRefresh(false);setOpeningWorkspace(false);setSigningIn(false)}}}
 useEffect(()=>{api('/session-state').then(r=>{setUser(r.user);setCsrf(r.csrf)}).catch(()=>{}).finally(()=>setChecking(false))},[])
 useEffect(()=>{if(user)load()},[user])
 useEffect(()=>{if(!unsaved)return;const block=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};window.addEventListener('beforeunload',block);return()=>window.removeEventListener('beforeunload',block)},[unsaved])
 useEffect(()=>{
  if(!user?.id||checking||openingWorkspace)return
  const url=new URL(window.location.href),id=url.searchParams.get('plan')
  if(!id||!/^[0-9a-f]{32}$/.test(id))return
  url.searchParams.delete('plan')
  window.history.replaceState(window.history.state,'',url.pathname+url.search+url.hash)
  openBatch(id,true)
 },[user?.id,checking,openingWorkspace])
 const admin=user?.roles.includes('ADMIN')
 const reviewer=hasReviewRole(user?.roles??[])
 const planner=canPlan(user?.roles??[])
 function leave(){return !unsaved||window.confirm(systemText("有未保存的修改，放弃并离开？"))}
 function nav(name:string,filter='all',keepScope=false,confirmed=false){
  if(name!==view&&!confirmed&&!leave())return
  setEaNavOpen(false)
  document.getElementById('ea-account-menu')?.removeAttribute('open')
  if(name!==view)setUnsaved(false)
  if(!keepScope){setScopeWarehouse('');setFromDay('');setToDay('');setScopePeriod('')}
  setView(name);setBatchId(null);setError('');setSearch('');setState(filter);load()
 }
 function openBatch(id:string,confirmed=false){
  if(view==='plan'&&batchId===id)return true
  if(!confirmed&&!leave())return false
  if(view!=='plan'){
   setPlanOrigin(view)
   listPosition.current={scroll:window.scrollY,focusId:document.activeElement?.id||''}
  }
  setEaNavOpen(false);setUnsaved(false);setBatchId(id);setView('plan');setError('')
  window.scrollTo(0,0)
  return true
 }
 function backToList(){
  restorePosition.current=true
  setUnsaved(false);setBatchId(null);setError('');setView(planOrigin)
  load()
 }
 async function openNote(note:InboxItem){
  if(!leave())return
  try{await api('/notifications/'+note.id+'/seen',{});openBatch(note.batch_id,true);refreshInbox()}
  catch(e){fail(e);refreshInbox()}
 }

 async function logout(){if(!leave())return;void flushUsage();try{await api('/sessions/current',undefined,'DELETE');loadEpoch.current++;setUser(null);setUnsaved(false);setBatchId(null);setView('home')}catch(e){fail(e)}}
 if(checking||!user||openingWorkspace)return <>
  {!checking&&(!user||signingIn)&&<div hidden={showBrand}><Login busy={signingIn} onBusy={setSigningIn} languageControl={<LanguageSwitcher/>} passwordChangedFor={passwordChangedFor} eaTheme={eaTheme} onThemeChange={()=>setEaTheme(eaTheme==='light'?'dark':'light')} onLogin={(u,accountPassword)=>{setOpeningWorkspace(true);setPasswordChangedFor('');loadEpoch.current++;setBatches([]);setInboxPreview(null);setInboxFilters(defaultInbox);setWarehouses([]);setView('home');setBatchId(null);setScopeWarehouse('');setFromDay('');setToDay('');setUnsaved(false);setNewOpen(false);setPasswordOpen(accountPassword?'account-password':false);setScopePeriod('');setPlanOrigin('plans');setEaNavOpen(false);setSearch('');setState('all');setUser(u);setError('')}}/></div>}
  {showBrand&&<BrandLoading theme={eaTheme}/>}
 </>
 const scopeRows=batches.filter(b=>(!scopeWarehouse||b.warehouse===scopeWarehouse)&&(!fromDay||localDay(b.updated_at)>=fromDay)&&(!toDay||localDay(b.updated_at)<=toDay))
 const scoped=scopePeriod?scopeRows.filter(b=>b.period===scopePeriod):scopeRows
 const archive=(b:any)=>(completedStates.includes(b.state)||b.state==='VOID')
 const periodOptions=new Map<string,{label:string;start:string}>()
 for(const batch of batches){
  if((scopeWarehouse&&batch.warehouse!==scopeWarehouse)||(view==='history'&&!archive(batch)))continue
  periodOptions.set(batch.period,{label:periodLabel(batch.period,batch.period_info?.label),start:batch.period_info?.start||batch.period})
 }
 const periods=[...periodOptions.entries()].sort(([a,x],[b,y])=>y.start.localeCompare(x.start)||b.localeCompare(a))
 const current=scoped.filter(b=>!archive(b))
 const canReview=(b:any)=>reviewer&&b.owner!==user.id&&(!b.reviewer_id||b.reviewer_id===user.id)&&['SUBMITTED','IN_REVIEW'].includes(b.state)
 const canEdit=(b:any)=>planner&&b.owner===user.id&&['DRAFT','RETURNED'].includes(b.state)
 const isPending=(b:any)=>canReview(b)||canEdit(b)
 const pending=scoped.filter(isPending)
 const taskCount=reviewer||planner?pending.length:current.length
 const returnedCount=scoped.filter(b=>b.state==='RETURNED').length
 const planUnit=(n:number)=>tr('份计划',n===1?'plan':'plans')
 const closed=scoped.filter(b=>completedStates.includes(b.state))
 const priority=(b:any)=>canReview(b)?0:canEdit(b)?(b.state==='RETURNED'?1:2):3
 const hasWorkQueue=planner||reviewer
 const baseList=view==='history'?scoped.filter(archive):view==='home'?(hasWorkQueue?pending:current):scoped
 const homeStates=hasWorkQueue?[...(planner?['DRAFT','RETURNED']:[]),...(reviewer?['SUBMITTED','IN_REVIEW']:[])]:['DRAFT','SUBMITTED','IN_REVIEW','RETURNED']
 const closedFilters=completedStates.filter(value=>value!=='PARTIALLY_APPROVED'||state===value||scoped.some(b=>b.state===value))
 const awaitingWarehouse=user.warehouses.length===0
 const listFilterActive=!!(search.trim()||state!=='all'||scopeWarehouse||scopePeriod||fromDay||toDay)
 function clearFilters(){setSearch('');setState('all');setScopeWarehouse('');setScopePeriod('');setFromDay('');setToDay('')}
 const matchesState=(b:any)=>state==='all'||(state==='pending'?isPending(b):state==='active'?!archive(b):state==='completed'?completedStates.includes(b.state):b.state===state)
 const visible=baseList.filter(b=>matchesState(b)&&[b.title,b.number,b.warehouse_name,warehouseName(b.warehouse_name)].join(' ').toLowerCase().includes(search.trim().toLowerCase())).sort((a,b)=>{
  if(view==='history')return b.updated_at.localeCompare(a.updated_at)
  return priority(a)-priority(b)||(canReview(a)?a.updated_at.localeCompare(b.updated_at):b.updated_at.localeCompare(a.updated_at))
 })
 const platformUrl=easphubPlatformUrl(eaTheme)
 const plansLabel=systemText(reviewer?'计划复审':'计划列表')
 const section=view==='plan'?planOrigin:view
 const sectionName=section==='myUsage'?tr('我的使用情况','My usage'):section==='teamUsage'?tr('使用分析','Usage insights'):systemText(section==='history'?'历史记录':section==='plans'?plansLabel:section==='data'?'数据中心':section==='rules'?'审核标准':section==='accounts'?'人员与权限':section==='inbox'?'通知中心':'工作台')
 return <WarehouseCatalog.Provider value={warehouses}><div ref={sidebar.shellRef} style={sidebar.width?{'--plan-sidebar-user-width':sidebar.width+'px'} as CSSProperties:undefined}
   className={'app-shell'+(eaNavOpen?' ea-sidebar-open':'')+(sidebar.collapsed?' sidebar-collapsed':'')}>
  <div className={'top-progress '+(refresh?'moving':'')}/>
  <button className="ea-nav-backdrop" hidden={!eaNavOpen} type="button" aria-label={systemText("关闭导航")} onClick={()=>{setEaNavOpen(false);document.getElementById('ea-nav-toggle')?.focus()}}/><header className="main-nav" id="ea-app-navigation"><a className="brand" href="#" onClick={e=>{e.preventDefault();nav('home')}}><span className="ea-platform-logo" role="img" aria-label="EASPhub"/></a><div className="ea-app-identity"><ClipboardCheck size={18}/><div><strong>{systemText("计划审核")}</strong></div></div>
   <nav aria-label={systemText("主导航")}><button className={section==='home'?'active':''} onClick={()=>nav('home')}><LayoutDashboard size={17}/>{systemText("工作台")}</button><button className={section==='plans'?'active':''} onClick={()=>nav('plans')}><ClipboardCheck size={17}/>{plansLabel}</button><button className={section==='history'?'active':''} onClick={()=>nav('history')}><History size={17}/>{systemText("历史记录")}</button>{reviewer&&<details className="management"><summary><SlidersHorizontal size={17}/>{systemText("管理")}<ChevronDown size={12}/></summary><div className="dropdown"><button aria-current={section==='data'?'page':undefined} onClick={()=>nav('data')}><Database size={15}/>{systemText("数据中心")}</button><button aria-current={section==='rules'?'page':undefined} onClick={()=>nav('rules','all',true)}><SlidersHorizontal size={15}/>{systemText("审核标准")}</button>{admin&&<button aria-current={section==='accounts'?'page':undefined} onClick={()=>nav('accounts')}><Users size={15}/>{systemText("人员与权限")}</button>}{admin&&<button aria-current={section==='teamUsage'?'page':undefined} onClick={()=>nav('teamUsage')}><ChartColumn size={15}/>{tr('使用分析','Usage insights')}</button>}</div></details>}</nav>
   <div className="nav-right">{platformUrl && <a className="platform-back" href={platformUrl}>{systemText("← EASPhub 工作台")}</a>}<PersonalAccount key={user.id} user={user} onProfileChange={setProfileOpen} onUsage={admin?()=>nav('myUsage'):undefined} onPassword={()=>setPasswordOpen('manual')} onLogout={logout}
    onUpdate={updated=>{setUser((current:any)=>current?.id===updated.id?updated:current);notify(tr('头像已更新','Avatar updated'))}}/></div>
  </header>
  {!sidebar.collapsed&&<SidebarResize shellRef={sidebar.shellRef} onCommit={sidebar.saveWidth}/>}
  <div className="ea-topbar"><button type="button" className="sidebar-collapse" aria-label={sidebar.collapsed?systemText("展开侧栏"):systemText("收起侧栏")} title={sidebar.collapsed?systemText("展开侧栏"):systemText("收起侧栏")} aria-controls="ea-app-navigation" aria-expanded={!sidebar.collapsed} onClick={sidebar.toggle}>{sidebar.collapsed?<PanelLeftOpen size={18}/>:<PanelLeftClose size={18}/>}</button><button type="button" id="ea-nav-toggle" className="ea-nav-toggle" aria-label={systemText("打开应用导航")} aria-controls="ea-app-navigation" aria-expanded={eaNavOpen} onClick={()=>setEaNavOpen(!eaNavOpen)}><Menu size={20}/></button><div className="ea-topbar__crumb"><span>{systemText("工作空间")}</span><span aria-hidden="true">/</span><span>{systemText("计划审核")}</span><span aria-hidden="true">/</span><strong>{sectionName}</strong></div><div className="ea-topbar__actions"><LanguageSwitcher/><button type="button" className="inbox-bell" aria-current={section==='inbox'?'page':undefined} aria-label={tr('通知中心，未读 '+(inboxPreview?.counts.unread??0)+' 条','Notifications, '+(inboxPreview?.counts.unread??0)+' unread')} title={systemText("通知中心")} onClick={()=>nav('inbox')}><Bell size={18}/>{!!inboxPreview?.counts.unread&&<b>{inboxPreview.counts.unread>99?'99+':inboxPreview.counts.unread}</b>}</button><button className="ea-theme-toggle" type="button" role="switch" aria-checked={eaTheme==='dark'} onClick={()=>setEaTheme(eaTheme==='light'?'dark':'light')} aria-label={systemText("深色外观")}><span className="ea-theme-track" aria-hidden="true"><span className="ea-theme-thumb"/><span className="ea-theme-day"><Sun size={15}/></span><span className="ea-theme-night"><Moon size={15}/></span></span></button></div></div>
  <main className="main-content">
   {error&&<div className="dismiss-notice"><Notice message={error} tone="error"/><button onClick={()=>setError('')} aria-label={systemText("关闭提示")}>×</button></div>}
   {view==='plan'&&batchId?<PlanView key={batchId} batchId={batchId} user={user} backLabel={tr('返回'+sectionName,'Back to '+sectionName)} onBack={backToList} onUpdate={load} notify={notify} onDirty={setUnsaved} onOpenBatch={id=>openBatch(id,true)}/>:
    view==='inbox'?<NotificationCenter admin={admin} filters={inboxFilters} onFilter={setInboxFilters} warehouses={warehouses} onOpen={openNote} onChanged={refreshInbox}/>:view==='data'?<DataCenter warehouses={warehouses} notify={notify} user={user}/>:
    view==='rules'?<RuleCenter warehouses={warehouses} warehouse={scopeWarehouse} notify={notify} user={user} onDirty={setUnsaved}/>:
    admin&&(view==='myUsage'||view==='teamUsage')?<UsageInsights key={view} scope={view==='myUsage'?'personal':'admin'}/>:view==='accounts'?<Accounts warehouses={warehouses} notify={notify} user={user}/>:
    <>
     <div className="page-heading"><div><h1>{view==='history'?systemText("历史记录"):view==='plans'?plansLabel:systemText("计划工作台")}</h1></div><div className="actions"><button className="secondary compact" aria-label={systemText("刷新计划")} onClick={load}><RefreshCw size={16} className={refresh?'spin':''}/></button>{planner&&<button data-usage-target="create" className="primary" disabled={!warehouses.length} onClick={()=>setNewOpen(true)}><Plus size={17}/>{systemText("新建计划")}</button>}</div></div>
     <div className="scope-controls">
      <span>{view==='home'?systemText("统计范围"):systemText("仓库")}</span><WarehouseSelect aria-label={systemText("统计仓库")} value={scopeWarehouse} onChange={e=>{setScopeWarehouse(e.target.value);setScopePeriod('')}}><option value="">{systemText("全部授权仓库")}</option>{warehouses.map(w=><option key={w.code} value={w.code}>{warehouseName(w.name)}</option>)}</WarehouseSelect>
      {view!=='home'&&<label>{systemText("计划周期")}<select aria-label={systemText("筛选计划周期")} value={scopePeriod} onChange={e=>setScopePeriod(e.target.value)}><option value="">{systemText("全部周期")}</option>{periods.map(([value,period])=><option key={value} value={value}>{period.label}</option>)}</select></label>}
      <label>{systemText("更新日期")}<input aria-label={systemText("开始日期")} type="date" value={fromDay} max={toDay||undefined} onChange={e=>setFromDay(e.target.value)}/></label><span>{systemText("至")}</span><input aria-label={systemText("结束日期")} type="date" min={fromDay} value={toDay} onChange={e=>setToDay(e.target.value)}/>
      {(scopeWarehouse||fromDay||toDay||scopePeriod)&&<button className="text-button" onClick={()=>{setScopeWarehouse('');setFromDay('');setToDay('');setScopePeriod('')}}>{systemText("重置范围")}</button>}
     </div>{view==='home'&&<div className="stats-strip"><button onClick={()=>nav('plans',reviewer||planner?'pending':'active',true)}><span className="stat-icon rose"><ClipboardCheck size={21}/></span><div><small>{reviewer&&!planner?systemText("等待复审"):reviewer||planner?systemText("待我处理"):systemText("进行中")}</small><strong>{taskCount}<em>{planUnit(taskCount)}</em></strong></div><ArrowUpRight size={16}/></button><button onClick={()=>nav('plans','RETURNED',true)}><span className="stat-icon coral"><History size={21}/></span><div><small>{systemText("退回修改")}</small><strong>{returnedCount}<em>{planUnit(returnedCount)}</em></strong></div><ArrowUpRight size={16}/></button><button onClick={()=>nav('history','completed',true)}><span className="stat-icon teal"><CheckCircle2 size={21}/></span><div><small>{systemText("已完成审核")}</small><strong>{closed.length}<em>{planUnit(closed.length)}</em></strong></div><ArrowUpRight size={16}/></button><div><span className="stat-icon blue"><Layers3 size={21}/></span><div><small>{systemText("授权仓库")}</small><strong>{warehouses.length}<em>{tr('个仓库',warehouses.length===1?'warehouse':'warehouses')}</em></strong></div></div></div>}
     <div className={view==='home'?'workspace-grid':''}><section className="panel"><div className="panel-heading"><div><h2>{view==='home'?(hasWorkQueue?systemText("我的待处理"):systemText("当前计划")):view==='history'?systemText("审核档案"):systemText("计划列表")}</h2><span>{visible.length} {planUnit(visible.length)}</span></div>{view==='home'&&<button className="text-button" onClick={()=>nav('plans','all',true)}>{systemText("全部计划")}<ArrowRight size={14}/></button>}</div>
      <div className="list-toolbar"><label className="search"><Search size={16}/><input aria-label={systemText("搜索计划名称、编号或仓库")} placeholder={systemText("搜索计划名称、编号或仓库")} value={search} onChange={e=>setSearch(e.target.value)}/></label><select aria-label={systemText("筛选计划状态")} value={state} onChange={e=>setState(e.target.value)}><option value="all">{systemText("全部状态")}</option>{view==='plans'&&hasWorkQueue&&<option value="pending">{systemText("待我处理")}</option>}{view==='plans'&&<option value="active">{systemText("进行中")}</option>}{view==='history'&&<option value="completed">{systemText("已完成审核")}</option>}{(view==='history'?[...closedFilters,'VOID']:view==='home'?homeStates:['DRAFT','SUBMITTED','IN_REVIEW','RETURNED',...closedFilters,'VOID']).map(s=><option key={s} value={s}>{planStateLabel(s)}</option>)}</select></div>
      {visible.length?<div className="table-scroll"><table className="batch-table"><thead><tr><th>{systemText("计划 / 仓库")}</th><th>{systemText("状态")}</th><th>{reviewer&&view!=='history'?systemText("未复审"):systemText("计划行")}</th><th>{systemText("需关注")}</th><th>{systemText("更新时间")}</th><th/></tr></thead><tbody>{visible.map(b=><tr key={b.id}><td><button id={'plan-title-'+b.id} className="row-link" onClick={()=>openBatch(b.id)}>{b.title}</button><small><WarehouseLabel code={b.warehouse} name={b.warehouse_name}/> <span>·</span> {b.number} <span>·</span> {periodLabel(b.period,b.period_info?.label)}</small></td><td><Badge value={b.state} label={b.state==='SUBMITTED'?systemText("待领取"):planStateLabel(b.state)}/>{b.reviewer_name&&<small>{b.reviewer_name}</small>}{b.state==='IN_REVIEW'&&!b.reviewer_id&&<small>{systemText("待领取")}</small>}</td><td className="mono">{reviewer&&view!=='history'?(['SUBMITTED','IN_REVIEW'].includes(b.state)?Math.max(0,b.summary.total-b.summary.reviewed):'—'):b.summary.total}</td><td><span className={b.summary.attention?'attention-count mono':'mono'}>{b.summary.attention}</span></td><td className="muted">{date(b.updated_at)}</td><td><button id={'plan-action-'+b.id} className="text-button" onClick={()=>openBatch(b.id)}>{canReview(b)?(b.reviewer_id?systemText("继续复审"):systemText("查看并领取")):canEdit(b)?systemText("继续编辑"):systemText("查看")}<ArrowRight size={14}/></button></td></tr>)}</tbody></table></div>:<Empty title={awaitingWarehouse?tr('尚未分配仓库','No warehouse assigned yet'):listFilterActive?systemText("没有符合条件的计划"):view==='history'?systemText("暂无审核档案"):view==='home'&&hasWorkQueue?systemText("暂无待处理计划"):systemText("暂无计划")}>{awaitingWarehouse?<span>{tr('请联系管理员分配仓库权限。','Ask your administrator to assign you a warehouse.')}</span>:listFilterActive?<button className="text-button" onClick={clearFilters}>{systemText("清除筛选")}</button>:planner&&view!=='history'&&<button data-usage-target="create" className="secondary" disabled={!warehouses.length} onClick={()=>setNewOpen(true)}><Plus size={16}/>{systemText("新建计划")}</button>}</Empty>}
     </section>{view==='home'&&<NotificationPreview data={inboxPreview} onOpen={openNote} onAll={()=>nav('inbox')}/>}</div>
    </>}
  </main><footer><span><i className="live-dot"/>{systemText("EASP Hub · 计划业务提效")}</span><span>v2.1.0</span></footer>
  {toast&&<div className="toast" role="status"><CheckCircle2 size={18}/>{systemMessage(toast)}</div>}
  {newOpen&&<NewPlan warehouses={warehouses} initialWarehouse={scopeWarehouse} onClose={()=>setNewOpen(false)} onCreated={b=>{setNewOpen(false);load();openBatch(b.id)}}/>}

  {passwordOpen&&<Password username={user.username} accountPassword={passwordOpen==='account-password'} beforeSubmit={leave} onClose={()=>setPasswordOpen(false)} onDone={()=>{setPasswordOpen(false);loadEpoch.current++;setUnsaved(false);setPasswordChangedFor(user.username);setUser(null)}}/>}
 </div></WarehouseCatalog.Provider>
}

function Login({onLogin,eaTheme,onThemeChange,passwordChangedFor,languageControl,busy,onBusy}:{languageControl?:import('react').ReactNode;passwordChangedFor:string;onLogin:(u:any,accountPassword:boolean)=>void;eaTheme:'light'|'dark';onThemeChange:()=>void;busy:boolean;onBusy:(value:boolean)=>void}) {
 const [username,setUsername]=useState(passwordChangedFor),[password,setPassword]=useState('')
 const [showPassword,setShowPassword]=useState(false),[error,setError]=useState('')
 const passwordInput=useRef<HTMLInputElement>(null)
 useEffect(()=>{if(error&&!busy)passwordInput.current?.focus()},[error,busy])
 async function enter(event:FormEvent) {
  event.preventDefault()
  if(busy||!username.trim()||!password)return
  onBusy(true);setError('')
  try {
   const result=await api('/sessions',{username:username.trim(),password})
   setCsrf(result.csrf);onLogin(result.user,password===result.user.username)
  } catch(e:any) { setError(e.message);onBusy(false) }
 }
 return <main className="sign-in">
  <header className="sign-in__cover">
   <img className="sign-in__photo" src={signInCover} alt="" width="1122" height="1402" fetchPriority="high"/>
   <span className="ea-platform-logo" role="img" aria-label="EASPhub"/>
   <div className="sign-in__identity"><p>{systemText("欧洲备件业务")}</p><h1>{systemText("计划审核")}</h1></div>
  </header>
  <section className="sign-in__workspace" aria-labelledby="sign-in-heading">
   <div className="sign-in__tools">{languageControl}<button className="ea-theme-toggle sign-in__theme" type="button" role="switch" aria-checked={eaTheme==='dark'} onClick={onThemeChange} aria-label={systemText("深色外观")}>
    <span className="ea-theme-track" aria-hidden="true"><span className="ea-theme-thumb"/><span className="ea-theme-day"><Sun size={15}/></span><span className="ea-theme-night"><Moon size={15}/></span></span>
   </button></div>
   <form className="sign-in__form" onSubmit={enter}>
    <h2 id="sign-in-heading">{systemText("账号登录")}</h2>
    {passwordChangedFor&&<Notice tone="success" message={systemText("密码已更新，请用新密码登录。")}/>}
    <div className="sign-in__field">
     <label htmlFor="sign-in-account">{systemText("账号")}</label>
     <div className="sign-in__input"><UserRound aria-hidden="true" size={18}/>
      <input id="sign-in-account" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required value={username} onChange={e=>setUsername(e.target.value)} />
     </div>
    </div>
    <div className="sign-in__field">
     <label htmlFor="sign-in-password">{systemText("密码")}</label>
     <div className="sign-in__input"><LockKeyhole aria-hidden="true" size={18}/>
      <input ref={passwordInput} id="sign-in-password" name="password" type={showPassword?'text':'password'} autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/>
      <button type="button" className="sign-in__reveal" aria-label={showPassword?tr('隐藏密码','Hide password'):tr('显示密码','Show password')} aria-pressed={showPassword} onClick={()=>setShowPassword(!showPassword)}>{showPassword?<EyeOff size={18}/>:<Eye size={18}/>}</button>
     </div>
    </div>
    {error&&<Notice message={systemText(error)} tone="error"/>}
    <button type="submit" className="primary sign-in__submit" disabled={busy}>{busy?tr('正在登录…','Signing in…'):tr('登录','Sign in')}<ArrowRight size={17} aria-hidden="true"/></button>
    <details className="usage-disclosure"><summary>{tr('使用统计说明','About usage statistics')}</summary><p>{tr('登录后记录访问的页面、操作次数和点击区域。你可以查看自己的使用情况，管理员可查看授权范围内的人员统计。系统不采集输入内容或录屏。','After sign-in, the app counts screen visits, actions and click regions. You can see your activity. Administrators can see usage within their access scope. Typed content and screen recordings are excluded.')}</p></details>
   </form>
  </section>
 </main>
}
function NewPlan({warehouses,initialWarehouse,onClose,onCreated}:{warehouses:any[];initialWarehouse:string;onClose:()=>void;onCreated:(b:any)=>void}){
 const [initial]=useState(()=>({
  warehouse:warehouses.some(w=>w.code===initialWarehouse)?initialWarehouse:warehouses.length===1?warehouses[0].code:'',
  title:defaultPlanTitle(localDay(new Date().toISOString()).slice(0,7)),period:localDay(new Date().toISOString()).slice(0,7),
 }))
 const [warehouse,setWarehouse]=useState(initial.warehouse),[snaps,setSnaps]=useState<any[]>([]),[snapshot,setSnapshot]=useState(''),[loadingSnaps,setLoadingSnaps]=useState(false),[reuse,setReuse]=useState(false),[title,setTitle]=useState(initial.title),[period,setPeriod]=useState(initial.period),[periodKind,setPeriodKind]=useState('month'),[titleEdited,setTitleEdited]=useState(false),[usePlan,setUsePlan]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const dirty=warehouse!==initial.warehouse||title!==initial.title||period!==initial.period||periodKind!=='month'||!usePlan||!!snapshot
 const close=useFormExit(dirty,busy,onClose)
 useEffect(()=>{let active=true;setSnaps([]);setSnapshot('');setError('');if(!warehouse||!reuse){setLoadingSnaps(false);return}setLoadingSnaps(true);api('/snapshots?warehouse='+encodeURIComponent(warehouse)).then(r=>{if(active)setSnaps(r)}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoadingSnaps(false)});return()=>{active=false}},[warehouse,reuse])
 async function create(e:FormEvent){e.preventDefault();if(busy||!warehouse||(snapshot&&!snaps.some(s=>s.id===snapshot&&s.warehouse===warehouse)))return;setBusy(true);setError('');try{const b=await api('/batches',{warehouse,snapshot_id:snapshot||null,title:title.trim(),period,use_snapshot_plan:!!snapshot&&usePlan});onCreated(b)}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <Modal title={systemText("新建计划")} onClose={close}><form onSubmit={create} className="modal-body">{error&&<Notice message={error} tone="error"/>}<div className="form-grid"><label>{systemText("仓库")}<WarehouseSelect value={warehouse} required disabled={busy} onChange={e=>{if(e.target.value!==warehouse){setWarehouse(e.target.value);setSnapshot('');setSnaps([])}}}><option value="">{systemText("请选择仓库")}</option>{warehouses.map(w=><option key={w.code} value={w.code}>{warehouseName(w.name)}</option>)}</WarehouseSelect></label><label>{systemText("周期")}<select value={periodKind} disabled={busy} onChange={e=>{const kind=e.target.value;const next=kind==='week'?currentWeek():localDay(new Date().toISOString()).slice(0,7);setPeriodKind(kind);setPeriod(next);if(!titleEdited)setTitle(defaultPlanTitle(next))}}><option value="month">{systemText("按月")}</option><option value="week">{systemText("按周")}</option></select></label><label>{systemText("计划周期")}<input type={periodKind} value={period} disabled={busy} onChange={e=>{const next=e.target.value;setPeriod(next);if(!titleEdited&&next)setTitle(defaultPlanTitle(next))}} required/>{periodKind==='week'&&<small>{weekLabel(period)}</small>}</label></div><label>{systemText("计划名称")}<input value={title} disabled={busy} onChange={e=>{setTitle(e.target.value);setTitleEdited(true)}} maxLength={120} required/></label><details className="reuse-data" onToggle={e=>{setReuse(e.currentTarget.open);if(!e.currentTarget.open)setSnapshot('')}}><summary>{systemText("使用已有仓库数据（选填）")}</summary><SnapshotPicker label={systemText("仓库快照")} required={false} snapshots={snaps} value={snapshot} onChange={setSnapshot} disabled={busy||!warehouse} loading={loadingSnaps} emptyText={systemText("暂不关联")} noDataText={warehouse?systemText("本仓暂无快照，可直接创建"):systemText("请先选择仓库")}/>
 {snapshot&&<label className="check-row"><input type="checkbox" disabled={busy} checked={usePlan} onChange={e=>setUsePlan(e.target.checked)}/><span>{systemText("带入快照计划")}</span></label>}</details>
 <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>{systemText("取消")}</button><button className="primary" disabled={busy||!warehouse||!title.trim()||!period}>{busy?systemText("正在创建…"):systemText("创建计划")}<ArrowRight size={16}/></button></div></form></Modal>
}
function Password({username,accountPassword,beforeSubmit,onClose,onDone}:{username:string;accountPassword:boolean;beforeSubmit:()=>boolean;onClose:()=>void;onDone:()=>void}){
 const [old,setOld]=useState(''),[next,setNext]=useState(''),[error,setError]=useState(''),[saving,setSaving]=useState(false)
 const close=useFormExit(!!(old||next),saving,onClose)
 async function save(e:FormEvent){
  e.preventDefault()
  if(saving)return
  if(next===username){setError('新密码不能与登录账号相同');return}
  if(old===next){setError('新密码与当前密码相同');return}
  if(!beforeSubmit())return
  setSaving(true);setError('')
  try{await api('/password',{current_password:old,password:next});onDone()}catch(e:any){setError(e.message)}finally{setSaving(false)}
 }
 return <Modal title={systemText("修改密码")} onClose={close}><form className="modal-body" data-usage-private onSubmit={save} inert={saving||undefined}>
  {error&&<Notice message={systemText(error)} tone="error"/>}
  {accountPassword&&<Notice tone="warn" message={systemText("当前密码与账号相同，建议换成专用密码。")}/>}
  <label>{systemText("登录账号")}<input type="text" readOnly name="username" autoComplete="username" value={username}/></label>
  <label>{systemText("当前密码")}<input type="password" name="current-password" autoComplete="current-password" value={old} onChange={e=>setOld(e.target.value)} required/></label>
  <PasswordField label={systemText("新密码")} required value={next} onChange={setNext} hint={systemText("6–200 位，保存后请用新密码重新登录。")}/>
  <div className="modal-actions"><button type="button" className="secondary" disabled={saving} onClick={close}>{systemText("取消")}</button><button className="primary" disabled={saving}>{systemText("保存新密码")}</button></div>
 </form></Modal>
}
