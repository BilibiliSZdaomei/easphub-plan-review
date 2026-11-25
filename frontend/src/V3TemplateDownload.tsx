import {getLanguage, systemText} from './i18n'
import {useState} from 'react'
import {Download} from 'lucide-react'
import {BASE,localDay} from './api'

export default function V3TemplateDownload({versionId,chooseMonth=false}: {versionId?:string;chooseMonth?:boolean}){
  const [month,setMonth]=useState(()=>localDay(new Date().toISOString()).slice(0,7))
  const params=new URLSearchParams({kind:'v3'})
  if(getLanguage()==='en')params.set('lang','en')
  if(versionId)params.set('version_id',versionId)
  if(chooseMonth)params.set('period',month)
  const valid=!chooseMonth||/^\d{4}-\d{2}$/.test(month)
  return <>
    {chooseMonth&&<label className="template-month">{systemText("模板月份")}<input type="month" required value={month} onChange={e=>setMonth(e.target.value)}/></label>}
    <a className={versionId?'text-button':'secondary'} href={valid?BASE+'/template?'+params:undefined} aria-disabled={!valid}>
      <Download size={versionId?14:15}/>{versionId?systemText("完整计划模板（V3）"):systemText("下载 V3 模板")}
    </a>
  </>
}
