import {getLanguage,tr} from './i18n'
export function periodLabel(value:string, fallback?:string) {
 if(getLanguage()!=='en')return fallback||value
 if(/^\d{4}-\d{2}$/.test(value)) {
  const dt=new Date(value+'-01T00:00:00Z')
  return Number.isNaN(dt.valueOf())?value:dt.toLocaleDateString('en-GB',{month:'long',year:'numeric',timeZone:'UTC'})
 }
 if(/^\d{4}-W\d{2}$/.test(value))return value.slice(0,4)+' · Week '+Number(value.slice(-2))
 return fallback||value
}
export function defaultPlanTitle(period:string) {
 if(period.includes('-W'))return tr(period.slice(0,4)+'年第'+period.slice(-2)+'周补货计划',periodLabel(period)+' replenishment plan')
 const month=Number(period.slice(-2))
 return tr(month+'月补货计划',periodLabel(period)+' replenishment plan')
}
export function currentWeek(){const n=new Date();const d=new Date(Date.UTC(n.getFullYear(),n.getMonth(),n.getDate()));d.setUTCDate(d.getUTCDate()+4-(d.getUTCDay()||7));const year=d.getUTCFullYear();const start=new Date(Date.UTC(year,0,1));return year+'-W'+String(Math.ceil((((+d-+start)/86400000)+1)/7)).padStart(2,'0')}
export function weekLabel(value:string){if(!/^\d{4}-W\d{2}$/.test(value))return '';const year=Number(value.slice(0,4)),week=Number(value.slice(6));const d=new Date(Date.UTC(year,0,4));d.setUTCDate(d.getUTCDate()-(d.getUTCDay()||7)+1+(week-1)*7);const start=d.toISOString().slice(0,10);d.setUTCDate(d.getUTCDate()+6);const end=d.toISOString().slice(0,10);return tr(start+' 至 '+end+'（周一至周日）',start+' to '+end+' (Monday–Sunday)')}
