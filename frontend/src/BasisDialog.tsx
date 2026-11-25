import {systemText} from './i18n'
import {useEffect, useRef, useState} from 'react'
import {api} from './api'
import SnapshotPicker from './SnapshotPicker'
import {ChangeList, ChangedItem} from './VersionChanges'
import {Busy, Modal, Notice} from './ui'

type Basis = {id: string; name: string}
type DraftVersion = {
  id: string; revision: number; snapshot: Basis|null; rule: Basis
  latest_rule_id: string; latest_rule_name?: string
}
type Preview = {
  revision: number; snapshot: Basis|null; rule: Basis; items: ChangedItem[]
  affected_count: number; quantity_changed_count: number; data_changed_count: number
}

export default function BasisDialog({ver,warehouse,onClose,onDone}: {
  ver: DraftVersion; warehouse: string; onClose: ()=>void; onDone: ()=>void | Promise<void>
}) {
  const [snapshots,setSnapshots] = useState<any[]>([])
  const currentSnapshotId = ver.snapshot?.id || ''
  const [snapshotId,setSnapshotId] = useState(currentSnapshotId)
  const [loading,setLoading] = useState(true)
  const [ruleId,setRuleId] = useState(ver.rule.id)
  const [optionsError,setOptionsError] = useState('')
  const [optionsAttempt,setOptionsAttempt] = useState(0)
  const [preview,setPreview] = useState<Preview|null>(null)
  const [previewing,setPreviewing] = useState(false)
  const [attempt,setAttempt] = useState(0)
  const [error,setError] = useState('')
  const [saving,setSaving] = useState(false)
  const savingRef = useRef(false)
  const hasChange = (!!snapshotId || !currentSnapshotId) && (snapshotId !== currentSnapshotId || ruleId !== ver.rule.id)
  const path = '/versions/'+ver.id

  useEffect(()=>{
    let active = true
    setOptionsError('')
    setLoading(true)
    api('/snapshots?warehouse='+encodeURIComponent(warehouse))
      .then(data=>{
        if(!active)return
        setSnapshots(data)

      })
      .catch(e=>{if(active)setOptionsError(e.message)})
      .finally(()=>{if(active)setLoading(false)})
    return ()=>{active=false}
  },[warehouse,optionsAttempt,currentSnapshotId])

  useEffect(()=>{
    let active = true
    setPreview(null)
    setError('')
    setPreviewing(hasChange)
    async function loadPreview() {
      try {
        const revision = attempt ? (await api(path+'?page_size=1')).revision : ver.revision
        if(!active)return
        const data = await api<Preview>(path+'/snapshot-preview',{snapshot_id:snapshotId||null,rule_id:ruleId,revision})
        if(active)setPreview(data)
      } catch(e:any) {
        if(active)setError(e.message)
      } finally {
        if(active)setPreviewing(false)
      }
    }
    if(hasChange)void loadPreview()
    return ()=>{active=false}
  },[path,snapshotId,ruleId,hasChange,ver.revision,attempt])

  const ready = hasChange && preview && (preview.snapshot?.id||'')===snapshotId && preview.rule.id===ruleId && !previewing
  function close() { if(!savingRef.current)onClose() }
  async function save() {
    if(!ready || !preview || savingRef.current)return
    savingRef.current = true
    setSaving(true)
    setError('')
    try {
      await api(path+'/basis',{snapshot_id:preview.snapshot?.id||null,rule_id:preview.rule.id,revision:preview.revision})
    } catch(e:any) {
      setPreview(null)
      setError(e.message)
      savingRef.current=false
      setSaving(false)
      return
    }
    try { await onDone() } finally {
      savingRef.current=false
      setSaving(false)
    }
  }

  return <Modal title={systemText("更换计算依据")} onClose={close} wide>
    <div className="modal-body">
      {optionsError && <><Notice message={optionsError} tone="error"/><button className="text-button" type="button" onClick={()=>setOptionsAttempt(v=>v+1)}>{systemText("重新加载快照")}</button></>}
      {loading ? <Busy text={systemText("读取快照…")}/> :
        !optionsError && (snapshots.length>0
          ? <SnapshotPicker required={!!currentSnapshotId} emptyText={currentSnapshotId?systemText("选择本仓快照"):systemText("使用计划自带数据")} snapshots={snapshots} value={snapshotId} disabled={saving} onChange={setSnapshotId}/>
          : <Notice message={systemText("本计划使用自带的基础数据。")} tone="info"/>)}
      {<label>{systemText("审核标准")}<select value={ruleId} disabled={saving || ver.latest_rule_id===ver.rule.id} onChange={e=>setRuleId(e.target.value)}>
        <option value={ver.rule.id}>{ver.rule.name}</option>
        {ver.latest_rule_id!==ver.rule.id && <option value={ver.latest_rule_id}>{ver.latest_rule_name || systemText("仓库最新审核标准")}</option>}
      </select></label>}
      {previewing && <Busy text={systemText("正在预览影响…")}/>}
      {error && <><Notice message={error} tone="error"/><button className="text-button" type="button" onClick={()=>setAttempt(v=>v+1)}>{systemText("重新预览")}</button></>}
      {ready && preview && <section className="basis-impact" aria-label={systemText("更换影响")}>
        <div className="change-summary" role="status"><strong>{systemText("影响")} {preview.affected_count} {systemText("行")}</strong><span>{systemText("数量结论变化")} {preview.quantity_changed_count} {systemText("行")}</span><span>{systemText("数据状态变化")} {preview.data_changed_count} {systemText("行")}</span></div>
        {preview.items.length>0 && <details className="basis-impact-detail"><summary>{systemText("查看影响明细")}</summary><ChangeList key={snapshotId+ruleId} items={preview.items} columns={[systemText("当前"),systemText("更换后")]} filename={systemText("更换依据差异")}/></details>}
      </section>}
      <div className="modal-actions"><button type="button" className="secondary" disabled={saving} onClick={close}>{snapshots.length?systemText("取消"):systemText("关闭")}</button>{(snapshots.length>0||ver.latest_rule_id!==ver.rule.id)&&<button type="button" className="primary" disabled={!ready || saving || !!optionsError} onClick={save}>{saving?systemText("正在保存…"):systemText("确认更换")}</button>}</div>
    </div>
  </Modal>
}

