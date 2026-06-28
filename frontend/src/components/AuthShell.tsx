import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import FramerBrand from './FramerBrand'
import TopToolbar from './TopToolbar'

interface Props {
  children: React.ReactNode
  sideTitle?: string
  sideSubtitle?: string
}

export default function AuthShell({ children, sideTitle, sideSubtitle }: Props) {
  const t = useI18n(s => s.t)

  return (
    <div className="auth-split-page">
      <div className="auth-toolbar-fixed">
        <TopToolbar />
      </div>
      <div className="auth-split-left">
        <div className="auth-split-brand">
          <FramerBrand showTagline />
          <h1>{sideTitle || `${t('framer.hero.titleLead')} ${t('framer.hero.titleAccent')}`}</h1>
          <p>{sideSubtitle || t('framer.hero.subtitle')}</p>
          <Link to="/" className="auth-back-link">{t('auth.backHome')}</Link>
        </div>
      </div>
      <div className="auth-split-right">
        {children}
      </div>
    </div>
  )
}
