import {systemText} from './i18n'
import {tr} from './i18n'
import {useEffect,useRef,useState,type KeyboardEvent,type PointerEvent,type RefObject} from 'react'

const minimum=180
const maximum=360
const widthKey='plan-review.sidebar.width'
const collapseKey='plan-review.sidebar.collapsed'
const clamp=(n:number)=>Math.min(maximum,Math.max(minimum,Math.round(n)))

function saved(key:string){
  try{return localStorage.getItem(key)}catch{return null}
}
function remember(key:string,value:string){
  try{localStorage.setItem(key,value)}catch{/* Browser storage is optional. */}
}

export function useSidebarSize(){
  const shellRef=useRef<HTMLDivElement>(null)
  const [width,setWidth]=useState<number|null>(()=>{
    const n=Number(saved(widthKey))
    return Number.isFinite(n)&&n>=minimum&&n<=maximum?n:null
  })
  const [collapsed,setCollapsed]=useState(()=>saved(collapseKey)==='true')
  function saveWidth(next:number){
    setWidth(next)
    remember(widthKey,String(next))
  }
  function toggle(){
    setCollapsed(!collapsed)
    remember(collapseKey,String(!collapsed))
  }
  return {shellRef,width,collapsed,saveWidth,toggle}
}

export function SidebarResize({shellRef,onCommit}:{
  shellRef:RefObject<HTMLDivElement|null>;onCommit:(size:number)=>void
}){
  const drag=useRef<{id:number;x:number;start:number;next:number;original:string}|null>(null)
  const [now,setNow]=useState(264)
  useEffect(()=>{
    const shell=shellRef.current
    const nav=shell?.querySelector<HTMLElement>('#ea-app-navigation')
    if(!shell||!nav)return
    const measure=()=>setNow(clamp(nav.offsetWidth))
    measure()
    const observer=new ResizeObserver(measure)
    observer.observe(nav)
    return ()=>{
      observer.disconnect()
      shell.classList.remove('sidebar-resizing')
    }
  },[shellRef])
  function start(e:PointerEvent<HTMLDivElement>){
    if(e.button!==0||!e.isPrimary)return
    const shell=shellRef.current
    const nav=shell?.querySelector<HTMLElement>('#ea-app-navigation')
    if(!shell||!nav)return
    e.preventDefault()
    e.currentTarget.focus({preventScroll:true})
    e.currentTarget.setPointerCapture(e.pointerId)
    const start=nav.offsetWidth
    drag.current={id:e.pointerId,x:e.clientX,start,next:start,original:shell.style.getPropertyValue('--plan-sidebar-user-width')}
    shell.classList.add('sidebar-resizing')
  }
  function move(e:PointerEvent<HTMLDivElement>){
    const current=drag.current
    if(!current||current.id!==e.pointerId)return
    current.next=clamp(current.start+e.clientX-current.x)
    shellRef.current?.style.setProperty('--plan-sidebar-user-width',current.next+'px')
  }
  function end(handle:HTMLDivElement,cancel:boolean){
    const current=drag.current, shell=shellRef.current
    if(!current||!shell)return
    drag.current=null
    shell.classList.remove('sidebar-resizing')
    if(handle.hasPointerCapture(current.id))handle.releasePointerCapture(current.id)
    if(cancel)shell.style.setProperty('--plan-sidebar-user-width',current.original)
    else onCommit(current.next)
  }
  function keyboard(e:KeyboardEvent<HTMLDivElement>){
    if(e.key==='Escape'&&drag.current){end(e.currentTarget,true);return}
    const step=e.shiftKey?32:8
    const current=shellRef.current?.querySelector<HTMLElement>('#ea-app-navigation')?.offsetWidth??now
    const size=({ArrowLeft:current-step,ArrowRight:current+step,Home:minimum,End:maximum} as Record<string,number>)[e.key]
    if(size===undefined)return
    e.preventDefault()
    onCommit(clamp(size))
  }
  return <div className="sidebar-resize" role="separator" aria-label={systemText("调整侧栏宽度")}
    aria-controls="ea-app-navigation" aria-orientation="vertical" aria-valuenow={now}
    aria-valuemin={minimum} aria-valuemax={maximum} aria-valuetext={tr(now+' 像素',now+' pixels')}
    tabIndex={0} title={systemText("拖动调整宽度，或使用左右方向键")}
    onPointerDown={start} onPointerMove={move} onPointerUp={e=>{
      if(drag.current?.id===e.pointerId){move(e);end(e.currentTarget,false)}
    }}
    onPointerCancel={e=>{if(drag.current?.id===e.pointerId)end(e.currentTarget,true)}}
    onLostPointerCapture={e=>{if(drag.current?.id===e.pointerId)end(e.currentTarget,true)}}
    onKeyDown={keyboard}/>
}
