import {warehouseName} from './i18n'
import {createContext,useContext,type SelectHTMLAttributes} from 'react'
import './warehouse-label.css'

export type WarehouseInfo = {code:string; name:string; market?:string}
export const WarehouseCatalog = createContext<WarehouseInfo[]>([])
const flags = import.meta.glob<string>('./flags/*.svg',{eager:true,query:'?url',import:'default'})

/** Project grants onto the API's market order without changing the stored permissions. */
export function orderedWarehouseCodes(codes:readonly string[], catalog:readonly {code:string}[]) {
 const remaining=new Set(codes)
 const ordered=catalog.filter(w=>remaining.delete(w.code)).map(w=>w.code)
 return ordered.concat([...remaining].sort())
}

function flagUrl(market?:string){
 const iso=market?.toLowerCase()
 return flags['./flags/'+(iso==='uk'?'gb':iso)+'.svg']
}

export default function WarehouseLabel({code,name,market}:{code?:string;name?:string;market?:string}){
 const warehouse=useContext(WarehouseCatalog).find(w=>w.code===code)
 const label=warehouseName(name||warehouse?.name||code||'—')
 const flag=flagUrl(market||warehouse?.market)
 return <span className="warehouse-label">{flag&&<img className="warehouse-flag" src={flag} alt="" width="20" height="15"/>}{label}</span>
}

export function WarehouseSelect({value,market,className,style,...props}:SelectHTMLAttributes<HTMLSelectElement>&{market?:string}){
 const warehouse=useContext(WarehouseCatalog).find(w=>w.code===value)
 const flag=flagUrl(market||warehouse?.market)
 return <select {...props} value={value} className={[className,flag&&'warehouse-select-flagged'].filter(Boolean).join(' ')}
  style={flag?{...style,backgroundImage:'url("'+flag+'")',backgroundSize:'20px 15px',backgroundPosition:'10px center',backgroundRepeat:'no-repeat',paddingInlineStart:38}:style}/>
}
