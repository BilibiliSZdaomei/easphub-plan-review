import {useState,useEffect} from 'react'
import {Plus,FlaskConical,Send,Save,ArrowLeft} from 'lucide-react'
import {api,date} from './api'
import {canReview} from './roles'
import TrialImpact from './TrialImpact'
import {Modal,Notice,Badge} from './ui'
import SnapshotPicker,{sortSnapshots} from './SnapshotPicker'

import CreateRule,{RuleFields,collectPackage,initialSource,overrideText,scopeLabel} from './RuleForm'

export default function RuleCenter({warehouses,warehouse,notify,user,onDirty}:{warehouses:any[];warehouse:string;notify:(s:string)=>void;user:any;onDirty:(dirty:boolean)=>void}){
 const [v3Defaults,setV3Defaults]=useState<Record<string,string|number>>({})
 const [v2Defaults,setV2Defaults]=useState<Record<string,string|number>>({})
 const [coverage,setCoverage]=useState<Record<string,string|null>>({})
 const [list,setList]=useState<any[]>([]),[labels,setLabels]=useState<Record<string,string>>({}),[selected,setSelected]=useState<any>(null),[pkg,setPkg]=useState<any>(null),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[snaps,setSnaps]=useState<any[]>([]),[snapshot,setSnapshot]=useState(''),[creating,setCreating]=useState<any>(null),[publish,setPublish]=useState(false),[note,setNote]=useState(''),[overrides,setOverrides]=useState(''),[publishReason,setPublishReason]=useState('')
 async function load(){const r=await api('/rules');setList(r.items);setLabels(r.labels);setCoverage(r.coverage);setV2Defaults(r.v2_defaults || {});setV3Defaults(r.v3_defaults || {})}
 useEffect(()=>{load().catch(e=>setError(e.message));api('/snapshots').then(setSnaps).catch(e=>setError(e.message))},[])
 useEffect(()=>{onDirty(dirty||(publish&&publishReason!==note))},[dirty,publish,publishReason,note,onDirty])
 useEffect(()=>()=>onDirty(false),[onDirty])
 const availableSnaps=sortSnapshots(snaps.filter(s=>{
  if(selected?.scope==='WAREHOUSE')return s.warehouse===selected.scope_code
  if(selected?.scope==='MARKET')return warehouses.some(w=>w.code===s.warehouse&&w.market===selected.scope_code)
  if(selected?.scope==='DEFAULT'&&selected.scope_code==='EUROPE')return warehouses.some(w=>w.code===s.warehouse&&w.region==='EUROPE')
  return true
 }))
 useEffect(()=>{
  const trialId=selected?.proof?.snapshot_id
  setSnapshot(availableSnaps.some(s=>s.id===trialId)?trialId:availableSnaps[0]?.id||'')
 },[selected?.id,selected?.proof?.snapshot_id,snaps,warehouses])
 function backToList(){
  if(busy||(dirty&&!window.confirm('放弃未保存的规则修改？')))return
  setDirty(false);setSelected(null);setError('')
 }
 function closePublish(){
  if(!busy&&(publishReason===note||window.confirm('放弃本次发布说明？')))setPublish(false)
 }
 function choose(r:any){setSelected(r);setPkg(structuredClone(r.package));setNote(r.note||'');setOverrides(overrideText(r.package));setDirty(false);setError('')}
 async function action(fn:()=>Promise<any>,message:string){setBusy(true);setError('');try{const r=await fn();choose(r);setList(items=>items.map(item=>item.id===r.id?r:item));load().catch(e=>setError(e.message));notify(message);return true}catch(e:any){setError(e.message);return false}finally{setBusy(false)}}
 const draft=selected?.state==='DRAFT',publisher=canReview(user.roles)
 const canEdit=publisher
 const published=list.filter(r=>r.state==='PUBLISHED')
 const defaultSource=initialSource(published,coverage,warehouse || (warehouses.length===1?warehouses[0].code:''))
 function openCreator(source:any){setCreating(source);setError('')}
 function savedNew(r:any){
  setCreating(null);choose(r);setList(items=>[r,...items]);load().catch(e=>setError(e.message));notify('新标准已保存为草稿')
 }
 function saveDraft(){
  try {
   const edited=collectPackage(pkg,overrides)
   action(()=>api('/rules/'+selected.id,{revision:selected.revision,package:edited,note},'PATCH'),'规则草稿已保存')
  } catch(e:any){setError(e.message)}
 }
 if(creating)return <CreateRule initial={creating} sources={published} warehouses={warehouses} labels={labels}
   v2Defaults={v2Defaults} v3Defaults={v3Defaults} onCreated={savedNew} onClose={()=>setCreating(null)} onDirty={onDirty}/>
 return <><div className="page-heading"><div><h1>审核标准</h1></div>
  {!selected&&canEdit&&<button className="primary" disabled={!defaultSource} onClick={()=>openCreator(defaultSource)}><Plus size={16}/>新建标准</button>}
 </div>{error&&<Notice message={error} tone="error"/>}{selected?<><div className="rule-title"><button className="back-link" disabled={busy} onClick={backToList}><ArrowLeft size={15}/>返回标准列表</button><span className="spacer"/><Badge value={draft?'DRAFT':'APPROVED'} label={draft?'规则草稿':selected.active?'当前使用':'历史版本'}/></div><section className="panel"><div className="panel-heading"><div><h2>{selected.name}</h2><span>{scopeLabel(selected,warehouses)}</span></div>{!draft&&canEdit&&<button className="secondary" onClick={()=>openCreator(selected)}><Plus size={15}/>基于此标准新建</button>}</div><div className="rule-intro">{pkg.model==='V3'?'V3 未来库存＝在库数量＋审核前净额＋海运计划。':'目标库存 X/Y 取自数据快照。下列月数用于审核判断。'}</div><RuleFields key={selected.id} warehouse={selected.scope==='WAREHOUSE'?selected.scope_code:undefined} pkg={pkg} labels={labels} overrides={overrides} disabled={!draft||!canEdit||busy}
  onPackage={value=>{setPkg(value);setDirty(true)}} onOverrides={value=>{setOverrides(value);setDirty(true)}}/>{draft&&canEdit&&<div className="rule-edit-footer"><label>本次修改说明<input disabled={busy} value={note} onChange={e=>{setNote(e.target.value);setDirty(true)}} placeholder="说明调整原因"/></label><button className="primary" disabled={!dirty||busy} onClick={saveDraft}><Save size={16}/>保存草稿</button></div>}</section>{draft&&<section className="panel trial-panel"><div className="panel-heading"><h2>试算与发布</h2></div><div className="trial-controls"><SnapshotPicker label="测试数据快照" snapshots={availableSnaps} value={snapshot} onChange={setSnapshot} disabled={busy}/><button className="secondary" disabled={!canEdit||dirty||busy||!snapshot} onClick={()=>action(()=>api(`/rules/${selected.id}/dry-run`,{revision:selected.revision,snapshot_id:snapshot}),'规则试算已完成')}><FlaskConical size={16}/>{busy?'正在处理…':'运行试算'}</button>{publisher&&<button className="primary" disabled={dirty||busy||!selected.proof||selected.proof.snapshot_id!==snapshot||selected.proof.new_errors.length>0} onClick={()=>{setPublishReason(note);setPublish(true)}}><Send size={15}/>发布此版本</button>}</div>{dirty&&<Notice message="请先保存草稿，再运行试算。"/>}{!dirty&&selected.proof&&selected.proof.snapshot_id===snapshot&&<TrialImpact key={selected.id+selected.proof.at} ruleId={selected.id} proof={selected.proof}/>}</section>}{!draft&&selected.proof&&<section className="panel trial-panel"><div className="panel-heading"><h2>发布前试算</h2></div><TrialImpact key={selected.id+selected.proof.at} ruleId={selected.id} proof={selected.proof}/></section>}</>:<section className="panel"><div className="panel-heading"><h2>标准与版本</h2><span>{list.length} 个版本</span></div><div className="table-scroll"><table><thead><tr><th>审核标准</th><th>适用范围</th><th>状态</th><th>发布时间</th><th/></tr></thead><tbody>{list.map(r=><tr key={r.id}><td><strong>{r.name}</strong><small>{r.note}</small></td><td>{scopeLabel(r,warehouses)}</td><td><Badge value={r.state==='DRAFT'?'DRAFT':r.active?'APPROVED':'VOID'} label={r.state==='DRAFT'?'草稿':r.active?'当前使用':'历史版本'}/></td><td>{date(r.published_at)}</td><td><button className="text-button" onClick={()=>choose(r)}>{r.state==='DRAFT'?'继续编辑':'查看标准'} →</button></td></tr>)}</tbody></table></div><details className="rule-details"><summary>各市场生效标准</summary><div className="table-scroll"><table><thead><tr><th>市场</th><th>仓库</th><th>生效标准</th></tr></thead><tbody>{warehouses.map(w=><tr key={w.code}><td>{w.market_name}</td><td>{w.name}</td><td>{list.find(r=>r.id===coverage[w.code])?.name||'尚未配置'}</td></tr>)}</tbody></table></div></details></section>}
 {publish&&<Modal title="发布审核标准" onClose={closePublish}><div className="modal-body"><p><strong>{selected.name}</strong> · {scopeLabel(selected,warehouses)}</p><p>试算 {selected.proof.rows} 行，{selected.proof.changed} 行变化。现有计划沿用原标准。</p>{error&&<Notice message={error} tone="error"/>}<label>发布说明<textarea rows={3} disabled={busy} value={publishReason} onChange={e=>setPublishReason(e.target.value)}/></label><div className="modal-actions"><button className="secondary" disabled={busy} onClick={closePublish}>返回</button><button className="primary" disabled={!publishReason.trim()||busy} onClick={async()=>{const ok=await action(()=>api(`/rules/${selected.id}/publish`,{revision:selected.revision,reason:publishReason}),'新审核标准已发布');if(ok)setPublish(false)}}>确认发布</button></div></div></Modal>}
 </>
}
