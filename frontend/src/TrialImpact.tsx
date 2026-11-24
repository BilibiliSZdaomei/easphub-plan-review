import {useEffect,useState} from 'react'
import {ChevronLeft,ChevronRight} from 'lucide-react'
import {api,flagLabels,fmt,labels} from './api'
import {Busy,Notice} from './ui'

type Outcome = {lower:number|null;upper:number|null;status:string;review_mode?:string;data_status?:string;flags?:string[];delay?:boolean}
type Impact = {material_code:string;material_name?:string;before:Outcome;after:Outcome;new_error_messages?:string[]}
type Result = {items:Impact[];total:number;recorded:number;changed:number;page_size:number}
type Trial = {at:string;rows:number;changed:number;new_errors:string[];baseline_name?:string;snapshot_name?:string}

function outcomeChanges({before,after,new_error_messages}:Impact) {
 const rows:[string,string,string][]=[]
 if (before.lower!==after.lower||before.upper!==after.upper) {
  rows.push(['库存区间',fmt(before.lower)+'–'+fmt(before.upper),fmt(after.lower)+'–'+fmt(after.upper)])
 }
 for (const [field,label] of [['status','数量结论'],['review_mode','审核方式'],['data_status','数据状态']] as const) {
  if (before[field]!==after[field]) {
   const display=(value?:string)=>value==='AUTO'?'自动审核':labels[value||'']||value||'—'
   rows.push([label,display(before[field]),display(after[field])])
  }
 }
 if (!!before.delay!==!!after.delay) rows.push(['建议延迟补货',before.delay?'是':'否',after.delay?'是':'否'])
 const flags=(value?:string[])=>value?.length?value.map(key=>flagLabels[key]||key).join('、'):'无'
 if(flags(before.flags)!==flags(after.flags))rows.push(['人工关注',flags(before.flags),flags(after.flags)])
 if(new_error_messages?.length)rows.push(['新增错误','—',new_error_messages.join('、')])
 return rows
}

export default function TrialImpact({ruleId,proof}:{ruleId:string;proof:Trial}) {
 const [q,setQ]=useState(''),[page,setPage]=useState(1),[result,setResult]=useState<Result|null>(null)
 const [error,setError]=useState(''),[attempt,setAttempt]=useState(0)
 const [errorsOnly,setErrorsOnly]=useState(!proof.changed&&proof.new_errors.length>0)
 useEffect(()=>{
  if(!proof.changed&&!proof.new_errors.length)return
  let active=true
  setResult(null);setError('')
  api<Result>('/rules/'+ruleId+'/trial-impacts?'+new URLSearchParams({q,page:String(page),at:proof.at,errors_only:String(errorsOnly)}))
   .then(data=>{if(active)setResult(data)}).catch(e=>{if(active)setError(e.message)})
  return()=>{active=false}
 },[q,page,ruleId,proof.at,proof.changed,proof.new_errors.length,attempt,errorsOnly])
 const pages=result?Math.max(1,Math.ceil(result.total/result.page_size)):1
 return <div className="trial-result">
  <div>试算 {proof.rows} 行 · 变化 <strong>{proof.changed}</strong> 行 · 新增错误 <strong className={proof.new_errors.length?'text-coral':''}>{proof.new_errors.length}</strong> 行</div>
  {(proof.baseline_name||proof.snapshot_name)&&<p className="muted">{proof.baseline_name&&'对比 '+proof.baseline_name}{proof.snapshot_name&&' · '+proof.snapshot_name}</p>}
  {(proof.changed>0||proof.new_errors.length>0)&&<>
   <div className="list-toolbar"><label className="search"><input type="search" aria-label="搜索试算物料" placeholder="搜索物料号或名称" value={q} onChange={e=>{setQ(e.target.value);setPage(1)}}/></label>
    {proof.new_errors.length>0&&<label className="check-row"><input type="checkbox" checked={errorsOnly} onChange={e=>{setErrorsOnly(e.target.checked);setPage(1)}}/>只看新增错误</label>}</div>
   {error?<><Notice tone="error" message={error}/><button type="button" className="text-button" onClick={()=>setAttempt(n=>n+1)}>重新读取</button></>:!result?<Busy/>:<>
    {result.recorded<result.changed&&<p className="muted">此次旧版试算留存 {result.recorded} / {result.changed} 行明细。</p>}
    <div className="table-scroll"><table><thead><tr><th>物料</th><th>变化项</th><th>现行规则（试算时）</th><th>本版规则</th></tr></thead>
    <tbody>{result.items.map(item=>{
     const changes=outcomeChanges(item)
     if(!changes.length)return <tr key={item.material_code}><td>{item.material_code}<small>{item.material_name}</small></td><td colSpan={3}>旧试算未记录具体字段</td></tr>
     return changes.map(([label,old,value],i)=><tr key={item.material_code+label}>{i===0&&<td rowSpan={changes.length}><span className="mono">{item.material_code}</span><small>{item.material_name}</small></td>}<td>{label}</td><td>{old}</td><td>{value}</td></tr>)
    })}</tbody></table></div>
    {!result.total&&<p>没有匹配的物料</p>}
    {result.total>0&&<div className="table-footer"><span>{(page-1)*result.page_size+1}–{Math.min(page*result.page_size,result.total)} / {result.total} 行物料</span><span className="spacer"/><button type="button" className="icon-button" aria-label="上一页试算物料" disabled={page<=1} onClick={()=>setPage(page-1)}><ChevronLeft size={16}/></button><span>{page} / {pages}</span><button type="button" className="icon-button" aria-label="下一页试算物料" disabled={page>=pages} onClick={()=>setPage(page+1)}><ChevronRight size={16}/></button></div>}
   </>}
  </>}
 </div>
}
