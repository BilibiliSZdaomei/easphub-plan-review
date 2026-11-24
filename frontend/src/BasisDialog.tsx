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
  revision: number; snapshot: Basis; rule: Basis; items: ChangedItem[]
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
  const hasChange = !!snapshotId && (snapshotId !== currentSnapshotId || ruleId !== ver.rule.id)
  const path = '/versions/'+ver.id

  useEffect(()=>{
    let active = true
    setOptionsError('')
    setLoading(true)
    api('/snapshots?warehouse='+encodeURIComponent(warehouse))
      .then(data=>{
        if(!active)return
        setSnapshots(data)
        if(!currentSnapshotId && data.length===1)setSnapshotId(data[0].id)
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
        const data = await api<Preview>(path+'/snapshot-preview',{snapshot_id:snapshotId,rule_id:ruleId,revision})
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

  const ready = hasChange && preview && preview.snapshot.id===snapshotId && preview.rule.id===ruleId && !previewing
  function close() { if(!savingRef.current)onClose() }
  async function save() {
    if(!ready || !preview || savingRef.current)return
    savingRef.current = true
    setSaving(true)
    setError('')
    try {
      await api(path+'/basis',{snapshot_id:preview.snapshot.id,rule_id:preview.rule.id,revision:preview.revision})
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

  return <Modal title={currentSnapshotId?"更换计算依据":"关联数据快照"} onClose={close} wide>
    <div className="modal-body">
      {optionsError && <><Notice message={optionsError} tone="error"/><button className="text-button" type="button" onClick={()=>setOptionsAttempt(v=>v+1)}>重新加载快照</button></>}
      {loading ? <Busy text="读取快照…"/> :
        !optionsError && (snapshots.length>0
          ? <SnapshotPicker snapshots={snapshots} value={snapshotId} disabled={saving} onChange={setSnapshotId}/>
          : <Notice message="本仓暂无已发布的快照。数据维护员发布后，即可在这里关联。" tone="info"/>)}
      {(snapshots.length>0 || !!currentSnapshotId) && <label>审核标准<select value={ruleId} disabled={saving || ver.latest_rule_id===ver.rule.id} onChange={e=>setRuleId(e.target.value)}>
        <option value={ver.rule.id}>{ver.rule.name}</option>
        {ver.latest_rule_id!==ver.rule.id && <option value={ver.latest_rule_id}>{ver.latest_rule_name || '仓库最新审核标准'}</option>}
      </select></label>}
      {previewing && <Busy text="正在预览影响…"/>}
      {error && <><Notice message={error} tone="error"/><button className="text-button" type="button" onClick={()=>setAttempt(v=>v+1)}>重新预览</button></>}
      {ready && preview && <section className="basis-impact" aria-label="更换影响">
        <div className="change-summary" role="status"><strong>影响 {preview.affected_count} 行</strong><span>数量结论变化 {preview.quantity_changed_count} 行</span><span>数据状态变化 {preview.data_changed_count} 行</span></div>
        {preview.items.length>0 && <details className="basis-impact-detail"><summary>查看影响明细</summary><ChangeList key={snapshotId+ruleId} items={preview.items} columns={['当前','更换后']} filename="更换依据差异"/></details>}
      </section>}
      <div className="modal-actions"><button type="button" className="secondary" disabled={saving} onClick={close}>{snapshots.length?'取消':'关闭'}</button>{snapshots.length>0&&<button type="button" className="primary" disabled={!ready || saving || !!optionsError} onClick={save}>{saving?'正在保存…':currentSnapshotId?'确认更换':'确认关联'}</button>}</div>
    </div>
  </Modal>
}

