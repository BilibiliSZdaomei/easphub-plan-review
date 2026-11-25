import {tr, systemText} from './i18n'
export function snapshotPublishedAt(value:string){
 if(!value)return '—'
 return new Date(value).toLocaleString(tr('zh-CN','en-GB'),{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
}

export function sortSnapshots(snapshots:any[]){
 return [...snapshots].sort((a,b)=>String(b.as_of||'').localeCompare(String(a.as_of||''))||String(b.created_at||'').localeCompare(String(a.created_at||'')))
}

export function snapshotLabel(snapshot:any){
 return tr(`${snapshot.name} · ${snapshot.as_of||'日期未填'} · ${snapshot.rows} 行`,`${snapshot.name} · ${snapshot.as_of||"Undated"} · ${snapshot.rows} rows`)
}

export default function SnapshotPicker({snapshots,value,onChange,disabled=false,loading=false,required=true,label=systemText("数据快照"),emptyText=systemText("请选择数据快照"),noDataText=systemText("暂无可用快照")}:{snapshots:any[];value:string;onChange:(id:string)=>void;disabled?:boolean;loading?:boolean;required?:boolean;label?:string;emptyText?:string;noDataText?:string}){
 const selected=snapshots.find(s=>s.id===value)
 return <div className="snapshot-picker"><label>{systemText(label)}<select aria-label={systemText(label)} required={required} value={value} disabled={disabled||loading||!snapshots.length} onChange={e=>onChange(e.target.value)}><option value="">{loading?systemText("正在读取…"):snapshots.length?systemText(emptyText):systemText(noDataText)}</option>{sortSnapshots(snapshots).map(s=><option key={s.id} value={s.id}>{snapshotLabel(s)}</option>)}</select></label>{selected&&<><div className="snapshot-meta"><span>{systemText("数据日期")} <b>{selected.as_of||'—'}</b></span><span>{systemText("发布时间")} {snapshotPublishedAt(selected.created_at)}</span></div><details className="snapshot-basis"><summary>{systemText("净额口径 ·")} {selected.net_mode==='COMPONENTS'?systemText("分项计算"):systemText("已提供净额")}</summary><p>{selected.basis||systemText("未填写口径")}</p></details></>}</div>
}
