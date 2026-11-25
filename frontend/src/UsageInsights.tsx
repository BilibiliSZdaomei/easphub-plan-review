import {useEffect,useId,useState,type CSSProperties,type ReactNode} from 'react'
import {Activity,CalendarDays,ChartNoAxesColumn,Eye,MousePointer2,RefreshCw,Search,Users} from 'lucide-react'
import {api} from './api'
import {getLanguage,tr,useLanguage} from './i18n'
import {roleNames} from './roles'
import {Busy,Notice} from './ui'
import {usagePageLabel,usagePages,usageTargetLabel,type UsagePage,type UsageTarget} from './usage-labels'
import './usage-insights.css'

type Scope='personal'|'admin'
type Period=1|7|30
type Trend={date:string;page_views:number;active_users:number;friction_events:number}
type Metric=keyof Omit<Trend,'date'>
type Person={id:string;name:string;role:string;active_days:number;page_views:number;click_count:number;online:boolean;friction_events:number}
type Friction={kind:'repeat'|'error'|'validation';page:UsagePage;target:UsageTarget;count:number}
type Heatmap={columns:number;rows:number;cells:{x:number;y:number;count:number;actions:{target:UsageTarget;count:number}[]}[];total:number}
type Report={
  days:number;generated_at:string;summary:{page_views:number;active_days:number;active_users:number;online_users:number;friction_events:number;click_count:number}
  trend:Trend[];pages:{page:UsagePage;page_views:number}[];actions:{target:UsageTarget;count:number}[]
  people:Person[];friction:Friction[];heatmap:Heatmap
}

const number=(value:number)=>value.toLocaleString(getLanguage())
const shortDate=(date:string)=>new Intl.DateTimeFormat(getLanguage(),{month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(date+'T00:00:00Z'))
const metricNames:Record<Metric,()=>string>={
  page_views:()=>tr('页面访问','Page views'),
  active_users:()=>tr('活跃人数','Active users'),
  friction_events:()=>tr('疑似卡点','Friction signals'),
}
const signals={
  repeat:()=>tr('快速重复点击','Rapid repeat clicks'),
  error:()=>tr('请求失败','Failed request'),
  validation:()=>tr('校验未通过','Validation failed'),
}

function Panel({title,controls,children,className=''}:{title:string;controls?:ReactNode;children:ReactNode;className?:string}){
  const id=useId()
  return <section aria-labelledby={id} className={'panel usage-panel '+className}>
    <header className="usage-panel-head"><h2 id={id}>{title}</h2>{controls}</header>{children}
  </section>
}

function EmptyLine({children}:{children:ReactNode}){
  return <p className="usage-empty">{children}</p>
}

function Stat({label,value,icon,hint}:{label:string;value:number;icon:ReactNode;hint?:string}){
  return <div className="usage-stat" title={hint}>
    <div>{icon}<span>{label}</span></div><strong>{number(value)}</strong>
    {hint&&<small>{hint}</small>}
  </div>
}

function TrendPanel({rows,admin}:{rows:Trend[];admin:boolean}){
  const [metric,setMetric]=useState<Metric>('page_views')
  const [activeDate,setActiveDate]=useState('')
  const field=admin?metric:'page_views'
  const label=metricNames[field]()
  const max=Math.max(1,...rows.map(row=>row[field]))
  const selected=rows.find(row=>row.date===activeDate)??rows.at(-1)
  const hasData=rows.some(row=>row[field]>0)
  const frequency=rows.length>9?Math.ceil((rows.length-1)/4):1
  const controls=admin?<select aria-label={tr('趋势指标','Trend metric')} value={field} onChange={e=>setMetric(e.target.value as Metric)}>
    {(Object.keys(metricNames) as Metric[]).map(key=><option key={key} value={key}>{metricNames[key]()}</option>)}
  </select>:<span className="usage-caption">{label}</span>
  return <Panel title={tr('使用趋势','Usage trend')} controls={controls} className="usage-trend-card">
    {hasData&&selected?<div className="usage-trend">
      <div className="usage-chart-note" aria-live="polite"><strong>{number(selected[field])}</strong> {label} <span>· {shortDate(selected.date)} UTC</span></div>
      <div className="usage-bars" role="group" aria-label={label}>
        {rows.map((row,i)=>{
          const display=shortDate(row.date)
          const selectedDay=row.date===selected.date
          return <div className="usage-bar-slot" key={row.date}>
            <button type="button" className={'usage-day'+(selectedDay?' is-active':'')} aria-pressed={selectedDay}
              aria-label={display+' · '+label+' '+number(row[field])} title={display+' · '+number(row[field])}
              onClick={()=>setActiveDate(row.date)} onFocus={()=>setActiveDate(row.date)} onMouseEnter={()=>setActiveDate(row.date)}>
              <i style={{'--usage-height':(100*row[field]/max)+'%'} as CSSProperties}/>
            </button>
            <span aria-hidden="true">{i%frequency===0||i===rows.length-1?new Date(row.date+'T00:00:00Z').getUTCDate():''}</span>
          </div>
        })}
      </div>
      <div className="usage-chart-ends"><span>{shortDate(rows[0].date)}</span>
        {rows.length>1&&<span>{shortDate(rows[rows.length-1].date)}</span>}</div>
    </div>:<EmptyLine>{tr('这段时间没有该指标的记录。','No activity for this metric in this period.')}</EmptyLine>}
  </Panel>
}

function Ranking({report}:{report:Report}){
  const [mode,setMode]=useState<'pages'|'actions'>('pages')
  const entries=mode==='pages'
    ?report.pages.map(row=>({key:row.page,label:usagePageLabel(row.page),count:row.page_views}))
    :report.actions.map(row=>({key:row.target,label:usageTargetLabel(row.target),count:row.count}))
  const ranked=entries.filter(row=>row.count>0).sort((a,b)=>b.count-a.count)
  const max=ranked[0]?.count||1
  return <Panel title={tr('常用功能','Most used')} controls={
    <div className="usage-switch" role="group" aria-label={tr('功能统计分类','Feature ranking category')}>
      <button type="button" aria-pressed={mode==='pages'} onClick={()=>setMode('pages')}>{tr('页面','Pages')}</button>
      <button type="button" aria-pressed={mode==='actions'} onClick={()=>setMode('actions')}>{tr('操作','Actions')}</button>
    </div>}>
    {ranked.length?<ol className="usage-ranking">{ranked.map((row,i)=><li key={row.key}>
      <span className="usage-place">{i+1}</span>
      <div><div><span>{row.label}</span><strong>{number(row.count)}</strong></div><i><b style={{width:(100*row.count/max)+'%'}}/></i></div>
    </li>)}</ol>:<EmptyLine>{mode==='pages'?tr('这段时间没有页面访问。','No page views in this period.'):tr('这段时间没有点击记录。','No clicks in this period.')}</EmptyLine>}
  </Panel>
}

function People({people}:{people:Person[]}){
  const [query,setQuery]=useState('')
  const matching=people.filter(person=>person.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  return <Panel title={tr('成员使用情况','Member activity')} controls={
    <label className="usage-search"><Search size={15} aria-hidden="true"/><input type="search" value={query}
      aria-label={tr('搜索成员','Search members')} placeholder={tr('搜索成员','Search members')} onChange={e=>setQuery(e.target.value)}/></label>}>
    {matching.length?<div className="usage-table-scroll"><table>
      <thead><tr>{[tr('成员','Member'),tr('状态','Status'),tr('活跃天数','Active days'),metricNames.page_views(),tr('点击次数','Clicks'),metricNames.friction_events()].map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead>
      <tbody>{matching.map(person=><tr key={person.id}>
        <td><strong>{person.name}</strong><small>{roleNames[person.role]||'—'}</small></td>
        <td><span className={'usage-presence'+(person.online?' online':'')}><i/>{person.online?tr('在线','Online'):tr('离线','Offline')}</span></td>
        <td>{number(person.active_days)}</td><td>{number(person.page_views)}</td><td>{person.click_count==null?'—':number(person.click_count)}</td><td>{number(person.friction_events)}</td>
      </tr>)}</tbody>
    </table></div>:<EmptyLine>{query?tr('没有匹配的成员。','No matching members.'):tr('暂无成员记录。','No member records yet.')}</EmptyLine>}
  </Panel>
}

function FrictionTable({rows}:{rows:Friction[]}){
  return <Panel title={tr('疑似卡点','Potential friction')} controls={<span className="usage-caption">{tr('按事件次数','Event counts')}</span>}>
    {rows.length?<div className="usage-table-scroll"><table>
      <thead><tr>{[tr('信号','Signal'),tr('所在页面','Page'),tr('操作位置','Control'),tr('次数','Events')].map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead>
      <tbody>{rows.map(row=><tr key={[row.kind,row.page,row.target].join('.')}><td><span className="usage-signal">{signals[row.kind]()}</span></td>
        <td>{usagePageLabel(row.page)}</td><td>{usageTargetLabel(row.target)}</td><td>{number(row.count)}</td></tr>)}</tbody>
    </table></div>:<EmptyLine>{tr('这段时间没有快速重复点击、请求失败或校验失败。','No rapid repeat clicks, request failures or validation failures in this period.')}</EmptyLine>}
  </Panel>
}

function HeatmapPanel({map,page,device,onPage,onDevice,failed}:{map:Heatmap|null;page:string;device:string;onPage:(value:string)=>void;onDevice:(value:string)=>void;failed:boolean}){
  const [cell,setCell]=useState<number|null>(null)
  const countByCell=new Map(map?.cells.map(point=>[point.y*8+point.x,point.count]))
  const max=Math.max(1,...countByCell.values())
  const points=[...countByCell.entries()].sort((a,b)=>b[1]-a[1])
  const index=cell??points[0]?.[0]??0
  const actions=map?.cells.find(point=>point.y*8+point.x===index)?.actions?.slice(0,3)??[]
  const position=(i:number)=>String.fromCharCode(65+i%8)+(Math.floor(i/8)+1)
  const total=map?.total??0
  const clickLabel=tr('次点击','clicks')
  const filters=<div className="usage-map-filters">
    <select aria-label={tr('热图页面','Heatmap page')} value={page} onChange={e=>{setCell(null);onPage(e.target.value)}}>
      <option value="all">{tr('全部页面','All pages')}</option>
      {(Object.keys(usagePages) as UsagePage[]).map(key=><option value={key} key={key}>{usagePageLabel(key)}</option>)}
    </select>
    <select aria-label={tr('热图终端','Heatmap device')} value={device} onChange={e=>{setCell(null);onDevice(e.target.value)}}>
      <option value="all">{tr('全部终端','All devices')}</option><option value="desktop">{tr('桌面端','Desktop')}</option><option value="mobile">{tr('移动端','Mobile')}</option>
    </select>
  </div>
  return <Panel title={tr('点击位置分布','Click heatmap')} controls={filters}>
    {!map?<p aria-live="polite" className="usage-empty">{failed?tr('点击分布暂时不可用。','Click heatmap is unavailable.'):tr('正在读取…','Loading…')}</p>:total>0?<div className="usage-map-body">
      <div className="usage-map-grid" role="group" aria-label={tr('屏幕位置，8 列 6 行','Screen position, 8 columns by 6 rows')}>
        <span aria-hidden="true"/>{'ABCDEFGH'.split('').map(c=><span key={c} aria-hidden="true">{c}</span>)}
        {Array.from({length:6},(_,y)=><div className="usage-map-row" key={y}>
          <span aria-hidden="true">{y+1}</span>
          {Array.from({length:8},(_,x)=>{
            const i=y*8+x,count=countByCell.get(i)||0
            const label=position(i)+' · '+number(count)+' '+clickLabel
            return <button key={x} type="button" aria-label={label} title={label} aria-pressed={index===i}
              className={'usage-tile tone-'+(count?Math.max(1,Math.ceil(5*Math.sqrt(count/max))):0)}
              onClick={()=>setCell(i)}>{count?number(count):''}</button>
          })}
        </div>)}
      </div>
      <div className="usage-map-footer"><span aria-live="polite"><strong>{position(index)}</strong> · {number(countByCell.get(index)||0)} / {number(total)} {clickLabel}</span>
        <span className="usage-map-legend">{tr('少','Low')}{[0,1,2,3,4,5].map(n=><i key={n} className={'tone-'+n}/>)}{tr('多','High')}</span></div>
      {actions.length>0&&<div className="usage-cell-actions" aria-live="polite"><strong>{tr('区内常用操作','Top actions here')}</strong>
        <ul>{actions.map(action=><li key={action.target}>{usageTargetLabel(action.target)} <b>{number(action.count)}</b></li>)}</ul>
      </div>}
    </div>:<EmptyLine>{tr('当前页面和终端还没有点击记录。','No clicks recorded for this page and device.')}</EmptyLine>}
  </Panel>
}

type Stored={report:Report;path:string;period:Period}
function ReportView({scope}:{scope:Scope}){
  useLanguage()
  const [period,setPeriod]=useState<Period>(7)
  const [page,setPage]=useState('all'),[device,setDevice]=useState('all')
  const [refresh,setRefresh]=useState(0),[pending,setPending]=useState(false)
  const [stored,setStored]=useState<Stored|null>(null),[error,setError]=useState('')
  const admin=scope==='admin'
  const path='/usage/insights?'+new URLSearchParams({scope:admin?'team':'me',days:String(period),page,device})
  useEffect(()=>{
    const refreshVisible=()=>{if(document.visibilityState==='visible')setRefresh(value=>value+1)}
    const interval=window.setInterval(refreshVisible,60000)
    document.addEventListener('visibilitychange',refreshVisible)
    return ()=>{window.clearInterval(interval);document.removeEventListener('visibilitychange',refreshVisible)}
  },[])
  useEffect(()=>{
    const controller=new AbortController()
    setPending(true);setError('')
    api<Report>(path,undefined,'GET',undefined,controller.signal).then(report=>{
      if(!controller.signal.aborted)setStored({report,path,period})
    }).catch((cause:unknown)=>{
      if(controller.signal.aborted)return
      if(cause instanceof Error&&'status' in cause&&(cause.status===401||cause.status===403))setStored(null)
      setError(cause instanceof Error?cause.message:tr('统计读取失败','Could not load usage'))
    }).finally(()=>{if(!controller.signal.aborted)setPending(false)})
    return ()=>controller.abort()
  },[path,period,refresh])
  const data=stored?.period===period?stored.report:null
  const showMap=stored?.path===path?stored.report.heatmap:null
  const range=period===1?tr('今天','Today'):tr('近 '+period+' 天','Last '+period+' days')
  return <div className="usage-insights" data-scope={scope}>
    <div className="page-heading usage-heading"><div><h1>{admin?tr('使用分析','Usage insights'):tr('我的使用情况','My usage')}</h1>
      <p>{admin?tr('授权范围内的成员','Members within your access'):tr('仅本人','Your activity only')} · {data?.trend.length?shortDate(data.trend[0].date)+(data.trend.length>1?' – '+shortDate(data.trend[data.trend.length-1].date):''):range} · UTC</p></div>
      <div className="usage-options"><div className="usage-switch" role="group" aria-label={tr('统计周期','Reporting period')}>
        {([1,7,30] as const).map(n=><button type="button" key={n} aria-pressed={n===period} onClick={()=>setPeriod(n)}>{n===1?tr('今天','Today'):tr('近 '+n+' 天',n+' days')}</button>)}
      </div><button type="button" className="secondary compact" aria-label={tr('刷新统计','Refresh insights')} title={tr('刷新统计','Refresh insights')} onClick={()=>setRefresh(n=>n+1)} disabled={pending}><RefreshCw size={15}/></button></div>
    </div>
    {error&&<div className="usage-error"><Notice message={error} tone="error"/><button type="button" className="text-button" onClick={()=>setRefresh(n=>n+1)}>{tr('重试','Retry')}</button></div>}
    {!data?(!error&&<Busy/>):<>
      <div className="usage-stats">
        {admin?<><Stat label={metricNames.active_users()} value={data.summary.active_users} icon={<Users size={17}/>}/>
          <Stat label={tr('当前在线','Online now')} value={data.summary.online_users} icon={<Activity size={17}/>} hint={tr('最近 2 分钟','Last 2 minutes')}/></>
          :<Stat label={tr('活跃天数','Active days')} value={data.summary.active_days} icon={<CalendarDays size={17}/>}/>}
        <Stat label={metricNames.page_views()} value={data.summary.page_views} icon={<Eye size={17}/>}/>
        {admin?<Stat label={metricNames.friction_events()} value={data.summary.friction_events} icon={<ChartNoAxesColumn size={17}/>}/>
          :<Stat label={tr('点击次数','Clicks')} value={data.summary.click_count} icon={<MousePointer2 size={17}/>}/>}
      </div>
      <div className="usage-pair"><TrendPanel rows={data.trend} admin={admin}/><Ranking report={data}/></div>
      {admin&&<><People people={data.people}/><HeatmapPanel map={showMap} page={page} device={device} onPage={setPage} onDevice={setDevice} failed={!!error}/><FrictionTable rows={data.friction}/></>}
      <details className="usage-definitions"><summary>{tr('统计口径','How usage is counted')}</summary>
        <p>{tr('按 UTC 自然日汇总。进入页面计一次访问，当天有使用记录计一个活跃日。','Days follow UTC. Opening a page counts as one view. A day with recorded activity counts as one active day.')}</p>
        {admin&&<p>{tr('活跃人数按账号去重。在线人数统计最近两分钟内发出活动信号且仍处于登录状态的账号。热图按浏览器可视区域划分。','Active users are counted once per account. Online users have a valid session with an activity signal in the last two minutes. Heatmap cells refer to positions within the browser viewport.')}</p>}
      </details>
    </>}
  </div>
}

export default function UsageInsights({scope}:{scope:Scope}){
  return <ReportView key={scope} scope={scope}/>
}
