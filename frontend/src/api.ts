export const APP_BASE=import.meta.env.BASE_URL.replace(/\/$/,'')
export const BASE=APP_BASE+'/api/v1'
let csrf=''
export function setCsrf(token:string){csrf=token}
export async function api<T=any>(path:string,body?:unknown,method?:string,operationKey?:string):Promise<T>{
  const verb=method || (body===undefined?'GET':'POST')
  const headers:Record<string,string>={'X-CSRF-Token':csrf}
  if(verb!=='GET')headers['Idempotency-Key']=operationKey??crypto.randomUUID()
  if(body!==undefined && !(body instanceof FormData))headers['Content-Type']='application/json'
  const response=await fetch(BASE+path,{method:verb,credentials:'same-origin',headers,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)})
  const data=await response.json().catch(()=>({}))
  if(!response.ok){
    const detail=data.detail
    let message=typeof detail==='string'?detail:detail?.message || '操作未完成，请稍后重试'
    if(Array.isArray(detail?.issues)&&typeof detail.issues[0]==='string')message+='：'+detail.issues.slice(0,3).join('；')
    const error=new Error(message) as Error & {detail:any;status:number};error.detail=detail;error.status=response.status;throw error
  }
  return data as T
}
export async function waitJob(id:string,onState?:(state:any)=>void){
  for(let i=0;i<300;i++){
    const j=await api('/jobs/'+id);onState?.(j)
    if(j.state==='FAILED')throw new Error(j.error || '文件处理失败')
    if(j.state==='DONE')return j
    await new Promise(r=>setTimeout(r,600))
  }
  throw new Error('任务仍在处理中，请稍后重新查看')
}
export const completedStates = ['APPROVED','PARTIALLY_APPROVED','REJECTED']
export const labels:Record<string,string>={DRAFT:'草稿',SUBMITTED:'待复审',IN_REVIEW:'复审中',RETURNED:'已退回',APPROVED:'已通过',PARTIALLY_APPROVED:'部分通过',REJECTED:'不批准',VOID:'已作废',WITHIN:'合理',BELOW:'偏少',ABOVE:'偏多',ERROR:'数据错误',WARNING:'需关注',VALID:'有效',PENDING:'待补数据',MANUAL:'人工判断',EXEMPT:'免数量审核',UNAVAILABLE:'无法计算',NOT_APPLICABLE:'不适用',BATCH_APPROVED:'整批通过',EXCEPTION_APPROVED:'例外批准'}
export const flagLabels:Record<string,string>={AIR:'需确认空运',COLLISION:'分类重叠',MISSING_RATE:'缺更换率',NO_SEA_RANGE:'仅减海运无法达标',ABC_MISSING:'分类缺失',MANUAL:'市场需求判断'}
export const reasonLabels=new Map([
  ['市场需求变化','预计用量有变化'],
  ['已确认特殊订单','已有订单要交付'],
  ['补货节奏','配合船期或到货时间'],
  ['特殊物料','备件有特殊备货要求'],
  ['数据口径说明','库存或销量需要说明'],
  ['其他','其他原因'],
])
export function reasonLabel(code:string){return reasonLabels.get(code) ?? code}
export function fmt(v:unknown){if(v===null||v===undefined||v==='')return '—';const n=Number(v);return Number.isFinite(n)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(n):String(v)}
export function date(v:string){return v?new Date(v).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—'}

export function localDay(v:string){const d=new Date(v);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
