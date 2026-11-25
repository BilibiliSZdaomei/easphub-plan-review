export type UsageFailure = 'error'|'validation'
export type FailureTarget = 'import'|'export'|'submit'|'save'|'return'|'transfer'|'undo'|'redo'|'create'|'approve'
type Recorder = (target:FailureTarget)=>(kind:UsageFailure)=>void
let active:Recorder|undefined

export function listenForFailures(recorder:Recorder) {
  active=recorder
  return ()=>{if(active===recorder)active=undefined}
}

export function requestFailure(path:string,method:string) {
  if(method==='GET'||!active)return
  const route=path.split('?')[0]
  let target:FailureTarget
  if(/^\/imports(?:\/|$)/.test(route))target='import'
  else if(route==='/exports')target='export'
  else if(route==='/batches')target='create'
  else if(/^\/versions\/[^/]+\//.test(route)){
    const key=route.split('/')[3]
    if(key==='reviews')target='save'
    else if(key==='finalize')target='submit'
    else if(key==='transfer'||key==='return'||key==='undo'||key==='redo'||key==='submit')target=key
    else target='save'
  }else if(/^\/(rules|snapshots|mappings)(?:\/|$)/.test(route))target='save'
  else return
  return active(target)
}

export function jobFailure(target:FailureTarget) {
  return active?.(target)
}
