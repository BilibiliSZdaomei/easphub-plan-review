import {createRoot} from 'react-dom/client'
import App from './App'
import './styles.css'
import './review-table-layout.css'
function initialTheme(): 'light'|'dark' {
 const query = new URLSearchParams(location.search).get('mode')
 if(query==='light'||query==='dark')return query
 try {
  const saved = localStorage.getItem('easphub.app.theme')
  if(saved==='light'||saved==='dark')return saved
  const platform = JSON.parse(localStorage.getItem('easphub.platform.prototype.v02')||'{}')
  return platform?.mode==='dark'?'dark':'light'
 } catch { return 'light' }
}

document.documentElement.dataset.eaMode=initialTheme()
createRoot(document.getElementById('root')!).render(<App/>);
