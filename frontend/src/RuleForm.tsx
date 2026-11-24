import {useEffect, useRef, useState, type FormEvent} from 'react'
import {ArrowLeft, Save} from 'lucide-react'
import {api} from './api'
import {Notice, useFormExit} from './ui'

type RulePackage = {
  model?: string
  params: Record<string, string | number>
  keywords: Record<string, string[]>
  overrides: Record<string, string>
  precision_version: string
}
type Rule = {id: string; name: string; scope: string; scope_code: string; state: string; active: boolean; revision: number; package: RulePackage}
type Warehouse = {code: string; name: string; market: string; market_name?: string; region?: string}
type Labels = Record<string,string>
const keywordGroups: Labels = {small:'小件',maintenance:'保养件',dangerous:'危包',manual:'用品精品',no_stock:'不备货'}

export function scopeLabel(rule:Rule, warehouses:Warehouse[]) {
  if(rule.scope==='WAREHOUSE') return warehouses.find(w=>w.code===rule.scope_code)?.name || rule.scope_code
  if(rule.scope==='MARKET') return (warehouses.find(w=>w.market===rule.scope_code)?.market_name || rule.scope_code)+'市场'
  return rule.scope_code==='EUROPE'?'欧洲通用':'原默认范围'
}

export function initialSource(rules:Rule[], coverage:Record<string,string|null>, warehouse:string) {
  const active=rules.filter(r=>r.active && r.state==='PUBLISHED')
  const effective=warehouse ? coverage[warehouse] : new Set(Object.values(coverage)).size===1 ? Object.values(coverage)[0] : null
  return active.find(r=>r.id===effective) || active.find(r=>r.scope==='DEFAULT' && r.scope_code==='EUROPE') || active[0]
}

export function overrideText(pkg:RulePackage) {
  return Object.entries(pkg.overrides || {}).map(([code,type])=>code+'='+type).join('\n')
}

export function collectPackage(pkg:RulePackage, text:string):RulePackage {
  if(text===overrideText(pkg)) return pkg
  const entries=text.split('\n').map(line=>line.trim()).filter(Boolean).map(line=>{
    const split=line.lastIndexOf('=')
    const code=line.slice(0,split).trim(), type=line.slice(split+1).trim()
    if(split<1 || !code || !type) throw new Error('每行请填写「物料号=类型」')
    return [code,type]
  })
  if(new Set(entries.map(([code])=>code)).size!==entries.length) throw new Error('同一物料号只能指定一种审核类型')
  return {...pkg, overrides:Object.fromEntries(entries)}
}

export function RuleFields({pkg, labels, overrides, disabled, onPackage, onOverrides}:{
  pkg:RulePackage; labels:Labels; overrides:string; disabled:boolean; onPackage:(value:RulePackage)=>void; onOverrides:(value:string)=>void
}) {
  return <>
    <div className="parameter-grid">{Object.entries(labels).filter(([key])=>key in pkg.params).map(([key,label])=>
      <label key={key}><span>{label}</span><input disabled={disabled} type="number" step="any" min="0" required
        value={pkg.params[key]} onChange={e=>onPackage({...pkg,params:{...pkg.params,[key]:e.target.value}})} /></label>
    )}</div>
    <details className="rule-details"><summary>特殊物料关键词</summary><p>按物料名称匹配，多个分类命中时标记为需关注。</p>
      {Object.entries(pkg.keywords).map(([group,words])=><label key={group}>{keywordGroups[group]}
        <textarea aria-label={keywordGroups[group]} disabled={disabled} value={words.join('、')} rows={2}
          onChange={e=>onPackage({...pkg,keywords:{...pkg.keywords,[group]:e.target.value.split(/[、,，\n]/)}})}/></label>)}
    </details>
    <details className="rule-details"><summary>按物料号指定审核类型</summary><p>每行填写「物料号=类型」，支持 small、maintenance、dangerous、manual、no_stock、normal。</p>
      <textarea aria-label="按物料号指定审核类型" className="full" disabled={disabled} rows={4} value={overrides} onChange={e=>onOverrides(e.target.value)}/>
    </details>
  </>
}

function initialValues(source:Rule) {
  const legacyDefault = source.scope==='DEFAULT' && source.scope_code!=='EUROPE'
  return {
    source,
    name:source.name.slice(0,92)+' · 自定义',
    scope:legacyDefault?'':source.scope,
    code:legacyDefault?'':source.scope_code,
    pkg:structuredClone(source.package),
    overrides:overrideText(source.package),
    note:'',
  }
}

export default function CreateRule({initial, sources, warehouses, labels, v2Defaults, onClose, onCreated, onDirty}:{
  initial:Rule; sources:Rule[]; warehouses:Warehouse[]; labels:Labels; v2Defaults:RulePackage['params']
  onClose:()=>void; onCreated:(rule:Rule)=>void; onDirty:(dirty:boolean)=>void
}) {
  const [form,setForm]=useState(()=>initialValues(initial))
  const [dirty,setDirty]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState('')
  const saving=useRef(false), attempt=useRef<{body:string; key:string}|null>(null)
  const markets=new Map(warehouses.map(w=>[w.market,w.market_name || w.market]))
  const {source,pkg}=form
  useEffect(()=>{onDirty(dirty || busy);return ()=>onDirty(false)},[dirty,busy,onDirty])
  const close=useFormExit(dirty,busy,onClose)

  function edit(values:Partial<typeof form>) {
    setForm(current=>({...current,...values}))
    setDirty(true)
    setError('')
  }
  function changeSource(id:string) {
    if(dirty && !window.confirm('更换基础标准会重置本页修改，继续？')) return
    const next=sources.find(r=>r.id===id)
    if(next){setForm(initialValues(next));setDirty(false);setError('')}
  }
  function changeScope(scope:string) {
    let code=''
    if(scope===source.scope && !(scope==='DEFAULT' && source.scope_code!=='EUROPE')) code=source.scope_code
    else if(scope==='DEFAULT') code='EUROPE'
    else if(scope==='MARKET' && markets.size===1) code=warehouses[0].market
    else if(scope==='WAREHOUSE' && warehouses.length===1) code=warehouses[0].code
    edit({scope,code})
  }
  function changeModel(model:string) {
    if(model==='V2'){edit({pkg:{...pkg,model,params:{...v2Defaults,...pkg.params}}});return}
    const params={...pkg.params}
    for(const key of Object.keys(v2Defaults)) delete params[key]
    edit({pkg:{...pkg,model,params}})
  }
  async function submit(e:FormEvent) {
    e.preventDefault()
    if(saving.current) return
    saving.current=true
    setError('')
    setBusy(true)
    try {
      const payload={source_id:source.id,source_revision:source.revision,name:form.name.trim(),scope:form.scope,
        scope_code:form.code,model:pkg.model || '0804',package:collectPackage(pkg,form.overrides),note:form.note.trim()}
      const body=JSON.stringify(payload)
      if(attempt.current?.body!==body) attempt.current={body,key:crypto.randomUUID()}
      const created=await api<Rule>('/rules',payload,'POST',attempt.current.key)
      onCreated(created)
    } catch(e:any) {setError(e.message)}
    finally {saving.current=false;setBusy(false)}
  }
  return <>
    <button className="back-link" disabled={busy} onClick={close}><ArrowLeft size={15}/>返回审核标准</button>
    <div className="page-heading"><h1>新建标准</h1></div>
    <form className="panel new-standard" onSubmit={submit}>
      <div className="panel-heading"><h2>基本信息</h2></div>
      <div className="parameter-grid new-standard-meta">
        <label>基础标准<select disabled={busy} value={source.id} onChange={e=>changeSource(e.target.value)}>
          {sources.map(r=><option key={r.id} value={r.id}>{r.name} · {scopeLabel(r,warehouses)}{r.active?'':' · 历史版本'}</option>)}
        </select></label>
        <label>标准名称<input required maxLength={100} disabled={busy} value={form.name} onChange={e=>edit({name:e.target.value})}/></label>
        <label>适用层级<select required disabled={busy} value={form.scope} onChange={e=>changeScope(e.target.value)}>
          {!form.scope&&<option value="" disabled>请选择新标准的适用层级</option>}
          {warehouses.some(w=>w.region==='EUROPE')&&<option value="DEFAULT">欧洲通用</option>}
          <option value="MARKET">指定市场</option><option value="WAREHOUSE">指定仓库</option>
        </select></label>
        {form.scope && form.scope!=='DEFAULT'&&<label>适用范围<select required disabled={busy} value={form.code} onChange={e=>edit({code:e.target.value})}>
          <option value="" disabled>{form.scope==='MARKET'?'选择市场':'选择仓库'}</option>
          {form.scope==='MARKET'?Array.from(markets,([code,label])=><option key={code} value={code}>{label}</option>):
            warehouses.map(w=><option key={w.code} value={w.code}>{w.name}</option>)}
        </select></label>}
        {source.package.model!=='V2'&&<label>审核模型<select disabled={busy} value={pkg.model || '0804'} onChange={e=>changeModel(e.target.value)}>
          <option value="0804">0804</option><option value="V2">V2</option>
        </select></label>}
      </div>
      <div className="panel-heading"><h2>审核参数</h2></div>
      <RuleFields pkg={pkg} labels={labels} disabled={busy} overrides={form.overrides}
        onPackage={pkg=>edit({pkg})} onOverrides={overrides=>edit({overrides})}/>
      {error&&<Notice tone="error" message={error}/>}
      <div className="rule-edit-footer">
        <label>修改说明（选填）<input disabled={busy} maxLength={2000} value={form.note} onChange={e=>edit({note:e.target.value})}/></label>
        <div className="actions"><button type="button" className="secondary" disabled={busy} onClick={close}>取消</button>
          <button className="primary" disabled={busy || !form.name.trim() || !form.code}><Save size={15}/>{busy?'正在创建…':'创建草稿'}</button></div>
      </div>
    </form>
  </>
}
