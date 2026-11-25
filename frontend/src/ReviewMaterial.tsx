import {systemText} from './i18n'
import {useRef} from 'react'
import {Minus,Plus} from 'lucide-react'

const specialGroups:Record<string,string> = {small:'小件',maintenance:'保养件',dangerous:'危包',manual:'用品精品',no_stock:'不备货'}

export function materialMarks(row:any) {
  const {override,matched_keywords}=row.result
  const groups = override ? [override] : Object.keys(matched_keywords || {}).filter(key=>matched_keywords[key]?.length)
  const special = groups.map(key=>specialGroups[key]).filter(Boolean).map(label=>systemText(label))
  const raw = String(row.input.large_value_flag ?? '').trim()
  const value = raw.replace(/^[、，,\s]+|[、，,\s]+$/g,'')
  const empty = /^(?:|0|否|无|普通|常规|无标记|正常|不适用|false|no|n|n\/a|[-—])$/i.test(value)
  const yes = /^(?:是|有|1|true|yes|y)$/i.test(value)
  const highlighted = yes || /(?:大金额|高单价|大体积|高金额|高价值)/.test(value) && !/^(?:非|不属于|不是|无)/.test(value)
  const size = empty ? '' : yes ? systemText("高单价大体积") : value
  return {special,size,highlighted}
}

export function PlanQuantity({value,step,disabled,edited,label,onChange}:{
  value:string|number;step:string|number;disabled:boolean;edited:boolean;label:string;onChange:(value:string)=>void
}) {
  const input=useRef<HTMLInputElement>(null)
  function adjust(up:boolean) {
    if(!input.current) return
    if(up) input.current.stepUp()
    else input.current.stepDown()
    onChange(input.current.value)
  }
  return <div className={'plan-quantity'+(edited?' edited':'')}>
    <button type="button" aria-label={systemText("减少 ")+label} title={systemText("减少一个订货步长")} disabled={disabled || Number(value)<=0} onClick={()=>adjust(false)}><Minus size={12}/></button>
    <input ref={input} className="quantity-input" aria-label={label} disabled={disabled}
      type="number" min="0" step={Number(step)>0?step:1} value={value} onChange={e=>onChange(e.target.value)}/>
    <button type="button" aria-label={systemText("增加 ")+label} title={systemText("增加一个订货步长")} disabled={disabled} onClick={()=>adjust(true)}><Plus size={12}/></button>
  </div>
}
