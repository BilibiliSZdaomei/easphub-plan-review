import {useEffect,useRef} from 'react'
import {BASE,sessionCsrf} from './api'
import {usageTargets,type UsagePage,type UsageTarget} from './usage-labels'
import {listenForFailures} from './usageSignals'

type Device='mobile'|'desktop'
type UsageEvent={kind:'view'|'pulse'|'click'|'repeat'|'error'|'validation';page:UsagePage;device:Device;target?:UsageTarget;x?:number;y?:number}
type Batch={batch_id:string;sent_at:number;events:UsageEvent[]}
const device=():Device=>window.matchMedia('(max-width: 760px)').matches?'mobile':'desktop'
const visible=()=>document.visibilityState==='visible'
const interaction='button,a,summary,input,textarea,select,[role="button"],[role="tab"],[role="switch"],[role="option"]'

function privateControl(el:Element){
  return !!(el.closest('[data-usage-private]')||el.closest('[role="dialog"]')?.querySelector('[data-usage-private]'))
}

function targetFor(el:Element):UsageTarget {
  const tag=el.closest<HTMLElement>('[data-usage-target]')?.dataset.usageTarget
  if(tag&&Object.hasOwn(usageTargets,tag))return tag as UsageTarget
  if(el.closest('#ea-account-menu,.profile-card,.avatar-editor'))return 'account'
  if(el.closest('nav,.topbar,.ea-topbar,.stats-strip'))return 'navigation'
  if(el.closest('.filter-tabs,.column-filter-menu,.list-toolbar,.scope-controls,.filter-active'))return 'filter'
  if(el.closest('input,textarea'))return 'input'
  if(el.closest('select'))return 'select'
  if(el.closest('table'))return 'table'
  if(el.closest(interaction))return 'button'
  if(el.closest('[role="dialog"]'))return 'dialog'
  return 'other'
}

function batchId(){
  const bytes=crypto.getRandomValues(new Uint8Array(16))
  bytes[6]=(bytes[6]&15)|64
  bytes[8]=(bytes[8]&63)|128
  const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('')
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-')
}

function startUsage(initialPage:UsagePage,csrf:string){
  let page=initialPage, opened=false, closed=false, sending=false
  let activeAt=0, lastPulse=-1, retryAt=0, delay=1500
  let current:Batch|null=null, timer:number|undefined
  const pending:UsageEvent[]=[]
  let repeated:{control:Element;time:number;x:number;y:number;count:number}|null=null
  let invalidForm:Element|null=null, invalidAt=0

  function schedule(ms:number){
    if(timer!==undefined||closed)return
    timer=window.setTimeout(()=>{timer=undefined;void flush()},ms)
  }
  async function flush(){
    if(closed||sending||(!current&&!pending.length))return
    if(Date.now()<retryAt){schedule(retryAt-Date.now());return}
    if(!current)current={batch_id:batchId(),sent_at:Math.floor(Date.now()/1000),events:pending.splice(0,60)}
    sending=true
    try{
      const r=await fetch(BASE+'/usage/events',{method:'POST',credentials:'same-origin',keepalive:true,
        headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(current)})
      if(r.status===401||r.status===403){closed=true;pending.length=0;current=null;return}
      if(!r.ok&&(r.status>=500||r.status===429))throw new Error('retry')
      current=null;delay=1500;retryAt=0
    }catch{
      if(current&&Date.now()/1000-current.sent_at>86400)current=null
      retryAt=Date.now()+delay;delay=Math.min(delay*2,60000)
    }finally{
      sending=false
      if(current||pending.length)schedule(Math.max(100,retryAt-Date.now()))
    }
  }
  function add(kind:UsageEvent['kind'],extra:Partial<UsageEvent>={}){
    if(closed||pending.length>=240)return
    pending.push({kind,page,device:device(),...extra})
    schedule(kind==='view'||pending.length>=40?120:900)
  }
  function show(){
    if(!opened&&visible()){opened=true;add('view')}
  }
  function wake(){
    if(!visible())return
    activeAt=Date.now();show()
    if(activeAt-lastPulse>=30000)pulse()
  }
  function pulse(){
    if(visible()&&activeAt>lastPulse&&Date.now()-activeAt<30000){lastPulse=Date.now();add('pulse')}
  }
  function click(e:MouseEvent){
    if(!visible()||!e.isTrusted||e.detail===0||!(e.target instanceof Element)||privateControl(e.target))return
    const el=e.target,target=targetFor(el)
    const x=Math.min(7,Math.max(0,Math.floor(e.clientX*8/Math.max(1,window.innerWidth))))
    const y=Math.min(5,Math.max(0,Math.floor(e.clientY*6/Math.max(1,window.innerHeight))))
    add('click',{target,x,y})
    const control=el.closest(interaction)??el
    // Repeated presses on steppers or row selections are normal plan editing.
    if(control.closest('input,select,textarea,.plan-quantity,[role="spinbutton"]')){repeated=null;return}
    const now=performance.now()
    if(!repeated||control!==repeated.control||now-repeated.time>1000||Math.hypot(e.clientX-repeated.x,e.clientY-repeated.y)>24){
      repeated={control,time:now,x:e.clientX,y:e.clientY,count:1}
    }else if(++repeated.count===3){add('repeat',{target})}
  }
  function invalid(e:Event){
    if(!visible()||!(e.target instanceof HTMLElement)||privateControl(e.target))return
    const form=e.target.closest('form')??e.target
    if(form===invalidForm&&performance.now()-invalidAt<600)return
    invalidForm=form;invalidAt=performance.now()
    add('validation',{target:targetFor(e.target)})
  }
  function visibility(){if(visible())wake();else void flush()}
  const unlisten=listenForFailures(target=>{
    const origin=page,originalDevice=device()
    return kind=>add(kind,{page:origin,device:originalDevice,target})
  })
  document.addEventListener('visibilitychange',visibility)
  document.addEventListener('click',click,true)
  document.addEventListener('invalid',invalid,true)
  for(const name of ['pointerdown','keydown','scroll','wheel','touchstart'])document.addEventListener(name,wake,{capture:true,passive:true})
  window.addEventListener('pagehide',flush)
  const interval=window.setInterval(pulse,30000)
  wake()
  return {
    visit(next:UsagePage){page=next;opened=false;repeated=null;show()},
    close(){
      // The old CSRF token binds the final batch to the session that produced it.
      void flush()
      closed=true;window.clearInterval(interval);window.clearTimeout(timer);unlisten()
      document.removeEventListener('visibilitychange',visibility)
      document.removeEventListener('click',click,true);document.removeEventListener('invalid',invalid,true)
      for(const name of ['pointerdown','keydown','scroll','wheel','touchstart'])document.removeEventListener(name,wake,true)
      window.removeEventListener('pagehide',flush)
    },
    flush,
  }
}

const views:Record<string,UsagePage>={home:'home',plans:'plans',plan:'detail',history:'history',data:'data',rules:'rules',accounts:'accounts',inbox:'inbox',profile:'profile',myUsage:'usage',teamUsage:'usage'}
export function useUsageTracking(userId:string|undefined,view:string,detailKey:string|null){
  const page=views[view]??'home'
  const visitKey=page==='detail'?page+'-'+detailKey:view
  const latest=useRef({page,visitKey})
  latest.current={page,visitKey}
  const tracker=useRef<ReturnType<typeof startUsage>|null>(null),previous=useRef('')
  useEffect(()=>{
    if(!userId)return
    previous.current=latest.current.visitKey
    const instance=startUsage(latest.current.page,sessionCsrf())
    tracker.current=instance
    return ()=>{instance.close();tracker.current=null}
  },[userId])
  useEffect(()=>{
    if(!tracker.current||previous.current===visitKey)return
    previous.current=visitKey;tracker.current.visit(page)
  },[page,visitKey])
  return ()=>tracker.current?.flush()
}
