import { Link } from 'react-router-dom'
import { useEffect } from 'react'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'
import TopToolbar from './TopToolbar'
import AuthVisualPanel from './AuthVisualPanel'

interface Props {
  children: React.ReactNode
}

export default function AuthShell({ children }: Props) {
  const t = useI18n(s => s.t)

  useEffect(() => {
    const prev = document.documentElement.getAttribute('data-theme')
    useTheme.getState().setTheme('dark')
    return () => {
      if (prev === 'light' || prev === 'dark') useTheme.getState().setTheme(prev)
    }
  }, [])

  return (
    <div className="auth-framer-page">
      <div className="auth-toolbar-fixed">
        <TopToolbar />
      </div>
      <div className="auth-framer-grid">
        <div className="auth-framer-left">
          <AuthVisualPanel />
          <Link to="/" className="auth-back-link">{t('auth.backHome')}</Link>
        </div>
        <div className="auth-framer-right">
          <div className="auth-glass-shell">{children}</div>
        </div>
      </div>
    </div>
  )
}
