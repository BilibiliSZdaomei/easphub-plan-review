import {Languages} from 'lucide-react'
import {setLanguage,useLanguage} from './i18n'

export default function LanguageSwitcher(){
  const language=useLanguage()
  const english=language==='en'
  return <button type="button" className="language-switch" lang={english?'zh-CN':'en'}
    aria-label={english?'切换到中文':'Switch to English'} title={english?'切换到中文':'Switch to English'}
    onClick={()=>setLanguage(english?'zh-CN':'en')}>
    <Languages size={16} aria-hidden="true"/><span>{english?'中文':'English'}</span>
  </button>
}
