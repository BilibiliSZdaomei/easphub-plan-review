import {defineConfig, loadEnv} from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig(({ mode }) => {
const base=(loadEnv(mode, '.', 'APP_').APP_BASE_PATH || '/plan-review').replace(/\/$/,'')
if(!/^\/[a-zA-Z0-9_-]+(?:\/[a-zA-Z0-9_-]+)*$/.test(base))throw new Error('Invalid APP_BASE_PATH')
return {base:base+'/',plugins:[react(),{name:'deployment-contract',generateBundle(){this.emitFile({type:'asset',fileName:'app-build.json',source:JSON.stringify({base_path:base,review_model:'V2',market_scope:'EUROPE',account_mode:'managed',ui_revision:5})})}}],server:{proxy:{[base+'/api']:'http://127.0.0.1:3350'}}}
})
