import {tr, systemText} from './i18n'
import {useEffect, useReducer} from 'react'
import {Redo2, Undo2} from 'lucide-react'

type Edits = Record<string, Record<string, string>>
type CellChange = {id:string; key:string; before?:string; after?:string}
type Step = {label:string; changes:CellChange[]}
type Draft = {edits:Edits; past:Step[]; future:Step[]}
type Action = {type:'change'; id:string; key:string; value:string; original:string}
            | {type:'clear'|'undo'|'redo'|'undoAll'}
export type HistoryDirection = 'undo'|'redo'
type Hint = {label:string; count:number}

const emptyDraft:Draft = {edits:{}, past:[], future:[]}
const historyLimit = 200

function applyStep(edits:Edits, step:Step, field:'before'|'after'):Edits {
 const result={...edits}
 const touched=new Set<string>()
 for(const change of step.changes){
  const {id,key}=change
  if(!touched.has(id)){result[id]={...edits[id]};touched.add(id)}
  const value=change[field]
  if(value===undefined)delete result[id][key]
  else result[id][key]=value
 }
 for(const id of touched)if(!Object.keys(result[id]).length)delete result[id]
 return result
}

function undoAll(state:Draft):Draft {
 const changes=Object.entries(state.edits).flatMap(([id,row])=>
  Object.entries(row).map(([key,after])=>({id,key,after})))
 if(!changes.length)return state
 return {edits:{},past:[],future:[...state.future,{label:'本次数量修改',changes}]}
}

function reduceDraft(state:Draft, action:Action):Draft {
 switch(action.type){
  case 'clear':return emptyDraft
  case 'undoAll':return undoAll(state)
  case 'undo':{
   const step=state.past.at(-1)
   if(!step)return undoAll(state)
   return {edits:applyStep(state.edits,step,'before'),past:state.past.slice(0,-1),future:[...state.future,step]}
  }
  case 'redo':{
   const step=state.future.at(-1)
   if(!step)return state
   return {edits:applyStep(state.edits,step,'after'),past:[...state.past.slice(1-historyLimit),step],future:state.future.slice(0,-1)}
  }
  case 'change':{
   const {id,key,value,original}=action
   const before=state.edits[id]?.[key]
   if((before??original)===value)return state
   const step={label:'数量修改',changes:[{id,key,before,after:value===original?undefined:value}]}
   return {edits:applyStep(state.edits,step,'after'),past:[...state.past.slice(1-historyLimit),step],future:[]}
  }
 }
}

function hint(step?:Step):Hint|null {
 return step?{label:step.label,count:new Set(step.changes.map(change=>change.id)).size}:null
}

export function useQuantityDraft() {
 const [draft,dispatch]=useReducer(reduceDraft,emptyDraft)
 const dirtyCount=Object.keys(draft.edits).length
 return {
  edits:draft.edits,
  undoHint:hint(draft.past.at(-1))||(dirtyCount?{label:'本次数量修改',count:dirtyCount}:null),
  redoHint:hint(draft.future.at(-1)),
  change:(id:string,key:string,value:string,original:string)=>dispatch({type:'change',id,key,value,original}),
  clear:()=>dispatch({type:'clear'}),
  undoAll:()=>dispatch({type:'undoAll'}),
  replay:(direction:HistoryDirection)=>dispatch({type:direction}),
 }
}

type HistoryProps={
 undo:Hint|null; redo:Hint|null; disabled:boolean; onAction:(direction:HistoryDirection)=>void
}

export function PlanHistoryControls({undo,redo,disabled,onAction}:HistoryProps) {
 useEffect(()=>{
  function shortcut(event:KeyboardEvent){
   if(disabled||event.defaultPrevented||event.isComposing||event.repeat||event.altKey||
      (!event.ctrlKey&&!event.metaKey)||(event.ctrlKey&&event.metaKey))return
   const key=event.key.toLowerCase()
   let direction:HistoryDirection
   if(key==='z')direction=event.shiftKey?'redo':'undo'
   else if(key==='y'&&event.ctrlKey&&!event.shiftKey)direction='redo'
   else return
   if(!(direction==='undo'?undo:redo))return
   const target=event.target
   if(document.querySelector('[aria-modal="true"], dialog[open]')||(target instanceof HTMLElement&&
      (target.isContentEditable||target.closest('textarea,select,input:not([type=checkbox]):not([type=button]),[role="dialog"]'))))return
   event.preventDefault()
   onAction(direction)
  }
  window.addEventListener('keydown',shortcut)
  return ()=>window.removeEventListener('keydown',shortcut)
 },[undo,redo,disabled,onAction])
 return <>{(['undo','redo'] as const).map(direction=>{
  const undoing=direction==='undo', label=undoing?systemText("撤销"):systemText("重做"), result=undoing?undo:redo
  const keys=undoing?'Ctrl / ⌘ + Z':systemText("Ctrl + Y 或 Ctrl / ⌘ + Shift + Z")
  const tip=result?`${label}${tr('', ' ')}${systemText(result.label)}${result.count?' · '+result.count+tr(' 行',' rows'):''}${tr('（',' (')}${keys}${tr('）',')')}`:tr('暂无可'+label+'的操作', 'Nothing to '+label.toLowerCase())
  return <button key={direction} data-usage-target={direction} type="button" className="secondary compact" disabled={disabled||!result}
   title={tip} aria-description={tip} aria-keyshortcuts={undoing?'Control+Z Meta+Z':'Control+Y Control+Shift+Z Meta+Shift+Z'}
   onClick={()=>onAction(direction)}>{undoing?<Undo2 size={15}/>:<Redo2 size={15}/>}{label}</button>
 })}</>
}
