import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import TopToolbar from './TopToolbar'
import AuthVisualPanel from './AuthVisualPanel'

interface Props {
  children: React.ReactNode
}

export default function AuthShell({ children }: Props) {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)

  return (
    <div className="auth-framer-page" key={locale}>
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
