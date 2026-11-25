import {useContext,useEffect,useRef,useState,type FormEvent} from 'react'
import {ChevronDown,KeyRound,LogOut,Pencil,UserRound,ChartColumn} from 'lucide-react'
import {api,APP_BASE} from './api'
import {tr,systemText} from './i18n'
import {roleNames} from './roles'
import {Modal,Notice} from './ui'
import WarehouseLabel,{WarehouseCatalog,orderedWarehouseCodes} from './WarehouseLabel'
import AvatarEditor from './AvatarEditor'
import {avatarSrc,equalConfig,presetConfigs,type AvatarConfig} from './personas'
import './personal-account.css'

type Preset=keyof typeof presetConfigs
const presets=Object.keys(presetConfigs) as Preset[]
function currentPreset(value?:string):Preset | 'blank' {
  return value && Object.hasOwn(presetConfigs,value)?value as Preset:'blank'
}

export type ProfileUser={
  id:string;username:string;name:string;roles:string[];warehouses:string[]
  avatar_preset?:string;avatar_config?:AvatarConfig|null;email?:string|null;notification_email?:string|null
}

export function AccountAvatar({preset,config,size=32}:{preset?:string;config?:AvatarConfig|null;size?:number}){
  const key=currentPreset(preset)
  const blank=!config&&key==='blank'
  const src=config?avatarSrc(config):blank?APP_BASE+'/assets/avatar-blank.svg':APP_BASE+'/assets/personas-7b5234c44b3c/personas-'+key+'.svg'
  return <img className={'personas-avatar'+(blank?' avatar-blank':'')} alt="" src={src} width={size} height={size}/>
}

function Profile({user,onSaved,onClose,onPassword,onUsage}:{
  user:ProfileUser;onSaved:(user:ProfileUser)=>void;onClose:()=>void;onPassword:()=>void;onUsage?:()=>void
}){
  const preset=currentPreset(user.avatar_preset)
  const original=user.avatar_config??(preset==='blank'?null:presetConfigs[preset])
  const [editing,setEditing]=useState(false),[choice,setChoice]=useState(original)
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  const [email,setEmail]=useState(user.notification_email)
  useEffect(()=>{
    const controller=new AbortController()
    api<{user:ProfileUser}>('/me',undefined,'GET',undefined,controller.signal)
      .then(result=>{if(!controller.signal.aborted)setEmail(result.user.notification_email)})
      .catch(()=>{/* The session profile still has the last known address. */})
    return ()=>controller.abort()
  },[user.id,user.notification_email])
  const catalog=useContext(WarehouseCatalog)
  const codes=orderedWarehouseCodes(user.warehouses,catalog)
  const editButton=useRef<HTMLButtonElement>(null),preview=useRef<HTMLDivElement>(null)
  const changed=choice&&original?!equalConfig(choice,original):choice!==original
  async function save(e:FormEvent){
    e.preventDefault()
    if(busy||!changed)return
    setBusy(true);setError('')
    try {
      const matchingPreset=choice?presets.find(key=>equalConfig(choice,presetConfigs[key])):'blank'
      const updated=await api<ProfileUser>('/profile/avatar',matchingPreset?{avatar_preset:matchingPreset}:{avatar_config:choice},'PATCH')
      onSaved(updated)
    }catch(e){setError(e instanceof Error?e.message:tr('头像保存失败','Could not save avatar'))}
    finally{setBusy(false)}
  }
  function cancelEdit(){
    if(busy)return
    setEditing(false);setChoice(original);setError('')
    requestAnimationFrame(()=>editButton.current?.focus())
  }
  function edit(){
    setChoice(original);setError('');setEditing(true)
    requestAnimationFrame(()=>preview.current?.focus())
  }
  return <Modal title={editing?tr('自定义头像','Customize avatar'):tr('个人账户','My account')} onClose={editing?cancelEdit:onClose}>
    {editing?<form className="profile-editor-form" onSubmit={save} noValidate={choice===null}>
      <div className="profile-preview" ref={preview} tabIndex={-1} role="group" aria-label={tr('头像预览','Avatar preview')}>
        <AccountAvatar config={choice} size={88}/>
        <span>{user.name||user.username}</span>
        <button type="button" className="profile-default-button" aria-pressed={choice===null} disabled={busy} onClick={()=>setChoice(null)}>
          <UserRound size={15} aria-hidden="true"/>{tr('默认头像','Default avatar')}
        </button>
      </div>
      <div className="profile-editor-scroll">
        <AvatarEditor value={choice} onChange={setChoice} disabled={busy}/>
        {error&&<Notice message={error} tone="error"/>}
      </div>
      <div className="profile-editor-footer">
        <button type="button" className="secondary" disabled={busy} onClick={cancelEdit}>{systemText('取消')}</button>
        <button type="submit" className="primary" disabled={busy||!changed}>{busy?systemText('正在保存…'):tr('保存头像','Save avatar')}</button>
      </div>
    </form>:<div className="profile-card">
      <div className="profile-identity"><button type="button" onClick={edit} aria-label={tr('编辑账户头像','Edit account avatar')} className="profile-image-button">
        <AccountAvatar preset={user.avatar_preset} config={user.avatar_config} size={64}/><Pencil size={14} aria-hidden="true"/>
      </button><div><strong>{user.name||user.username}</strong><button ref={editButton} type="button" onClick={edit} className="text-button profile-edit-button">{tr('自定义头像','Customize avatar')}</button></div></div>
      <dl className="profile-facts">
        <div><dt>{systemText('登录账号')}</dt><dd>{user.username}</dd></div>
        <div><dt>{tr('角色','Role')}</dt><dd>{roleNames[user.roles[0]]||systemText('待分配')}</dd></div>
        <div><dt>{tr('通知邮箱','Notification email')}</dt><dd>{email||tr('尚未设置','Not set')}
          <small className="profile-email-help">{email?tr('如需更改，请联系管理员。','Contact an administrator to change it.'):tr('请联系管理员设置收件邮箱。','Ask an administrator to add your email.')}</small>
        </dd></div>
      </dl>
      {codes.length?<details className="profile-access">
        <summary><span>{tr('授权仓库','Warehouse access')}</span><span>{tr(codes.length+' 个仓库',codes.length+(codes.length===1?' warehouse':' warehouses'))}<ChevronDown size={15} aria-hidden="true"/></span></summary>
        <div className="profile-warehouses">{codes.map(code=><WarehouseLabel key={code} code={code}/>)}</div>
      </details>:<div className="profile-access profile-access-empty"><span>{tr('授权仓库','Warehouse access')}</span><span>{tr('尚未分配','None assigned')}</span></div>}
      <div className="profile-actions">{onUsage&&<button type="button" className="text-button" onClick={onUsage}><ChartColumn size={15}/>{tr('我的使用情况','My usage')}</button>}<button type="button" className="text-button" onClick={onPassword}><KeyRound size={15}/>{systemText('修改密码')}</button></div>
    </div>}
  </Modal>
}

export default function PersonalAccount({user,onUpdate,onPassword,onLogout,onUsage,onProfileChange}:{
  user:ProfileUser;onUpdate:(updated:ProfileUser)=>void;onPassword:()=>void;onLogout:()=>void;onUsage?:()=>void;onProfileChange:(open:boolean)=>void
}){
  const [profile,setProfile]=useState(false)
  useEffect(()=>{onProfileChange(profile);return ()=>onProfileChange(false)},[profile,onProfileChange])
  const [menuOpen,setMenuOpen]=useState(false)
  const menu=useRef<HTMLDetailsElement>(null)
  const name=user.name||user.username
  function closeMenu(focus=false){
    if(menu.current)menu.current.open=false
    if(focus)menu.current?.querySelector('summary')?.focus()
  }
  useEffect(()=>{
    if(!menuOpen)return
    const outside=(e:PointerEvent)=>{if(!menu.current?.contains(e.target as Node))closeMenu()}
    const escape=(e:KeyboardEvent)=>{if(e.key==='Escape'&&menu.current?.open){e.stopPropagation();closeMenu(true)}}
    document.addEventListener('pointerdown',outside)
    document.addEventListener('keydown',escape,true)
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape,true)}
  },[menuOpen])
  const usage=onUsage?()=>{closeMenu(true);setProfile(false);onUsage()}:undefined
  function password(){closeMenu(true);setProfile(false);onPassword()}
  return <>
    <details ref={menu} className="account" id="ea-account-menu" onToggle={e=>setMenuOpen(e.currentTarget.open)}>
      <summary aria-label={tr(name+'，账户菜单',name+', account menu')}><AccountAvatar preset={user.avatar_preset} config={user.avatar_config}/>
        <span className="profile-menu-name">{name}<small>{roleNames[user.roles[0]]||systemText('待分配')}</small></span><ChevronDown size={13}/></summary>
      <div className="dropdown">
        <button type="button" onClick={()=>{closeMenu(true);setProfile(true)}}><UserRound size={15}/>{tr('个人账户','My account')}</button>
        {usage&&<button type="button" onClick={usage}><ChartColumn size={15}/>{tr('我的使用情况','My usage')}</button>}
        <button type="button" onClick={password}><KeyRound size={15}/>{systemText('修改密码')}</button>
        <button type="button" onClick={()=>{closeMenu(true);onLogout()}}><LogOut size={15}/>{systemText('退出登录')}</button>
      </div>
    </details>
    {profile&&<Profile user={user} onClose={()=>setProfile(false)} onPassword={password} onUsage={usage} onSaved={updated=>{onUpdate(updated);setProfile(false)}}/>}
  </>
}
