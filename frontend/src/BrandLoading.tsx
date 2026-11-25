import {useEffect, useState} from 'react'
import logoLight from './brand/mono-neutral-light-intro-draw.svg'
import logoDark from './brand/mono-neutral-dark-intro-draw.svg'
import stillLight from './brand/mono-neutral-light.svg'
import stillDark from './brand/mono-neutral-dark.svg'
import {tr} from './i18n'
import './brand-loading.css'

// Use the matching static master directly when the browser requests reduced motion.
export default function BrandLoading({theme}: {theme: 'light' | 'dark'}) {
  return <main className="brand-loading" role="status">
    <picture>
      <source media="(prefers-reduced-motion: reduce)" srcSet={theme === 'dark' ? stillDark : stillLight} />
      <img src={theme === 'dark' ? logoDark : logoLight} width="976" height="300" alt="EASPhub" />
    </picture>
    <span>{tr('正在打开计划审核…', 'Opening Plan Review…')}</span>
  </main>
}

export function useDelayedLoading(pending: boolean) {
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    if (!pending) {
      setVisible(false)
      return
    }
    const timer = window.setTimeout(() => setVisible(true), 200)
    return () => window.clearTimeout(timer)
  }, [pending])
  return pending && visible
}
