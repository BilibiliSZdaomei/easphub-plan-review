import {getLanguage, systemText} from './i18n'
import {tableDisplay} from './planMessages'
import {useEffect, useLayoutEffect, useRef, useState} from 'react'
import {createPortal} from 'react-dom'
import {X} from 'lucide-react'
import './column-filter.css'

type Column = {key:string; label:string; type:string}
type Props = {
  column:Column; anchor:HTMLButtonElement; options:string[]; rule:Record<string,any>
  onClose:()=>void; onApply:(rule:Record<string,unknown>|null)=>void
}
const numericOps = [['range','介于（含边界）'],['eq','等于'],['ne','不等于'],['gt','大于'],['ge','大于或等于'],['lt','小于'],['le','小于或等于']]
const textOps = [['contains','包含'],['not_contains','不包含'],['eq','等于'],['ne','不等于'],['starts','开头是'],['ends','结尾是']]
const blankOps = [['only','为空'],['exclude','不为空']]

export default function ColumnFilterMenu({column, anchor, options, rule, onClose, onApply}:Props){
  const menu = useRef<HTMLFormElement>(null)
  const isNumeric = column.type === 'number'
  const isEnum = column.type === 'enum'
  const percent = column.key === 'replacement_rate'
  function display(value:unknown){
    if (value == null || value === '') return ''
    if (!percent) return String(value)
    return String(value).endsWith('%') ? String(value).slice(0,-1) : String(Number((Number(value)*100).toPrecision(12)))
  }
  const [op,setOp] = useState(rule.blank || rule.op || (isNumeric?'range':'contains'))
  const [term,setTerm] = useState(display(rule.term ?? rule.contains))
  const [termLanguage,setTermLanguage] = useState(rule.lang === 'en' ? 'en' : 'zh-CN')
  const [min,setMin] = useState(display(rule.min))
  const [max,setMax] = useState(display(rule.max))
  const [choice,setChoice] = useState<string[]|null>(rule.values ?? null)
  const [search,setSearch] = useState('')
  const [error,setError] = useState('')
  const values = [...new Set([...options,...(rule.values || [])])] as string[]
  const optionLabel=(v:string)=>v?tableDisplay(column.key,v):systemText('（空白）')
  const found = values.filter(v=>optionLabel(v).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  const checked = choice ?? values
  function toggle(changes:string[],on:boolean){
    const next = on ? [...new Set([...checked,...changes])] : checked.filter(v=>!changes.includes(v))
    setChoice(next.length===values.length?null:next)
  }
  useLayoutEffect(()=>{
    const el=menu.current
    if(!el)return
    function position(){
      if(!el)return
      const rect=anchor.getBoundingClientRect(),margin=8
      const left=Math.min(window.innerWidth-el.offsetWidth-margin,Math.max(rect.right-el.offsetWidth,margin))
      const top=rect.bottom+el.offsetHeight+margin<=window.innerHeight ? rect.bottom+4
        : Math.max(margin,Math.min(rect.top-el.offsetHeight-4,window.innerHeight-el.offsetHeight-margin))
      el.style.left=Math.max(margin,left)+'px'
      el.style.top=top+'px'
    }
    position()
    const resize=new ResizeObserver(position)
    resize.observe(el)
    window.addEventListener('resize',position)
    window.addEventListener('scroll',position,true)
    return ()=>{resize.disconnect();window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true)}
  },[anchor])
  useEffect(()=>{
    menu.current?.querySelector<HTMLElement>('input:not([type=checkbox]),select')?.focus({preventScroll:true})
  },[])
  useEffect(()=>{
    function dismiss(e:Event){
      if(e.target instanceof Node && !menu.current?.contains(e.target) && !anchor.contains(e.target))onClose()
    }
    document.addEventListener('pointerdown',dismiss)
    document.addEventListener('focusin',dismiss)
    return ()=>{document.removeEventListener('pointerdown',dismiss);document.removeEventListener('focusin',dismiss)}
  },[anchor,onClose])
  function close(){anchor.focus({preventScroll:true});onClose()}
  function apply(){
    const numberValue=(s:string)=>percent?s+'%':s
    let next:Record<string,unknown>|null=null
    if(isEnum){
      if(choice!==null)next={values:choice}
    }else if(op==='only'||op==='exclude'){
      next={blank:op}
    }else if(op==='range'){
      if(min!==''&&max!==''&&Number(min)>Number(max)){setError(systemText("下限不能大于上限"));return}
      if(min!==''||max!=='')next={...(min!==''?{min:numberValue(min)}:{}),...(max!==''?{max:numberValue(max)}:{})}
    }else if(term!==''){
      const english = termLanguage === 'en' && ['advice','attention'].includes(column.key)
      next={op,term:isNumeric?numberValue(term):term,...(english?{lang:'en'}:{})}
    }
    anchor.focus({preventScroll:true})
    onApply(next)
  }
  const unit=percent?(getLanguage()==='en'?' (%)':'（%）'):''
  return createPortal(<form className="column-filter-menu" ref={menu} role="dialog" aria-label={systemText("筛选 ")+systemText(column.label)}
    onSubmit={e=>{e.preventDefault();apply()}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();close()}}}>
    <div className="column-filter-heading"><strong>{systemText(column.label)}</strong><button type="button" className="icon-button" aria-label={systemText("关闭筛选")} onClick={close}><X size={15}/></button></div>
    {isEnum ? <>
      <input aria-label={systemText("查找筛选选项")} placeholder={systemText("查找选项")} value={search} onChange={e=>setSearch(e.target.value)}/>
      <label className="filter-check select-values"><input type="checkbox" disabled={!found.length} checked={found.length>0&&found.every(v=>checked.includes(v))}
        ref={el=>{if(el)el.indeterminate=found.some(v=>checked.includes(v))&&!found.every(v=>checked.includes(v))}}
        onChange={e=>toggle(found,e.target.checked)}/>{search?systemText("选择搜索结果"):systemText("全选")}</label>
      <div className="filter-choices">{found.map(v=><label key={v} className="filter-check"><input type="checkbox" checked={checked.includes(v)} onChange={e=>toggle([v],e.target.checked)}/>{optionLabel(v)}</label>)}
        {found.length===0&&<span className="muted">{systemText("没有匹配的选项")}</span>}</div>
    </> : <>
      <select aria-label={systemText("筛选条件")} value={op} onChange={e=>{setOp(e.target.value);setError('')}}>
        {[...(isNumeric?numericOps:textOps),...blankOps].map(([key,label])=><option key={key} value={key}>{systemText(label)}</option>)}
      </select>
      {op==='range'?<div className="filter-range"><label>{systemText("下限")}{unit}<input type="number" step="any" value={min} onChange={e=>{setMin(e.target.value);setError('')}}/></label>
        <label>{systemText("上限")}{unit}<input type="number" step="any" value={max} onChange={e=>{setMax(e.target.value);setError('')}}/></label></div>
      :(!['only','exclude'].includes(op)&&<input aria-label={isNumeric?systemText("比较值")+unit:systemText("筛选文字")} placeholder={isNumeric?systemText("数值")+unit:systemText("输入文字")} type={isNumeric?'number':'text'} step={isNumeric?'any':undefined}
        value={term} maxLength={200} onChange={e=>setTerm(e.target.value)}/>)}
    </>}
    {error&&<small role="alert" className="text-coral">{error}</small>}
    <div className="column-filter-actions"><button type="button" className="text-button" onClick={()=>{anchor.focus({preventScroll:true});onApply(null)}}>{systemText("清除此列筛选")}</button>
      <button type="submit" className="primary compact">{systemText("应用筛选")}</button></div>
  </form>,document.body)
}
