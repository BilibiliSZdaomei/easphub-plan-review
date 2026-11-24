export function snapshotPublishedAt(value:string){
 if(!value)return '—'
 return new Date(value).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
}

export function sortSnapshots(snapshots:any[]){
 return [...snapshots].sort((a,b)=>String(b.as_of||'').localeCompare(String(a.as_of||''))||String(b.created_at||'').localeCompare(String(a.created_at||'')))
}

export function snapshotLabel(snapshot:any){
 return `${snapshot.name} · ${snapshot.as_of||'日期未填'} · ${snapshot.rows} 行`
}

export default function SnapshotPicker({snapshots,value,onChange,disabled=false,loading=false,required=true,label='数据快照',emptyText='请选择数据快照',noDataText='暂无可用快照'}:{snapshots:any[];value:string;onChange:(id:string)=>void;disabled?:boolean;loading?:boolean;required?:boolean;label?:string;emptyText?:string;noDataText?:string}){
 const selected=snapshots.find(s=>s.id===value)
 return <div className="snapshot-picker"><label>{label}<select aria-label={label} required={required} value={value} disabled={disabled||loading||!snapshots.length} onChange={e=>onChange(e.target.value)}><option value="">{loading?'正在读取…':snapshots.length?emptyText:noDataText}</option>{sortSnapshots(snapshots).map(s=><option key={s.id} value={s.id}>{snapshotLabel(s)}</option>)}</select></label>{selected&&<><div className="snapshot-meta"><span>数据日期 <b>{selected.as_of||'—'}</b></span><span>发布时间 {snapshotPublishedAt(selected.created_at)}</span></div><details className="snapshot-basis"><summary>净额口径 · {selected.net_mode==='COMPONENTS'?'分项计算':'已提供净额'}</summary><p>{selected.basis||'未填写口径'}</p></details></>}</div>
}
