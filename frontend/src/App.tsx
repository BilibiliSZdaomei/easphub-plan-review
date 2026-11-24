import { easphubPlatformUrl } from "./platformLink";
import signInCover from './sign-in-port.webp'
import './sign-in.css'
import {useState,useEffect,FormEvent,useCallback,useRef} from 'react'
import {ArrowRight,ArrowUpRight,Plus,Search,ClipboardCheck,CheckCircle2,LogOut,SlidersHorizontal,Database,Users,ChevronDown,Bell,RefreshCw,Layers3,Eye,EyeOff,LayoutDashboard,History,KeyRound,Menu,Sun,Moon,UserRound,LockKeyhole} from 'lucide-react'
import {api,setCsrf,labels,date,localDay} from './api'
import {Badge,Busy,Empty,Modal,Notice,useFormExit} from './ui'
import PlanView from './PlanView'
import {currentWeek,weekLabel} from './periods'
import DataCenter from './DataCenter'
import RuleCenter from './RuleCenter'
import Accounts from './Accounts'
import SnapshotPicker from './SnapshotPicker'

export default function App(){
 const [user,setUser]=useState<any>(null),[checking,setChecking]=useState(true)
 const [view,setView]=useState('home'),[unsaved,setUnsaved]=useState(false),[scopeWarehouse,setScopeWarehouse]=useState(''),[fromDay,setFromDay]=useState(''),[toDay,setToDay]=useState(''),[batchId,setBatchId]=useState<string|null>(null),[batches,setBatches]=useState<any[]>([]),[warehouses,setWarehouses]=useState<any[]>([]),[notes,setNotes]=useState<any[]>([])
 const [error,setError]=useState(''),[toast,setToast]=useState(''),[newOpen,setNewOpen]=useState(false),[passwordOpen,setPasswordOpen]=useState(false),[refresh,setRefresh]=useState(false),[search,setSearch]=useState(''),[state,setState]=useState('all')
 const [eaTheme,setEaTheme]=useState<'light'|'dark'>(()=>document.documentElement.dataset.eaMode==='dark'?'dark':'light')
 const platformUrl=easphubPlatformUrl(eaTheme)
 const [eaNavOpen,setEaNavOpen]=useState(false)
 const [notesOpen,setNotesOpen]=useState(false),[unreadOnly,setUnreadOnly]=useState(false)
 const [scopePeriod,setScopePeriod]=useState('')
 const [planOrigin,setPlanOrigin]=useState('plans')
 const listPosition=useRef({scroll:0,focusId:'',notifications:false})
 const restorePosition=useRef(false)
 useEffect(()=>{
  if(!restorePosition.current||view==='plan')return
  restorePosition.current=false
  const previous=listPosition.current
  const frame=requestAnimationFrame(()=>{
   window.scrollTo(0,previous.scroll)
   if(!previous.notifications)document.getElementById(previous.focusId)?.focus({preventScroll:true})
  })
  return()=>cancelAnimationFrame(frame)
 },[view])
 const loadEpoch=useRef(0)
 useEffect(()=>{if(!eaNavOpen)return;const dismiss=(e:KeyboardEvent)=>{if(e.key==='Escape'){setEaNavOpen(false);document.getElementById('ea-nav-toggle')?.focus()}};window.addEventListener('keydown',dismiss);return()=>window.removeEventListener('keydown',dismiss)},[eaNavOpen])
 useEffect(()=>{document.documentElement.dataset.eaMode=eaTheme;window.localStorage.setItem('easphub.app.theme',eaTheme)},[eaTheme])
 const notify=useCallback((s:string)=>{setToast(s);setTimeout(()=>setToast(''),5000)},[])
 const fail=useCallback((e:any)=>{setError(e.message||String(e));if(e.status===401){setUser(null);setBatchId(null)}},[])
 async function load(){const epoch=++loadEpoch.current;setRefresh(true);try{const [b,w,n]=await Promise.all([api('/batches'),api('/warehouses'),api('/notifications?all=true')]);if(epoch!==loadEpoch.current)return;setBatches(b);setWarehouses(w);setNotes(n)}catch(e){if(epoch===loadEpoch.current)fail(e)}finally{if(epoch===loadEpoch.current)setRefresh(false)}}
 useEffect(()=>{api('/session-state').then(r=>{setUser(r.user);setCsrf(r.csrf)}).catch(()=>{}).finally(()=>setChecking(false))},[])
 useEffect(()=>{if(user)load()},[user])
 useEffect(()=>{if(!unsaved)return;const block=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};window.addEventListener('beforeunload',block);return()=>window.removeEventListener('beforeunload',block)},[unsaved])
 const reviewer=user?.roles.includes('REVIEWER'),planner=user?.roles.includes('PLANNER'),manager=user?.roles.some((r:string)=>['ADMIN','DATA_STEWARD','RULE_EDITOR','RULE_PUBLISHER'].includes(r))
 function leave(){return !unsaved||window.confirm("有未保存的修改，放弃并离开？")}
 function nav(name:string,filter='all',keepScope=false,confirmed=false){
  if(name!==view&&!confirmed&&!leave())return
  setEaNavOpen(false)
  document.querySelectorAll('header details[open]').forEach(d=>d.removeAttribute('open'))
  if(name!==view)setUnsaved(false)
  if(!keepScope){setScopeWarehouse('');setFromDay('');setToDay('');setScopePeriod('')}
  setView(name);setBatchId(null);setError('');setSearch('');setState(filter);load()
 }
 function openBatch(id:string,confirmed=false){
  if(view==='plan'&&batchId===id)return true
  if(!confirmed&&!leave())return false
  if(view!=='plan'){
   setPlanOrigin(view)
   listPosition.current={scroll:window.scrollY,focusId:document.activeElement?.id||'',notifications:notesOpen}
  }
  setEaNavOpen(false);setUnsaved(false);setBatchId(id);setView('plan');setError('')
  window.scrollTo(0,0)
  return true
 }
 function backToList(){
  restorePosition.current=true
  setUnsaved(false);setBatchId(null);setError('');setView(planOrigin)
  if(listPosition.current.notifications)setNotesOpen(true)
  load()
 }
 async function openNote(note:any){if(!openBatch(note.batch_id))return;setNotesOpen(false);if(note.seen)return;try{await api('/notifications/'+note.id+'/seen',{});setNotes(n=>n.map(item=>item.id===note.id?{...item,seen:true}:item))}catch(e){fail(e)}}
 async function logout(){if(!leave())return;try{await api('/sessions/current',undefined,'DELETE');loadEpoch.current++;setUser(null);setUnsaved(false);setBatchId(null);setView('home')}catch(e){fail(e)}}
 if(checking)return <Busy text="正在打开计划审核…"/>
 if(!user)return <Login eaTheme={eaTheme} onThemeChange={()=>setEaTheme(eaTheme==='light'?'dark':'light')} onLogin={u=>{loadEpoch.current++;setBatches([]);setNotes([]);setWarehouses([]);setView('home');setBatchId(null);setScopeWarehouse('');setFromDay('');setToDay('');setUnsaved(false);setNewOpen(false);setPasswordOpen(false);setNotesOpen(false);setUnreadOnly(false);setScopePeriod('');setPlanOrigin('plans');setEaNavOpen(false);setSearch('');setState('all');setUser(u);setError('')}}/>
 const scopeRows=batches.filter(b=>(!scopeWarehouse||b.warehouse===scopeWarehouse)&&(!fromDay||localDay(b.updated_at)>=fromDay)&&(!toDay||localDay(b.updated_at)<=toDay))
 const scoped=scopePeriod?scopeRows.filter(b=>b.period===scopePeriod):scopeRows
 const archive=(b:any)=>['APPROVED','VOID'].includes(b.state)
 const periodOptions=new Map<string,{label:string;start:string}>()
 for(const batch of batches){
  if((scopeWarehouse&&batch.warehouse!==scopeWarehouse)||(view==='history'&&!archive(batch)))continue
  periodOptions.set(batch.period,{label:batch.period_info?.label||batch.period,start:batch.period_info?.start||batch.period})
 }
 const periods=[...periodOptions.entries()].sort(([a,x],[b,y])=>y.start.localeCompare(x.start)||b.localeCompare(a))
 const current=scoped.filter(b=>!['APPROVED','VOID'].includes(b.state))
 const canReview=(b:any)=>reviewer&&b.owner!==user.id&&['SUBMITTED','IN_REVIEW'].includes(b.state)
 const canEdit=(b:any)=>planner&&b.owner===user.id&&['DRAFT','RETURNED'].includes(b.state)
 const isPending=(b:any)=>canReview(b)||canEdit(b)
 const pending=scoped.filter(isPending)
 const closed=scoped.filter(b=>b.state==='APPROVED')
 const priority=(b:any)=>canReview(b)?0:canEdit(b)?(b.state==='RETURNED'?1:2):3
 const todoNotes=notes.filter(n=>!unreadOnly||!n.seen)
 const hasWorkQueue=planner||reviewer
 const baseList=view==='history'?scoped.filter(archive):view==='home'?(hasWorkQueue?pending:current):scoped
 const homeStates=hasWorkQueue?[...(planner?['DRAFT','RETURNED']:[]),...(reviewer?['SUBMITTED','IN_REVIEW']:[])]:['DRAFT','SUBMITTED','IN_REVIEW','RETURNED']
 const listFilterActive=!!(search.trim()||state!=='all'||scopeWarehouse||scopePeriod||fromDay||toDay)
 function clearFilters(){setSearch('');setState('all');setScopeWarehouse('');setScopePeriod('');setFromDay('');setToDay('')}
 const matchesState=(b:any)=>state==='all'||(state==='pending'?isPending(b):state==='active'?!['APPROVED','VOID'].includes(b.state):b.state===state)
 const visible=baseList.filter(b=>matchesState(b)&&[b.title,b.number,b.warehouse_name].join(' ').toLowerCase().includes(search.trim().toLowerCase())).sort((a,b)=>{
  if(view==='history')return b.updated_at.localeCompare(a.updated_at)
  return priority(a)-priority(b)||(canReview(a)?a.updated_at.localeCompare(b.updated_at):b.updated_at.localeCompare(a.updated_at))
 })
 const plansLabel=reviewer?'计划复审':'计划列表'
 const section=view==='plan'?planOrigin:view
 const sectionName=section==='history'?'历史记录':section==='plans'?plansLabel:section==='data'?'数据中心':section==='rules'?'审核标准':section==='accounts'?'人员与权限':'工作台'
 const displayName=String(String(user.name||'').split(' · ')[0]||user.username||'').trim()
 const roleLabel=reviewer?'复审人员':planner?'计划员':user.roles.includes('DATA_STEWARD')?'数据维护':manager?'管理人员':'只读查看'
 return <div className={'app-shell'+(eaNavOpen?' ea-sidebar-open':'')}>
  <div className={'top-progress '+(refresh?'moving':'')}/>
  <button className="ea-nav-backdrop" hidden={!eaNavOpen} type="button" aria-label="关闭导航" onClick={()=>{setEaNavOpen(false);document.getElementById('ea-nav-toggle')?.focus()}}/><header className="main-nav" id="ea-app-navigation"><a className="brand" href="#" onClick={e=>{e.preventDefault();nav('home')}}><span className="ea-platform-logo" role="img" aria-label="EASPhub"/></a><div className="ea-app-identity"><ClipboardCheck size={18}/><div><strong>计划审核</strong></div></div>
   <nav aria-label="主导航"><button className={section==='home'?'active':''} onClick={()=>nav('home')}><LayoutDashboard size={17}/>工作台</button><button className={section==='plans'?'active':''} onClick={()=>nav('plans')}><ClipboardCheck size={17}/>{plansLabel}</button><button className={section==='history'?'active':''} onClick={()=>nav('history')}><History size={17}/>历史记录</button>{manager&&<details className="management"><summary><SlidersHorizontal size={17}/>管理<ChevronDown size={12}/></summary><div className="dropdown">{user.roles.some((r:string)=>['DATA_STEWARD','ADMIN'].includes(r))&&<button onClick={()=>nav('data')}><Database size={15}/>数据中心</button>}{user.roles.some((r:string)=>['RULE_EDITOR','RULE_PUBLISHER'].includes(r))&&<button onClick={()=>nav('rules','all',true)}><SlidersHorizontal size={15}/>审核标准</button>}{user.roles.includes('ADMIN')&&<button onClick={()=>nav('accounts')}><Users size={15}/>人员与权限</button>}</div></details>}</nav>
   <div className="nav-right">{platformUrl && <a className="platform-back" href={platformUrl}>← EASPhub 工作台</a>}<details className="account"><summary><span className="avatar" aria-hidden="true">{Array.from(displayName)[0]?.toLocaleUpperCase()||'?'}</span><span>{displayName}<small>{roleLabel}</small></span><ChevronDown size={13}/></summary><div className="dropdown"><button onClick={()=>setPasswordOpen(true)}><KeyRound size={14}/>修改密码</button><button onClick={logout}><LogOut size={14}/>退出登录</button></div></details></div>
  </header>
  <div className="ea-topbar"><button type="button" id="ea-nav-toggle" className="ea-nav-toggle" aria-label="打开应用导航" aria-controls="ea-app-navigation" aria-expanded={eaNavOpen} onClick={()=>setEaNavOpen(!eaNavOpen)}><Menu size={20}/></button><div className="ea-topbar__crumb"><span>工作空间</span><span aria-hidden="true">/</span><span>计划审核</span><span aria-hidden="true">/</span><strong>{sectionName}</strong></div><div className="ea-topbar__actions"><button className="ea-theme-toggle" type="button" role="switch" aria-checked={eaTheme==='dark'} onClick={()=>setEaTheme(eaTheme==='light'?'dark':'light')} aria-label="深色外观"><span className="ea-theme-track" aria-hidden="true"><span className="ea-theme-thumb"/><span className="ea-theme-day"><Sun size={15}/></span><span className="ea-theme-night"><Moon size={15}/></span></span></button></div></div>
  <main className="main-content">
   {error&&<div className="dismiss-notice"><Notice message={error} tone="error"/><button onClick={()=>setError('')} aria-label="关闭提示">×</button></div>}
   {view==='plan'&&batchId?<PlanView key={batchId} batchId={batchId} user={user} backLabel={'返回'+sectionName} onBack={backToList} onUpdate={load} notify={notify} onDirty={setUnsaved} onOpenBatch={id=>openBatch(id,true)}/>:
    view==='data'?<DataCenter warehouses={warehouses} notify={notify} user={user}/>:
    view==='rules'?<RuleCenter warehouses={warehouses} warehouse={scopeWarehouse} notify={notify} user={user} onDirty={setUnsaved}/>:
    view==='accounts'?<Accounts warehouses={warehouses} notify={notify} user={user}/>:
    <>
     <div className="page-heading"><div><h1>{view==='history'?'历史记录':view==='plans'?plansLabel:'计划工作台'}</h1></div><div className="actions"><button className="secondary compact" aria-label="刷新计划" onClick={load}><RefreshCw size={16} className={refresh?'spin':''}/></button>{planner&&<button className="primary" disabled={!warehouses.length} onClick={()=>setNewOpen(true)}><Plus size={17}/>新建计划</button>}</div></div>
     <div className="scope-controls">
      <span>{view==='home'?'统计范围':'仓库'}</span><select aria-label="统计仓库" value={scopeWarehouse} onChange={e=>{setScopeWarehouse(e.target.value);setScopePeriod('')}}><option value="">全部授权仓库</option>{warehouses.map(w=><option key={w.code} value={w.code}>{w.name}</option>)}</select>
      {view!=='home'&&<label>计划周期<select aria-label="筛选计划周期" value={scopePeriod} onChange={e=>setScopePeriod(e.target.value)}><option value="">全部周期</option>{periods.map(([value,period])=><option key={value} value={value}>{period.label}</option>)}</select></label>}
      <label>更新日期<input aria-label="开始日期" type="date" value={fromDay} max={toDay||undefined} onChange={e=>setFromDay(e.target.value)}/></label><span>至</span><input aria-label="结束日期" type="date" min={fromDay} value={toDay} onChange={e=>setToDay(e.target.value)}/>
      {(scopeWarehouse||fromDay||toDay||scopePeriod)&&<button className="text-button" onClick={()=>{setScopeWarehouse('');setFromDay('');setToDay('');setScopePeriod('')}}>重置范围</button>}
     </div>{view==='home'&&<div className="stats-strip"><button onClick={()=>nav('plans',reviewer||planner?'pending':'active',true)}><span className="stat-icon rose"><ClipboardCheck size={21}/></span><div><small>{reviewer&&!planner?'等待复审':reviewer||planner?'待我处理':'进行中'}</small><strong>{reviewer||planner?pending.length:current.length}<em>份计划</em></strong></div><ArrowUpRight size={16}/></button><button onClick={()=>nav('plans','RETURNED',true)}><span className="stat-icon coral"><History size={21}/></span><div><small>退回修改</small><strong>{scoped.filter(b=>b.state==='RETURNED').length}<em>份计划</em></strong></div><ArrowUpRight size={16}/></button><button onClick={()=>nav('history','APPROVED',true)}><span className="stat-icon teal"><CheckCircle2 size={21}/></span><div><small>已完成审核</small><strong>{closed.length}<em>份计划</em></strong></div><ArrowUpRight size={16}/></button><div><span className="stat-icon blue"><Layers3 size={21}/></span><div><small>授权仓库</small><strong>{warehouses.length}<em>个仓库</em></strong></div></div></div>}
     <div className={view==='home'?'workspace-grid':''}><section className="panel"><div className="panel-heading"><div><h2>{view==='home'?(hasWorkQueue?'我的待处理':'当前计划'):view==='history'?'审核档案':'计划列表'}</h2><span>{visible.length} 份计划</span></div>{view==='home'&&<button className="text-button" onClick={()=>nav('plans','all',true)}>全部计划<ArrowRight size={14}/></button>}</div>
      <div className="list-toolbar"><label className="search"><Search size={16}/><input aria-label="搜索计划名称、编号或仓库" placeholder="搜索计划名称、编号或仓库" value={search} onChange={e=>setSearch(e.target.value)}/></label><select aria-label="筛选计划状态" value={state} onChange={e=>setState(e.target.value)}><option value="all">全部状态</option>{view==='plans'&&hasWorkQueue&&<option value="pending">待我处理</option>}{view==='plans'&&<option value="active">进行中</option>}{(view==='history'?['APPROVED','VOID']:view==='home'?homeStates:['DRAFT','SUBMITTED','IN_REVIEW','RETURNED','APPROVED','VOID']).map(s=><option key={s} value={s}>{labels[s]}</option>)}</select></div>
      {visible.length?<div className="table-scroll"><table className="batch-table"><thead><tr><th>计划 / 仓库</th><th>状态</th><th>{reviewer&&view!=='history'?'未复审':'计划行'}</th><th>需关注</th><th>更新时间</th><th/></tr></thead><tbody>{visible.map(b=><tr key={b.id}><td><button id={'plan-title-'+b.id} className="row-link" onClick={()=>openBatch(b.id)}>{b.title}</button><small>{b.warehouse_name} <span>·</span> {b.number} <span>·</span> {b.period_info?.label||b.period}</small></td><td><Badge value={b.state}/></td><td className="mono">{reviewer&&view!=='history'?(['SUBMITTED','IN_REVIEW'].includes(b.state)?Math.max(0,b.summary.total-b.summary.reviewed):'—'):b.summary.total}</td><td><span className={b.summary.attention?'attention-count mono':'mono'}>{b.summary.attention}</span></td><td className="muted">{date(b.updated_at)}</td><td><button id={'plan-action-'+b.id} className="text-button" onClick={()=>openBatch(b.id)}>{canReview(b)?(b.state==='IN_REVIEW'?'继续复审':'开始复审'):canEdit(b)?'继续编辑':'查看'}<ArrowRight size={14}/></button></td></tr>)}</tbody></table></div>:<Empty title={listFilterActive?'没有符合条件的计划':view==='history'?'暂无审核档案':view==='home'&&hasWorkQueue?'暂无待处理计划':'暂无计划'}>{listFilterActive?<button className="text-button" onClick={clearFilters}>清除筛选</button>:planner&&view!=='history'&&<button className="secondary" disabled={!warehouses.length} onClick={()=>setNewOpen(true)}><Plus size={16}/>新建计划</button>}</Empty>}
     </section>{view==='home'&&<aside><section className="panel"><div className="panel-heading"><div><Bell size={17}/><h2>通知</h2><span className="count-dot">{notes.filter(n=>!n.seen).length}</span></div><button className="text-button" onClick={()=>setNotesOpen(true)}>查看全部<ArrowRight size={14}/></button></div><div className="todo-filter"><label className="check-row"><input type="checkbox" checked={unreadOnly} onChange={e=>setUnreadOnly(e.target.checked)}/>只看未读</label></div>{todoNotes.length?<div className="todo-list">{todoNotes.slice(0,5).map(n=><button key={n.id} onClick={()=>openNote(n)}><span className={'todo-dot '+(n.seen?'seen':'')}/><span>{n.text}<small>{n.seen?'已读':'未读'} · {date(n.at)}</small></span><ArrowUpRight size={15}/></button>)}</div>:<div className="quiet-state"><CheckCircle2 size={25}/><strong>{unreadOnly?'暂无未读通知':'暂无通知'}</strong></div>}</section></aside>}</div>
    </>}
  </main><footer><span><i className="live-dot"/>EASP Hub · 计划业务提效</span><span>v2.0.0</span></footer>
  {toast&&<div className="toast" role="status"><CheckCircle2 size={18}/>{toast}</div>}
  {newOpen&&<NewPlan warehouses={warehouses} initialWarehouse={scopeWarehouse} onClose={()=>setNewOpen(false)} onCreated={b=>{setNewOpen(false);load();openBatch(b.id)}}/>}
  {notesOpen&&<Modal title="通知" onClose={()=>setNotesOpen(false)}><div className="modal-body"><label className="check-row"><input type="checkbox" checked={unreadOnly} onChange={e=>setUnreadOnly(e.target.checked)}/>只看未读</label>{todoNotes.length?<div className="todo-list">{todoNotes.map(n=><button key={n.id} onClick={()=>openNote(n)}><span className={'todo-dot '+(n.seen?'seen':'')}/><span>{n.text}<small>{n.seen?'已读':'未读'} · {date(n.at)}</small></span><ArrowUpRight size={15}/></button>)}</div>:<Empty title={unreadOnly?'暂无未读通知':'暂无通知'}/>}</div></Modal>}
  {passwordOpen&&<Password beforeSubmit={leave} onClose={()=>setPasswordOpen(false)} onDone={()=>{setPasswordOpen(false);loadEpoch.current++;setUnsaved(false);setUser(null);notify('密码已更新，请重新登录')}}/>}
 </div>
}

function Login({onLogin,eaTheme,onThemeChange}:{onLogin:(u:any)=>void;eaTheme:'light'|'dark';onThemeChange:()=>void}) {
 const [username,setUsername]=useState(''),[password,setPassword]=useState('')
 const [showPassword,setShowPassword]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 async function enter(event:FormEvent) {
  event.preventDefault()
  if(busy||!username.trim()||!password)return
  setBusy(true);setError('')
  try {
   const result=await api('/sessions',{username:username.trim(),password})
   setCsrf(result.csrf);onLogin(result.user)
  } catch(e:any) { setError(e.message) }
  finally {setBusy(false)}
 }
 return <main className="sign-in">
  <header className="sign-in__cover">
   <img className="sign-in__photo" src={signInCover} alt="" width="1122" height="1402" fetchPriority="high"/>
   <span className="ea-platform-logo" role="img" aria-label="EASPhub"/>
   <div className="sign-in__identity"><p>欧洲备件业务</p><h1>计划审核</h1></div>
  </header>
  <section className="sign-in__workspace" aria-labelledby="sign-in-heading">
   <button className="ea-theme-toggle sign-in__theme" type="button" role="switch" aria-checked={eaTheme==='dark'} onClick={onThemeChange} aria-label="深色外观">
    <span className="ea-theme-track" aria-hidden="true"><span className="ea-theme-thumb"/><span className="ea-theme-day"><Sun size={15}/></span><span className="ea-theme-night"><Moon size={15}/></span></span>
   </button>
   <form className="sign-in__form" onSubmit={enter}>
    <h2 id="sign-in-heading">账号登录</h2>
    <div className="sign-in__field">
     <label htmlFor="sign-in-account">账号</label>
     <div className="sign-in__input"><UserRound aria-hidden="true" size={18}/>
      <input id="sign-in-account" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required value={username} onChange={e=>setUsername(e.target.value)} />
     </div>
    </div>
    <div className="sign-in__field">
     <label htmlFor="sign-in-password">密码</label>
     <div className="sign-in__input"><LockKeyhole aria-hidden="true" size={18}/>
      <input id="sign-in-password" name="password" type={showPassword?'text':'password'} autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/>
      <button type="button" className="sign-in__reveal" aria-label={showPassword?'隐藏密码':'显示密码'} aria-pressed={showPassword} onClick={()=>setShowPassword(!showPassword)}>{showPassword?<EyeOff size={18}/>:<Eye size={18}/>}</button>
     </div>
    </div>
    {error&&<Notice message={error} tone="error"/>}
    <button type="submit" className="primary sign-in__submit" disabled={busy}>{busy?'正在登录…':'登录'}<ArrowRight size={17} aria-hidden="true"/></button>
   </form>
  </section>
 </main>
}
function NewPlan({warehouses,initialWarehouse,onClose,onCreated}:{warehouses:any[];initialWarehouse:string;onClose:()=>void;onCreated:(b:any)=>void}){
 const [initial]=useState(()=>({
  warehouse:warehouses.some(w=>w.code===initialWarehouse)?initialWarehouse:warehouses.length===1?warehouses[0].code:'',
  title:(new Date().getMonth()+1)+'月补货计划',period:localDay(new Date().toISOString()).slice(0,7),
 }))
 const [warehouse,setWarehouse]=useState(initial.warehouse),[snaps,setSnaps]=useState<any[]>([]),[snapshot,setSnapshot]=useState(''),[loadingSnaps,setLoadingSnaps]=useState(false),[title,setTitle]=useState(initial.title),[period,setPeriod]=useState(initial.period),[periodKind,setPeriodKind]=useState('month'),[titleEdited,setTitleEdited]=useState(false),[usePlan,setUsePlan]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('')
 const dirty=warehouse!==initial.warehouse||title!==initial.title||period!==initial.period||periodKind!=='month'||!usePlan||(!loadingSnaps&&snapshot!==(snaps.length===1?snaps[0].id:''))
 const close=useFormExit(dirty,busy,onClose)
 useEffect(()=>{let active=true;setSnaps([]);setSnapshot('');setError('');if(!warehouse){setLoadingSnaps(false);return}setLoadingSnaps(true);api('/snapshots?warehouse='+encodeURIComponent(warehouse)).then(r=>{if(active){setSnaps(r);if(r.length===1)setSnapshot(r[0].id)}}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoadingSnaps(false)});return()=>{active=false}},[warehouse])
 async function create(e:FormEvent){e.preventDefault();if(busy||loadingSnaps||!warehouse||(snapshot&&!snaps.some(s=>s.id===snapshot&&s.warehouse===warehouse)))return;setBusy(true);setError('');try{const b=await api('/batches',{warehouse,snapshot_id:snapshot||null,title:title.trim(),period,use_snapshot_plan:!!snapshot&&usePlan});onCreated(b)}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <Modal title="新建计划" onClose={close}><form onSubmit={create} className="modal-body">{error&&<Notice message={error} tone="error"/>}<div className="form-grid"><label>仓库<select value={warehouse} required disabled={busy} onChange={e=>{if(e.target.value!==warehouse){setWarehouse(e.target.value);setSnapshot('');setSnaps([])}}}><option value="">请选择仓库</option>{warehouses.map(w=><option key={w.code} value={w.code}>{w.name}</option>)}</select></label><label>周期<select value={periodKind} disabled={busy} onChange={e=>{const kind=e.target.value;const next=kind==='week'?currentWeek():localDay(new Date().toISOString()).slice(0,7);setPeriodKind(kind);setPeriod(next);if(!titleEdited)setTitle(kind==='week'?next.slice(0,4)+'年第'+next.slice(-2)+'周补货计划':Number(next.slice(-2))+'月补货计划')}}><option value="month">按月</option><option value="week">按周</option></select></label><label>计划周期<input type={periodKind} value={period} disabled={busy} onChange={e=>{const next=e.target.value;setPeriod(next);if(!titleEdited&&next)setTitle(periodKind==='week'?next.slice(0,4)+'年第'+next.slice(-2)+'周补货计划':Number(next.slice(-2))+'月补货计划')}} required/>{periodKind==='week'&&<small>{weekLabel(period)}</small>}</label></div><label>计划名称<input value={title} disabled={busy} onChange={e=>{setTitle(e.target.value);setTitleEdited(true)}} maxLength={120} required/></label><SnapshotPicker label="数据快照（选填）" required={false} snapshots={snaps} value={snapshot} onChange={setSnapshot} disabled={busy||!warehouse} loading={loadingSnaps} emptyText="暂不关联" noDataText={warehouse?'本仓暂无快照，可直接创建':'请先选择仓库'}/>
 {snapshot&&<label className="check-row"><input type="checkbox" disabled={busy} checked={usePlan} onChange={e=>setUsePlan(e.target.checked)}/><span>带入快照计划</span></label>}
 <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>取消</button><button className="primary" disabled={busy||loadingSnaps||!warehouse||!title.trim()||!period}>{busy?'正在创建…':'创建计划'}<ArrowRight size={16}/></button></div></form></Modal>
}
function Password({beforeSubmit,onClose,onDone}:{beforeSubmit:()=>boolean;onClose:()=>void;onDone:()=>void}){const [old,setOld]=useState(''),[next,setNext]=useState(''),[error,setError]=useState('');return <Modal title="修改密码" onClose={onClose}><form className="modal-body" onSubmit={async e=>{e.preventDefault();if(!beforeSubmit())return;try{await api('/password',{current_password:old,password:next});onDone()}catch(e:any){setError(e.message)}}}>{error&&<Notice message={error} tone="error"/>}<label>当前密码<input type="password" value={old} onChange={e=>setOld(e.target.value)} required/></label><label>新密码<input type="password" value={next} onChange={e=>setNext(e.target.value)} minLength={12} required/><small>至少12位，保存后重新登录。</small></label><div className="modal-actions"><button className="primary">保存新密码</button></div></form></Modal>}
