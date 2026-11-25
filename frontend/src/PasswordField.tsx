import {systemText} from './i18n'
import {useId,useState} from 'react'
import {Eye,EyeOff,KeyRound} from 'lucide-react'
import {tr} from './i18n'
import './review-tools.css'

export default function PasswordField({label,value,onChange,required=false,hint}:{label:string;value:string;onChange:(value:string)=>void;required?:boolean;hint:string}){
 const id=useId()
 const [visible,setVisible]=useState(false)
 function generate(){
  const bytes=crypto.getRandomValues(new Uint8Array(18))
  onChange(btoa(String.fromCharCode(...bytes)).replace(/\+/g,'-').replace(/\//g,'_'))
  setVisible(true)
 }
 return <div className="password-field">
  <label htmlFor={id}>{label}</label>
  <div className="password-field-controls">
   <input id={id} name="new-password" autoComplete="new-password" type={visible?'text':'password'} required={required} minLength={6} maxLength={200} spellCheck={false} autoCapitalize="none" value={value} onChange={e=>onChange(e.target.value)} aria-describedby={id+'-hint'}/>
   <button type="button" className="icon-button" aria-label={visible?tr('隐藏新密码','Hide new password'):tr('显示新密码','Show new password')} aria-pressed={visible} onClick={()=>setVisible(!visible)}>{visible?<EyeOff size={16}/>:<Eye size={16}/>}</button>
   <button type="button" className="secondary compact" onClick={generate}><KeyRound size={14}/>{systemText("生成密码")}</button>
  </div>
  <small id={id+'-hint'}>{hint}</small>
 </div>
}
