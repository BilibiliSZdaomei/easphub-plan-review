import {AccountAvatar,type ProfileUser} from './PersonalAccount'
import {tr, systemText, warehouseName} from './i18n'
import PasswordField from './PasswordField'
import {useState,useEffect,FormEvent} from 'react'
import {ChevronDown,Plus,Search,Users} from 'lucide-react'
import WarehouseLabel,{orderedWarehouseCodes,WarehouseSelect,type WarehouseInfo} from './WarehouseLabel'
import './people.css'
import BulkAccounts from './BulkAccounts'
import {api} from './api'
import {emailAddress} from './accountEmail'
import {Badge,Busy,Empty,Modal,Notice,useFormExit} from './ui'

import {roleNames as roles} from './roles'
type Person=ProfileUser & {active:boolean}

function WarehouseAccess({codes}:{codes:string[]}){
 if(!codes.length)return <span className="muted">{systemText("尚未授权")}</span>
 const labels=(list:string[])=>list.map(code=><WarehouseLabel key={code} code={code}/>)
 if(codes.length<=2)return <div className="people-warehouses">{labels(codes)}</div>
 return <details className="people-access">
  <summary><span className="people-warehouses">{labels(codes.slice(0,2))}</span><span className="people-more">{tr(`另 ${codes.length-2} 仓`, `+${codes.length-2} more`)} <ChevronDown size={13} aria-hidden="true"/></span></summary>
  <div className="people-warehouses">{labels(codes.slice(2))}</div>
 </details>
}

export default function Accounts({warehouses,user,notify}:{warehouses:WarehouseInfo[];user:Person;notify:(s:string)=>void}){
 const [bulk,setBulk]=useState(false),[editing,setEditing]=useState<any>(null)
 const [list,setList]=useState<Person[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState('')
 const [search,setSearch]=useState(''),[role,setRole]=useState(''),[warehouse,setWarehouse]=useState(''),[status,setStatus]=useState('')
 async function load(){
  setError('')
  try{setList(await api('/users'))}catch(e:any){setError(e.message)}finally{setLoading(false)}
 }
 useEffect(()=>{load()},[])
 const term=search.trim().toLocaleLowerCase()
 const filtered=list.filter(p=>(!role||p.roles.includes(role))&&(!warehouse||p.warehouses.includes(warehouse))
  &&(!status||p.active===(status==='active'))&&(!term||[p.name,p.username].some(value=>value.toLocaleLowerCase().includes(term))))
 const hasFilter=!!(term||role||warehouse||status)
 function reset(){setSearch('');setRole('');setWarehouse('');setStatus('')}
 return <>
  <div className="page-heading"><div><h1>{systemText("人员与权限")}</h1></div><div className="actions">
   <button className="secondary" onClick={()=>setBulk(true)}><Users size={16}/>{systemText("批量创建")}</button>
   <button className="primary" onClick={()=>setEditing({roles:['PLANNER'],warehouses:[],active:true})}><Plus size={16}/>{systemText("添加人员")}</button>
  </div></div>
  {error&&<><Notice message={error} tone="error"/><button className="text-button" onClick={load}>{systemText("重新读取人员")}</button></>}
  <section className="panel people-panel" aria-label={systemText("已授权人员")}>
   <div className="panel-heading"><h2>{systemText("已授权人员")}</h2>{!loading&&<span aria-live="polite">{hasFilter?filtered.length+' / ':''}{list.length}{tr(' 人',' users')}</span>}</div>
   <div className="list-toolbar people-filters">
    <label className="search"><Search size={16}/><input aria-label={systemText("搜索姓名或账号")} placeholder={systemText("搜索姓名或账号")} value={search} onChange={e=>setSearch(e.target.value)}/></label>
    <select aria-label={systemText("筛选人员角色")} value={role} onChange={e=>setRole(e.target.value)}><option value="">{systemText("全部角色")}</option>{Object.entries(roles).map(([key,label])=><option key={key} value={key}>{systemText(label)}</option>)}</select>
    <WarehouseSelect aria-label={systemText("筛选人员仓库权限")} value={warehouse} onChange={e=>setWarehouse(e.target.value)}><option value="">{systemText("全部仓库权限")}</option>{warehouses.map(w=><option key={w.code} value={w.code}>{warehouseName(w.name)}</option>)}</WarehouseSelect>
    <select aria-label={systemText("筛选账号状态")} value={status} onChange={e=>setStatus(e.target.value)}><option value="">{systemText("全部状态")}</option><option value="active">{systemText("使用中")}</option><option value="inactive">{systemText("已停用")}</option></select>
    {hasFilter&&<button className="text-button" onClick={reset}>{systemText("清除筛选")}</button>}
   </div>
   {loading?<Busy/>:filtered.length?<div className="table-scroll"><table aria-label={systemText("人员列表")}><thead><tr><th>{systemText("姓名 / 账号")}</th><th>{systemText("角色")}</th><th>{systemText("可访问仓库")}</th><th>{tr('通知邮箱','Notification email')}</th><th>{systemText("状态")}</th><th aria-label={systemText("操作")}/></tr></thead>
    <tbody>{filtered.map(u=><tr key={u.id}>
     <td><div className="people-profile"><AccountAvatar preset={u.id===user.id?user.avatar_preset:u.avatar_preset} config={u.id===user.id?user.avatar_config:u.avatar_config}/><div><strong>{u.name}</strong><small>{u.username}{u.id===user.id?tr(' · 当前账号',' · You'):''}</small></div></div></td>
     <td><div className="role-tags"><span>{systemText(roles[u.roles[0]]||'待分配')}</span></div></td>
     <td><WarehouseAccess codes={orderedWarehouseCodes(u.warehouses,warehouses)}/></td><td className="people-email">{u.notification_email||'—'}</td><td><Badge value={u.active?'WITHIN':'VOID'} label={u.active?systemText("使用中"):systemText("已停用")}/></td>
     <td><button className="text-button" aria-label={tr('管理权限 '+u.name,'Manage access for '+u.name)} onClick={()=>setEditing(u)}>{systemText("管理权限 →")}</button></td>
    </tr>)}</tbody></table></div>:!error&&<Empty title={hasFilter?systemText("没有符合条件的人员"):systemText("暂无已授权人员")}/>}
  </section>
  {bulk&&<BulkAccounts warehouses={warehouses} roles={roles} onClose={()=>setBulk(false)} onDone={n=>{setBulk(false);load();notify(tr(`已创建 ${n} 个账号`,`Accounts created: ${n}`))}}/>}
  {editing&&<AccountForm value={editing} warehouses={warehouses} user={user} onClose={()=>setEditing(null)} onDone={()=>{setEditing(null);load();notify(tr('人员信息已保存','Account details saved'))}}/>}
 </>
}
function AccountForm({value,warehouses,user,onClose,onDone}:{value:any;warehouses:any[];user:any;onClose:()=>void;onDone:()=>void}){
 const [data,setData]=useState({...value,name:value.name||'',username:value.username||'',email:value.email||'',password:''}),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const sameMembers=(left:string[],right:string[])=>left.length===right.length&&left.every(id=>right.includes(id))
 const changes:Record<string,unknown>={}
 if(data.email!==(value.email||''))changes.email=data.email
 if(data.password)changes.password=data.password
 if(data.active!==value.active)changes.active=data.active
 if(!sameMembers(value.roles,data.roles))changes.roles=data.roles
 if(!sameMembers(value.warehouses,data.warehouses))changes.warehouses=data.warehouses
 const dirty=Object.keys(changes).length>0||data.name!==(value.name||'')||data.username!==(value.username||'')
 const loginEmail=emailAddress(data.username)
 const close=useFormExit(dirty,busy,onClose)
 function toggle(key:string,v:string){setData({...data,[key]:data[key].includes(v)?data[key].filter((x:string)=>x!==v):[...data[key],v]})}
 async function submit(e:FormEvent){e.preventDefault();setBusy(true);try{await api(value.id?'/users/'+value.id:'/users',value.id?changes:data,value.id?'PATCH':'POST');onDone()}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <Modal title={value.id?systemText("管理人员权限"):systemText("添加人员")} onClose={close}><form className="modal-body" data-usage-private onSubmit={submit} inert={busy||undefined}>{error&&<Notice message={error} tone="error"/>}<div className="form-grid"><label>{systemText("姓名")}<input required disabled={!!value.id} value={data.name} onChange={e=>setData({...data,name:e.target.value})}/></label><label>{systemText("登录账号")}<input required disabled={!!value.id} autoComplete="off" value={data.username} onChange={e=>setData({...data,username:e.target.value})}/></label></div>
 <label>{tr('通知邮箱（选填）','Notification email (optional)')}
  <input type="email" maxLength={254} autoComplete="off" spellCheck={false} value={data.email} placeholder={loginEmail||'name@example.com'}
    onChange={e=>{
      const email=e.currentTarget.value
      e.currentTarget.setCustomValidity(email.trim()&&!emailAddress(email)?tr('请填写一个有效的通知邮箱','Enter one valid notification email address.'):'')
      setData({...data,email})
    }}/>
  {!data.email&&loginEmail&&<small>{tr('留空使用登录邮箱','Leave blank to use the login email')} · {loginEmail}</small>}
 </label>
 <PasswordField label={value.id?systemText("重设密码（留空保留原密码）"):systemText("初始密码")} value={data.password} onChange={password=>setData({...data,password})} required={!value.id} hint={systemText("6–200 位。密码或权限变更后，现有登录立即失效。")}/><label>{systemText("角色")}<select required disabled={value.id===user.id} value={data.roles[0]||''} onChange={e=>setData({...data,roles:[e.target.value]})}><option value="" disabled>{systemText("请选择角色")}</option>{Object.entries(roles).map(([key,name])=><option key={key} value={key}>{systemText(name)}</option>)}</select></label><fieldset><legend>{systemText("授权仓库")}</legend><div className="check-grid">{warehouses.map(w=><label className="check-row" key={w.code}><input type="checkbox" checked={data.warehouses.includes(w.code)} onChange={()=>toggle('warehouses',w.code)}/><WarehouseLabel code={w.code} name={w.name}/></label>)}</div></fieldset>{value.id&&<label className="check-row"><input type="checkbox" disabled={value.id===user.id} checked={data.active} onChange={e=>setData({...data,active:e.target.checked})}/>{systemText("允许此账号登录")}</label>}<div className="modal-actions"><button type="button" className="secondary" onClick={close}>{systemText("取消")}</button><button className="primary" disabled={busy||!dirty||!data.roles.length}>{busy?systemText("正在保存…"):systemText("保存权限")}</button></div></form></Modal>
}
