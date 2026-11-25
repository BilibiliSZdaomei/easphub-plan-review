import {systemMessage,systemText} from './i18n'
import {createPortal} from 'react-dom'
import {useEffect,useRef,ReactNode} from 'react'
import {X,LoaderCircle,Inbox,CheckCircle2,AlertCircle} from 'lucide-react'
import {labels} from './api'
export function Badge({value,label}:{value:string;label?:string}){return <span className={'badge '+value.toLowerCase()}>{label||labels[value]||value}</span>}
export function Busy({text='正在读取…'}:{text?:string}){return <div className="busy"><LoaderCircle size={21}/><span>{systemText(text)}</span></div>}
export function Empty({title,children}:{title:string;children?:ReactNode}){return <div className="empty"><Inbox size={34} strokeWidth={1.3}/><h3>{title}</h3>{children}</div>}
export function useDialog<T extends HTMLElement=HTMLElement>(onClose:()=>void){
 const ref=useRef<T>(null)
 const close=useRef(onClose)
 close.current=onClose
 useEffect(()=>{
  const dialog=ref.current
  const previous=document.activeElement as HTMLElement|null
  const previousOverflow=document.body.style.overflow
  document.body.style.overflow='hidden'
  dialog?.focus()
  const key=(event:KeyboardEvent)=>{
   const dialogs=document.querySelectorAll('[role="dialog"][aria-modal="true"]')
   if(dialogs[dialogs.length-1]!==dialog)return
   if(event.key==='Escape'){event.preventDefault();close.current();return}
   if(event.key!=='Tab')return
   const nodes=Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,a[href]')||[]).filter(el=>el.getClientRects().length>0&&!el.closest('[inert]'))
   const first=nodes[0],last=nodes.at(-1)
   if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog)){event.preventDefault();last?.focus()}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
  }
  document.addEventListener('keydown',key)
  return()=>{document.removeEventListener('keydown',key);document.body.style.overflow=previousOverflow;if(previous?.isConnected)previous.focus()}
 },[])
 return ref
}
export function useFormExit(dirty:boolean,busy:boolean,onClose:()=>void){
 useEffect(()=>{
  if(!dirty&&!busy)return
  const guard=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''}
  window.addEventListener('beforeunload',guard)
  return()=>window.removeEventListener('beforeunload',guard)
 },[dirty,busy])
 return ()=>{if(!busy&&(!dirty||window.confirm(systemText('放弃未保存的修改？'))))onClose()}
}
export function Modal({title,children,onClose,wide=false}:{title:string;children:ReactNode;onClose:()=>void;wide?:boolean}){
 const ref=useDialog<HTMLDivElement>(onClose)
 return createPortal(<div className="modal-backdrop" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={'modal '+(wide?'wide':'')}><div className="modal-head"><h2>{title}</h2><button className="icon-button" aria-label={systemText("关闭")} onClick={onClose}><X size={20}/></button></div>{children}</div></div>,document.body)
}
export function Notice({message,tone='info',raw=false}:{message:string;tone?:string;raw?:boolean}){return <div role={tone==='error'?'alert':'status'} className={'notice '+tone}>{tone==='success'?<CheckCircle2 size={18}/>:<AlertCircle size={18}/>}<span>{raw?message:systemMessage(message)}</span></div>}
export function Stepper({current}:{current:number}){return <div className="stepper">{['导入计划','自审与说明','复审'].map((name,i)=><div className={i+1===current?'current':i+1<current?'done':''} key={name}><span>{i+1<current?'✓':'0'+(i+1)}</span><strong>{systemText(name)}</strong>{i<2&&<i className="step-arrow">→</i>}</div>)}</div>}
