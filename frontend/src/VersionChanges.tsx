import {useMemo, useState} from 'react'
import {ChevronLeft, ChevronRight, Download, Search} from 'lucide-react'
import {flagLabels, labels, reasonLabel} from './api'

type ValueChange = {before: unknown; after: unknown}
type Fields = Record<string, ValueChange>
export type ChangedItem = {
  material_code: string
  material_name?: string
  change: string
  fields: Fields
  result_fields?: Fields
  decision_fields?: Fields
  override_fields?: Fields
}
type Diff = {
  items: ChangedItem[]
  summary: {total: number; added: number; removed: number; modified: number}
  rule_changed: boolean
  snapshot_changed: boolean
  from_version?: {id: string; seq: number}
  to_version?: {id: string; seq: number}
}

const fieldLabels: Record<string,string> = {
  material_name:'物料名称', material_type:'物料类型', material_abc:'物料 ABC', local_abc:'本地 ABC',
  vehicle_model:'车型', vehicle_parc:'备件保有量', source_note:'备注', monthly_sales:'逐月销量',
  on_hand_months:'在库周转（月）', pipeline_days:'净库存周转（天）', future_days:'补货后周转（天）', delay_replenishment:'建议延迟补货', advice:'审批建议',
  is_key_model:'重点车型', fleet_qty:'装车量', avg_sales_3m:'近 3 月月均销量', avg_sales_6m:'近 6 月月均销量',
  replacement_rate:'稳态更换率', replacement_target:'更换率目标库存', sales_target:'销量目标库存',
  net_supply_before_plan:'审核前净额', sea_plan_qty:'海运计划', air_plan_qty:'空运计划', on_hand_qty:'在库数量',
  in_transit_qty:'在途数量', on_order_qty:'在订数量', demand_deduction_qty:'需求抵扣', uom:'计量单位',
  quantity_step:'订货步长', reason_code:'原因类别', reason:'计划说明', air_reason:'空运说明', source_line_id:'源明细行',
  source_formulas:'快照源公式', plan_source_formulas:'计划源公式', formula:'公式', cached:'原表计算值',
  quantity_status:'数量结论', data_status:'数据状态', review_mode:'审核方式', rule_id:'命中规则',
  lower_raw:'取整前下限', upper_raw:'取整前上限', lower:'库存下限', upper:'库存上限', future_qty:'未来库存',
  quantity_gap:'偏离数量', sea_feasible:'海运可调至区间内', sea_lower:'海运下限', sea_upper:'海运上限',
  suggested_sea_qty:'建议海运量', residual_excess:'剩余超量', manual_flags:'人工关注', errors:'数据错误',
  warnings:'提醒', matched_keywords:'命中关键词', override:'物料分类覆盖', explanation:'计算依据',
  m:'月均销量参考值', precision_version:'精度版本', status:'复审结论', reviewer_id:'复审人编号',
  reviewer_name:'复审人', reviewed_at:'复审时间', ack_flags:'已确认关注项', air_confirmed:'已确认空运',
  forced:'例外终审', data_error_accepted:'已接受数据错误', issues:'待处理问题', user_id:'操作人编号',
  user_name:'操作人', at:'确认时间', affected_count:'涉及物料数', stage:'环节',
}
const groups = [
  ['fields', '计划'], ['result_fields','计算'], ['decision_fields','复审'], ['override_fields','提交提醒'],
] as const
const enumLabels: Record<string,string> = {
  ...labels, ...flagLabels, AUTO:'自动计算', MANUAL:'人工判断', maintenance:'保养件', dangerous:'危包',
  no_stock:'不备货', manual:'人工判断', small:'小件', submit:'提交', finalize:'终审',
}
const translated = new Set(['quantity_status','data_status','review_mode','status','stage','override','manual_flags','ack_flags'])

function describe(value: unknown, field: string): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.length ? value.map(v => describe(v,field)).join('、') : '无'
  if (typeof value === 'object') {
    const record = value as Record<string,unknown>
    if (typeof record.message === 'string') return record.message
    return Object.entries(record).filter(([,v]) => !(Array.isArray(v) && !v.length))
      .map(([k,v]) => (enumLabels[k] || fieldLabels[k] || k)+'：'+describe(v,k)).join('；') || '无'
  }
  const text = String(value)
  if (field === 'reason_code') return reasonLabel(text)
  if (field === 'manual_flags' || field === 'ack_flags') return flagLabels[text] || text
  return translated.has(field) ? enumLabels[text] || text : text
}

function differences(row: ChangedItem) {
  return groups.flatMap(([key,group]) => Object.entries(row[key] || {}).map(([field,values]) => ({
    group, field, label: field === 'reason' && key !== 'fields' ? '依据说明' : fieldLabels[field] || field,
    before: describe(values.before,field), after: describe(values.after,field),
  })))
}

function exportChanges(rows: ChangedItem[], filename: string, columns: [string,string]) {
  const data = [['物料号','物料名称','变更','类别','字段',...columns]]
  rows.forEach(row => {
    const changed = differences(row)
    if (!changed.length) data.push([row.material_code,row.material_name || '',row.change,'','','',''])
    changed.forEach(c => data.push([row.material_code,row.material_name || '',row.change,c.group,c.label,c.before,c.after]))
  })
  const escapeCell = (value: string) => {
    const safe = /^\s*[=+@-]/.test(value) && !/^-?\d+(\.\d+)?$/.test(value) ? "'"+value : value
    return '"'+safe.replaceAll('"','""')+'"'
  }
  const csv = data.map(line => line.map(escapeCell).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob(['\uFEFF',csv],{type:'text/csv;charset=utf-8'}))
  const link = document.createElement('a')
  link.href = url
  link.download = filename+'.csv'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url),1000)
}

const pageSize = 20
export function ChangeList({items, columns, filename}: {items: ChangedItem[]; columns: [string,string]; filename: string}) {
  const [search,setSearch] = useState('')
  const [kind,setKind] = useState('')
  const [page,setPage] = useState(1)
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return items.filter(row => (!kind || row.change === kind) &&
      (row.material_code+' '+(row.material_name || '')).toLowerCase().includes(query))
  },[items,search,kind])
  const pages = Math.max(1,Math.ceil(filtered.length/pageSize))
  const position = Math.min(page,pages)
  const start = (position-1)*pageSize

  return <div className="change-list">
    <div className="list-toolbar diff-toolbar">
      <div className="search"><Search size={16}/><input type="search" aria-label="搜索变更物料" placeholder="搜索物料号或名称" value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}}/></div>
      {new Set(items.map(row => row.change)).size>1 && <select aria-label="变更类型" value={kind} onChange={e=>{setKind(e.target.value);setPage(1)}}><option value="">全部变更</option>{['新增','修改','删除'].map(t=><option key={t}>{t}</option>)}</select>}
      <button type="button" className="text-button" disabled={!filtered.length} onClick={()=>exportChanges(filtered,filename,columns)}><Download size={14}/>导出差异</button>
    </div>
    <div className="change-rows">{filtered.slice(start,start+pageSize).map(row => {
      const changes = differences(row)
      return <details className="change-row" key={row.material_code}>
        <summary><strong>{row.material_code}</strong> <span>{row.material_name}</span> <small>{row.change} · {changes.length} 项</small></summary>
        {changes.length>0 && <div className="table-scroll"><table className="simple-table change-fields"><thead><tr><th>字段</th><th>{columns[0]}</th><th>{columns[1]}</th></tr></thead>
          <tbody>{changes.map(({group,field,label,before,after})=><tr key={group+field}><th scope="row"><small>{group}</small> {label}</th><td>{before}</td><td>{after}</td></tr>)}</tbody>
        </table></div>}
      </details>
    })}</div>
    {!filtered.length && <p className="empty-inline">无匹配物料</p>}
    <div className="table-footer"><span>{filtered.length ? (start+1)+'–'+Math.min(start+pageSize,filtered.length)+' / '+filtered.length : '0'} 行</span>
      {pages>1 && <div className="pagination"><button type="button" className="icon-button" aria-label="上一页差异" disabled={position===1} onClick={()=>setPage(position-1)}><ChevronLeft size={16}/></button><span>{position} / {pages}</span><button type="button" className="icon-button" aria-label="下一页差异" disabled={position===pages} onClick={()=>setPage(position+1)}><ChevronRight size={16}/></button></div>}
    </div>
  </div>
}

export default function VersionChanges({diff}: {diff: Diff}) {
  const columns: [string,string] = [diff.from_version ? 'V'+diff.from_version.seq : '对比版本',diff.to_version ? 'V'+diff.to_version.seq : '当前版本']
  const summary = diff.summary
  return <div className="version-changes">
    <div className="change-summary"><strong>{columns[0]} → {columns[1]}</strong><span>新增 {summary.added} · 修改 {summary.modified} · 删除 {summary.removed}</span>
      {diff.rule_changed && <span>审核标准已更换</span>}{diff.snapshot_changed && <span>数据快照已更换</span>}
    </div>
    {diff.items.length>0 && <ChangeList key={columns.join('-')} items={diff.items} columns={columns} filename={'计划版本差异-'+columns.join('-')}/>}
  </div>
}

