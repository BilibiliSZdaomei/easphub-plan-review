import {ReactNode, useLayoutEffect, useMemo, useRef, useState} from 'react'

type Props = {rows:any[]; columns:number; children:(row:any)=>ReactNode}
const ESTIMATE = 48
const OVERSCAN = 12

function rowAt(offsets:number[], position:number){
  let lo=0, hi=offsets.length-1
  while(lo<hi){
    const mid=Math.ceil((lo+hi)/2)
    if(offsets[mid]<=position)lo=mid
    else hi=mid-1
  }
  return lo
}

// The same row renderer and checkboxes serve every page size. Row heights may
// vary with material labels, review reasons, column widths and compact mode.
export default function WindowedRows({rows,columns,children}:Props){
  const body=useRef<HTMLTableSectionElement>(null)
  const heights=useRef(new Map<string,number>())
  const [revision,measure]=useState(0)
  const [viewport,setViewport]=useState({top:0,height:720})
  const virtual=rows.length>100
  const offsets=useMemo(()=>{
    const result=[0]
    if(virtual)for(const row of rows)result.push(result[result.length-1]+(heights.current.get(row.id)??ESTIMATE))
    return result
  },[virtual,rows,revision])
  const first=virtual?Math.max(0,rowAt(offsets,viewport.top)-OVERSCAN):0
  const last=virtual?Math.min(rows.length,rowAt(offsets,viewport.top+viewport.height)+1+OVERSCAN):rows.length
  useLayoutEffect(()=>{
    const scroll=body.current?.closest<HTMLElement>('.plan-scroll')
    if(!virtual||!scroll)return
    const update=()=>{
      const top=Math.max(0,scroll.getBoundingClientRect().top-(body.current?.getBoundingClientRect().top??0))
      const height=scroll.clientHeight
      setViewport(v=>v.top===top&&v.height===height?v:{top,height})
    }
    const observer=new ResizeObserver(update)
    observer.observe(scroll)
    scroll.addEventListener('scroll',update,{passive:true})
    update()
    return ()=>{observer.disconnect();scroll.removeEventListener('scroll',update)}
  },[virtual])
  useLayoutEffect(()=>{
    if(!virtual||!body.current)return
    const elements=Array.from(body.current.rows).filter(el=>el.getAttribute('aria-hidden')!=='true')
    const observer=new ResizeObserver(()=>{
      let changed=false
      elements.forEach((el,i)=>{
        const height=el.getBoundingClientRect().height,id=rows[first+i]?.id
        if(id && height>0 && heights.current.get(id)!==height){
          heights.current.set(id,height)
          changed=true
        }
      })
      if(changed)measure(n=>n+1)
    })
    elements.forEach(el=>observer.observe(el))
    return ()=>observer.disconnect()
  },[virtual,rows,first,last])
  function spacer(height:number){
    return height>0?<tr aria-hidden="true" className="row-spacer"><td colSpan={columns} style={{height,padding:0,border:0,lineHeight:0}}/></tr>:null
  }
  return <tbody ref={body}>
    {virtual&&spacer(offsets[first])}
    {rows.slice(first,last).map(children)}
    {virtual&&spacer(offsets[rows.length]-offsets[last])}
  </tbody>
}
