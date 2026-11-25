import {useEffect,useState} from 'react'
import {Mail,RefreshCw} from 'lucide-react'
import {api} from './api'
import {tr} from './i18n'

type MailStatus={smtp_configured:boolean;counts:Record<string,number>}
export default function MailDeliveryStatus(){
  const [open,setOpen]=useState(false),[seq,refresh]=useState(0)
  const [data,setData]=useState<MailStatus|null>(null),[error,setError]=useState(false)
  useEffect(()=>{
    if(!open)return
    const controller=new AbortController()
    setError(false)
    api<MailStatus>('/mail-delivery/status',undefined,'GET',undefined,controller.signal)
      .then(s=>{if(!controller.signal.aborted)setData(s)}).catch(()=>{if(!controller.signal.aborted)setError(true)})
    return ()=>controller.abort()
  },[open,seq])
  return <details className="panel mail-status" onToggle={e=>setOpen(e.currentTarget.open)}>
    <summary><Mail size={16}/>{tr('邮件投递','Email delivery')}</summary>
    {open&&<div className="mail-status-body">
      <div className="mail-status-heading"><span>{error?tr('暂时无法读取','Unable to load delivery status'):!data?tr('正在读取…','Loading…'):
        data.smtp_configured?tr('已配置 SMTP 发信服务','SMTP service configured'):tr('等待配置 SMTP 发信服务','SMTP setup pending')}</span>
        <button type="button" className="text-button" onClick={()=>refresh(n=>n+1)} aria-label={tr('刷新邮件投递','Refresh email delivery')}><RefreshCw size={15}/></button></div>
      {data&&!error&&<dl>{[
        [tr('待发送','Queued'),(data.counts.QUEUED??0)+(data.counts.RETRY??0)],
        [tr('投递中','Sending'),(data.counts.RUNNING??0)+(data.counts.SENDING??0)],
        [tr('待补邮箱','Missing email'),data.counts.WAITING_EMAIL??0],
        [tr('已发送','Sent'),data.counts.SENT??0],
        [tr('投递失败','Failed'),data.counts.FAILED??0],
        [tr('已取消','Cancelled'),data.counts.CANCELLED??0],
      ].map(([label,count])=><div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>}
      {!!data?.counts.WAITING_EMAIL&&<p>{tr('到「人员与权限」补录收件邮箱，待发邮件会自动进入队列。','Add a notification email in People and permissions to queue waiting mail.')}</p>}
    </div>}
  </details>
}
