import {adminMessage} from './adminMessages'
import {englishServerMessage} from './serverMessages'
import {useSyncExternalStore} from 'react'

export type Language = 'zh-CN' | 'en'
const preferenceKey = 'plan-review.language'
const subscribers = new Set<() => void>()
const files = import.meta.glob<Record<string,string>>('./i18n/*.json', {eager:true, import:'default'})
const english:Record<string,string> = Object.assign(Object.create(null), ...Object.values(files))
function savedLanguage(): Language {
  try { return localStorage.getItem(preferenceKey) === 'en' ? 'en' : 'zh-CN' }
  catch { return 'zh-CN' }
}
let language = savedLanguage()
function applyLanguage(next:Language) {
  language = next
  document.documentElement.lang = next
  document.title = tr('计划审核 · EASP Hub', 'Plan Review · EASP Hub')
  for (const listener of subscribers) listener()
}
applyLanguage(language)
window.addEventListener('storage', event => {
  if (event.key === preferenceKey || event.key === null) applyLanguage(savedLanguage())
})
export function setLanguage(next:Language) {
  try { localStorage.setItem(preferenceKey,next) } catch { /* This tab still switches. */ }
  applyLanguage(next)
}
const subscribe = (listener:() => void) => { subscribers.add(listener); return () => {subscribers.delete(listener)} }
export const getLanguage = () => language
export function useLanguage() { return useSyncExternalStore(subscribe,getLanguage) }
export function tr(zh:string,en:string) { return language === 'en' ? en : zh }

// Translate application-owned terms only. User names, notes and source data are displayed verbatim.
export function systemText(value:string):string {
  if (language !== 'en' || !value) return value
  return english[value] ?? value
}
export function systemMessage(value:string):string {
  if(language!=='en'||!value)return value
  const translated = english[value] ?? adminMessage(value,systemMessage) ?? englishServerMessage(value,systemMessage)
  if(translated!==undefined)return translated
  const separator=value.indexOf('：')
  if(separator>0 && english[value.slice(0,separator)]){
    return english[value.slice(0,separator)]+': '+value.slice(separator+1).split('；').map(systemMessage).join('; ')
  }
  return value
}
export function localizedLabels(entries:Record<string,string>):Record<string,string> {
  return Object.defineProperties({},Object.fromEntries(Object.entries(entries).map(([code,label]) =>
    [code,{enumerable:true,get:() => systemText(label)}])))
}
const warehouseNames:Record<string,string> = {
  '英国':'United Kingdom','西班牙':'Spain','德国':'Germany','荷兰':'Netherlands','意大利':'Italy',
  '法国':'France','波兰':'Poland','瑞士':'Switzerland','瑞典':'Sweden','乌兹别克斯坦':'Uzbekistan',
  '荷兰中心仓':'Netherlands Central Warehouse','英国中心仓':'UK Central Warehouse',
  '德国仓':'Germany Warehouse','意大利仓':'Italy Warehouse','法国仓':'France Warehouse',
  '西班牙 NSC 仓':'Spain NSC Warehouse','波兰仓':'Poland Warehouse','瑞士仓':'Switzerland Warehouse',
  '瑞典仓':'Sweden Warehouse','乌兹别克斯坦仓':'Uzbekistan Warehouse',
}
export function warehouseName(name:string) {
  return language === 'en' && Object.hasOwn(warehouseNames,name) ? warehouseNames[name] : name
}
