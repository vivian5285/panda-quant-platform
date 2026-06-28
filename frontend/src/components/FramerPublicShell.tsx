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
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Link to="/login" className="framer-btn-ghost" style={{ fontSize: 14, textDecoration: 'none' }}>
            {t('auth.login')}
          </Link>
          <TopToolbar />
        </div>
      </header>
      {children}
    </div>
  )
}
