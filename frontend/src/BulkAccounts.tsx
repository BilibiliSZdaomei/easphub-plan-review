import {tr, warehouseName, systemText} from './i18n'
import WarehouseLabel,{orderedWarehouseCodes} from './WarehouseLabel'
import {useRef, useState} from 'react'
import {Download, FileUp} from 'lucide-react'
import {api} from './api'
import {emailAddress} from './accountEmail'
import {Modal, Notice, useFormExit} from './ui'

type Warehouse = {code:string;name:string}
type AccountRow = {line:number;username:string;name:string;roles:string[];warehouses:string[];email?:string|null;issues:string[]}
type Props = {warehouses:Warehouse[];roles:Record<string,string>;onClose:()=>void;onDone:(count:number)=>void}
const header = ['账号','姓名','初始密码','角色','授权仓库','通知邮箱']

const englishHeader = ['Username','Name','Initial password','Role','Authorized warehouses','Notification email']
function downloadTemplate(){
 const file=new Blob(['\ufeff'+tr(header.join(','), englishHeader.join(','))+'\r\n'],{type:'text/csv;charset=utf-8'})
 const url=URL.createObjectURL(file)
 const link=document.createElement('a')
 link.href=url;link.download=tr('批量开户模板.csv','accounts-template.csv');link.click()
 window.setTimeout(()=>URL.revokeObjectURL(url),1000)
}

async function readFile(file:File){
 if(file.size>1024*1024)throw new Error('文件过大，每批最多 100 人')
 const bytes=new Uint8Array(await file.arrayBuffer())
 if(bytes[0]===255&&bytes[1]===254)return new TextDecoder('utf-16le').decode(bytes)
 if(bytes[0]===254&&bytes[1]===255)return new TextDecoder('utf-16be').decode(bytes)
 try{return new TextDecoder('utf-8',{fatal:true}).decode(bytes)}
 catch{return new TextDecoder('gb18030').decode(bytes)}
}

export default function BulkAccounts({warehouses,roles,onClose,onDone}:Props){
 const [rows,setRows]=useState<AccountRow[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const source=useRef(''),operation=useRef(''),fileInput=useRef<HTMLInputElement>(null)
 const close=useFormExit(!!source.current,busy,onClose)
 const invalid=rows.filter(r=>r.issues.length).length
 async function preview(load:()=>Promise<string>){
  if(busy)return
  setBusy(true);setError('');setRows([]);source.current='';operation.current=''
  try{
   const table=await load()
   const response=await api<{rows:AccountRow[]}>('/users/bulk/preview',{table})
   setRows(response.rows)
   if(response.rows.every(row=>!row.issues.length)){
    source.current=table
    operation.current=crypto.randomUUID()
   }
  }catch(e:any){setError(e.message)}finally{setBusy(false)}
 }
 async function create(){
  if(!source.current||invalid||busy)return
  setBusy(true);setError('')
  try{
   const result=await api<{created:number}>('/users/bulk',{table:source.current},'POST',operation.current)
   source.current='';onDone(result.created)
  }catch(e:any){
   if(Array.isArray(e.detail?.rows)){setRows(e.detail.rows);source.current=''}
   setError(e.message)
  }finally{setBusy(false)}
 }
 return <Modal wide title={systemText("批量创建账号")} onClose={close}><div className="modal-body" data-usage-private>
  {error&&<Notice message={error} tone="error"/>}
  <label>{systemText("粘贴 Excel 单元格")}<textarea aria-label={systemText("粘贴 Excel 单元格")} rows={2} value="" readOnly disabled={busy} spellCheck={false}
    placeholder={tr(header.join('　/　'),englishHeader.join(' / '))} onPaste={e=>{e.preventDefault();const text=e.clipboardData.getData('text/plain');void preview(async()=>text)}}/>
  </label>
  <div className="actions">
   <button type="button" className="secondary" disabled={busy} onClick={()=>fileInput.current?.click()}><FileUp size={15}/>{systemText("选择 CSV / TSV")}</button>
   <input ref={fileInput} type="file" accept=".csv,.tsv,.txt" hidden onChange={e=>{
    const file=e.currentTarget.files?.[0];e.currentTarget.value=''
    if(file)void preview(()=>readFile(file))
   }}/>
   <button type="button" className="text-button" onClick={downloadTemplate}><Download size={15}/>{systemText("下载模板")}</button>
  </div>
  <details className="rule-details"><summary>{systemText("角色与仓库填法")}</summary>
   <p>{tr(`角色可填${Object.values(roles).join('、')}，每人选一个。多个仓库用「、」分隔。初始密码 6–200 位。`, 'Use PLANNER, REVIEWER or ADMIN. Enter one role per person. Separate warehouse codes with a semicolon. Initial passwords must be 6–200 characters.')}</p>
   <p>{tr('仓库可留空，之后在人员与权限中分配。可选仓库：','Leave blank to assign warehouse access later. Available warehouses: ')}{warehouses.map(w=>tr(w.name+'（'+w.code+'）',warehouseName(w.name)+' ('+w.code+')')).join(tr('、',', '))}</p>
   <p>{tr('通知邮箱选填。账号本身是邮箱时，留空即可使用登录邮箱收件。','Notification email is optional. Leave it blank to receive mail at an email-based username.')}</p>
  </details>
  {rows.length>0&&<section><div className="panel-heading"><h2>{systemText("账号预览")}</h2><span>{rows.length}{tr(' 人',' users')}{invalid>0?tr(' · '+invalid+' 行需修改',' · Rows requiring changes: '+invalid):''}</span></div>
   <div className="table-scroll"><table><thead><tr><th>{systemText("行")}</th><th>{systemText("姓名 / 账号")}</th><th>{systemText("角色")}</th><th>{systemText("授权仓库")}</th><th>{tr('通知邮箱','Notification email')}</th><th>{systemText("校验")}</th></tr></thead>
    <tbody>{rows.map(row=><tr key={row.line}><td>{row.line}</td><td><strong>{row.name}</strong><small>{row.username}</small></td>
     <td>{row.roles.map(r=>systemText(roles[r])).join(tr('、',', '))}</td>
     <td><div className="people-warehouses">{!row.warehouses.length&&<span className="muted">{systemText('尚未授权')}</span>}{orderedWarehouseCodes(row.warehouses,warehouses).map(code=><WarehouseLabel key={code} code={code}/>)}</div></td>
     <td>{row.email||emailAddress(row.username)||'—'}</td><td>{row.issues.length?row.issues.map(issue=>systemText(issue)).join(tr('；','; ')):systemText("可创建")}</td>
    </tr>)}</tbody></table></div>
  </section>}
  <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>{systemText("取消")}</button>
   <button type="button" className="primary" disabled={busy||!rows.length||invalid>0||!source.current} onClick={create}>
    {busy?systemText("正在处理…"):rows.length&&!invalid?tr('创建 '+rows.length+' 个账号','Create accounts ('+rows.length+')'):systemText("创建账号")}
   </button>
  </div>
 </div></Modal>
}
