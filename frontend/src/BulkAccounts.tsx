import {useRef, useState} from 'react'
import {Download, FileUp} from 'lucide-react'
import {api} from './api'
import {Modal, Notice, useFormExit} from './ui'

type Warehouse = {code:string;name:string}
type AccountRow = {line:number;username:string;name:string;roles:string[];warehouses:string[];issues:string[]}
type Props = {warehouses:Warehouse[];roles:Record<string,string>;onClose:()=>void;onDone:(count:number)=>void}
const header = ['账号','姓名','初始密码','角色','授权仓库']

function downloadTemplate(){
 const file=new Blob(['\ufeff'+header.join(',')+'\r\n'],{type:'text/csv;charset=utf-8'})
 const url=URL.createObjectURL(file)
 const link=document.createElement('a')
 link.href=url;link.download='批量开户模板.csv';link.click()
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
 return <Modal wide title="批量创建账号" onClose={close}><div className="modal-body">
  {error&&<Notice message={error} tone="error"/>}
  <label>粘贴 Excel 单元格
   <textarea aria-label="粘贴 Excel 单元格" rows={2} value="" readOnly disabled={busy} spellCheck={false}
    placeholder={header.join('　/　')} onPaste={e=>{e.preventDefault();const text=e.clipboardData.getData('text/plain');void preview(async()=>text)}}/>
  </label>
  <div className="actions">
   <button type="button" className="secondary" disabled={busy} onClick={()=>fileInput.current?.click()}><FileUp size={15}/>选择 CSV / TSV</button>
   <input ref={fileInput} type="file" accept=".csv,.tsv,.txt" hidden onChange={e=>{
    const file=e.currentTarget.files?.[0];e.currentTarget.value=''
    if(file)void preview(()=>readFile(file))
   }}/>
   <button type="button" className="text-button" onClick={downloadTemplate}><Download size={15}/>下载模板</button>
  </div>
  <details className="rule-details"><summary>角色与仓库填法</summary>
   <p>角色可填{Object.values(roles).join('、')}。多项用「、」分隔。初始密码 6–200 位。</p>
   <p>仓库可填名称或编码。{warehouses.map(w=>w.name+'（'+w.code+'）').join('、')}</p>
  </details>
  {rows.length>0&&<section><div className="panel-heading"><h2>账号预览</h2><span>{rows.length} 人{invalid>0?' · '+invalid+' 行需修改':''}</span></div>
   <div className="table-scroll"><table><thead><tr><th>行</th><th>姓名 / 账号</th><th>角色</th><th>授权仓库</th><th>校验</th></tr></thead>
    <tbody>{rows.map(row=><tr key={row.line}><td>{row.line}</td><td><strong>{row.name}</strong><small>{row.username}</small></td>
     <td>{row.roles.map(r=>roles[r]).join('、')}</td>
     <td>{row.warehouses.map(code=>warehouses.find(w=>w.code===code)?.name||code).join('、')}</td>
     <td>{row.issues.length?row.issues.join('；'):'可创建'}</td>
    </tr>)}</tbody></table></div>
  </section>}
  <div className="modal-actions"><button type="button" className="secondary" disabled={busy} onClick={close}>取消</button>
   <button type="button" className="primary" disabled={busy||!rows.length||invalid>0||!source.current} onClick={create}>
    {busy?'正在处理…':rows.length&&!invalid?'创建 '+rows.length+' 个账号':'创建账号'}
   </button>
  </div>
 </div></Modal>
}
