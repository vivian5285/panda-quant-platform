import { Link, useNavigate } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import { useState } from 'react'
import { useAuth } from '../../store/auth'
import { useI18n } from '../../i18n'
import LanguageSwitcher from '../LanguageSwitcher'
import ThemeToggle from '../ThemeToggle'

const anchors = ['features', 'stats', 'showcase', 'markets', 'faq'] as const

export default function LandingNav() {
  const t = useI18n(s => s.t)
  const token = useAuth(s => s.token)
  const isAdmin = useAuth(s => s.isAdmin)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const consolePath = token ? (isAdmin() ? '/admin' : '/dashboard') : '/login'

  const scrollTo = (id: string) => {
    setOpen(false)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <header className="landing-nav">
      <div className="landing-nav-inner">
        <Link to="/" className="landing-brand" onClick={() => setOpen(false)}>
          <span className="landing-brand-icon">🐼</span>
          <span className="landing-brand-text">
            <strong>{t('brand.name')}</strong>
            <small>{t('brand.tagline')}</small>
          </span>
        </Link>

        <nav className={`landing-links ${open ? 'open' : ''}`}>
          {anchors.map(id => (
            <button key={id} type="button" className="landing-link" onClick={() => scrollTo(id)}>
              {t(`landing.nav.${id}`)}
            </button>
          ))}
        </nav>

        <div className="landing-nav-actions">
          <LanguageSwitcher />
          <ThemeToggle />
          {token ? (
            <button type="button" className="btn btn-primary landing-nav-cta" onClick={() => navigate(consolePath)}>
              {t('landing.nav.console')}
            </button>
          ) : (
            <>
              <Link to="/login" className="btn btn-ghost landing-nav-signin">{t('auth.login')}</Link>
              <Link to="/register" className="btn btn-primary landing-nav-cta">{t('landing.hero.ctaPrimary')}</Link>
            </>
          )}
          <button type="button" className="landing-menu-btn" onClick={() => setOpen(v => !v)} aria-label="Menu">
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>
    </header>
  )
}
