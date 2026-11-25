import LanguageSwitcher from './LanguageSwitcher'
import {systemText} from './i18n'
import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {Expand,Maximize2,Minimize2,Shrink} from 'lucide-react'
import './plan-focus.css'

export function usePlanFocus(notify:(message:string)=>void){
 const [active,setActive]=useState(false),[full,setFull]=useState(false)
 const button=useRef<HTMLButtonElement>(null)
 const previousScroll=useRef(0),requestedFull=useRef(false)
 function enter(){
  previousScroll.current=window.scrollY
  setActive(true)
 }
 function exit(){
  setActive(false)
 }
 useLayoutEffect(()=>{
  if(!active)return
  function update(){setFull(document.fullscreenElement===document.documentElement)}
  update()
  document.addEventListener('fullscreenchange',update)
  const toggle=button.current
  return ()=>{
   document.removeEventListener('fullscreenchange',update)
   if(requestedFull.current&&document.fullscreenElement===document.documentElement){
    void document.exitFullscreen().catch(()=>{})
   }
   requestedFull.current=false
   // Wait until the normal page is laid out before restoring the reading position.
   requestAnimationFrame(()=>{
    if(toggle?.isConnected){
     window.scrollTo({top:previousScroll.current,behavior:'instant'})
     toggle.focus({preventScroll:true})
    }
   })
  }
 },[active])
 useEffect(()=>{
  if(!active)return
  function escape(event:KeyboardEvent){
   if(event.key!=='Escape'||event.isComposing||event.defaultPrevented||document.fullscreenElement)return
   if(document.querySelector('[role="dialog"]'))return
   const details=document.activeElement?.closest<HTMLDetailsElement>('details[open]')
   if(details){
    details.open=false
    details.querySelector('summary')?.focus()
   }else exit()
   event.preventDefault()
  }
  window.addEventListener('keydown',escape)
  return ()=>window.removeEventListener('keydown',escape)
 },[active])
 async function toggleFull(){
  try{
   if(document.fullscreenElement===document.documentElement){
    await document.exitFullscreen()
   }else{
    requestedFull.current=true
    await document.documentElement.requestFullscreen()
    if(!requestedFull.current&&document.fullscreenElement===document.documentElement){
     await document.exitFullscreen()
    }
   }
  }catch{
   notify(systemText("浏览器未允许切换全屏，可继续使用专注模式"))
  }
 }
 return {active,full,button,enter,exit,toggleFull}
}

export function FocusControls({focus}:{focus:ReturnType<typeof usePlanFocus>}){
 return <>
  {focus.active&&<LanguageSwitcher/>}
  {focus.active&&document.fullscreenEnabled&&<button className="text-button plan-native-full" type="button" title={focus.full?systemText("退出浏览器全屏"):systemText("浏览器全屏")} aria-label={focus.full?systemText("退出浏览器全屏"):systemText("浏览器全屏")} aria-pressed={focus.full} onClick={focus.toggleFull}>{focus.full?<Shrink size={16}/>:<Expand size={16}/>}<span>{focus.full?systemText("退出全屏"):systemText("全屏")}</span></button>}
  <button ref={focus.button} className="secondary compact plan-focus-toggle" type="button" aria-pressed={focus.active} onClick={focus.active?focus.exit:focus.enter}>{focus.active?<Minimize2 size={15}/>:<Maximize2 size={15}/>} {focus.active?systemText("退出专注"):systemText("专注模式")}</button>
 </>
}
