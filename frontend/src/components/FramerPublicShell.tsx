import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import FramerBrand from './FramerBrand'
import TopToolbar from './TopToolbar'

interface Props {
  children: React.ReactNode
}

export default function FramerPublicShell({ children }: Props) {
  const t = useI18n(s => s.t)

  return (
    <div className="framer-public-page">
      <header className="framer-public-nav">
        <FramerBrand />
        <div className="framer-public-nav-actions">
          <Link to="/login" className="framer-btn-ghost framer-public-login">
            {t('auth.login')}
          </Link>
          <TopToolbar />
        </div>
      </header>
      {children}
    </div>
  )
}
