import { NavLink, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import GeminiLogo from './GeminiLogo'
import NotificationDropdown from './NotificationDropdown'
import TopToolbar from './TopToolbar'
import AppSearchNav, { SearchNavItem } from './AppSearchNav'
import {
  LayoutDashboard, ArrowLeftRight, ScrollText, Link2, Wallet, Shield, LogOut,
  Menu, X, Banknote, UserCircle, TrendingUp, KeyRound,
} from 'lucide-react'
import { useMemo, useState } from 'react'

export default function Layout({ children }: { children: React.ReactNode }) {
  const { displayName, logout, isAdmin, role } = useAuth()
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

  const userNav = [
    { to: '/dashboard', icon: LayoutDashboard, label: t('nav.dashboard') },
    { to: '/trading', icon: TrendingUp, label: t('nav.trading') },
    { to: '/trades', icon: ArrowLeftRight, label: t('nav.trades') },
    { to: '/logs', icon: ScrollText, label: t('nav.logs') },
    { to: '/api', icon: KeyRound, label: t('nav.api') },
    { to: '/referrals', icon: Link2, label: t('nav.referrals') },
    { to: '/settlements', icon: Wallet, label: t('nav.settlements') },
    { to: '/withdraw', icon: Banknote, label: t('nav.withdraw') },
    { to: '/profile', icon: UserCircle, label: t('nav.profile') },
  ]

  const adminNav = [{ to: '/admin', icon: Shield, label: t('nav.admin') }]
  const nav = [...userNav, ...(isAdmin() ? adminNav : [])]

  const searchItems: SearchNavItem[] = useMemo(() => {
    const core = nav.map(({ to, label }) => ({ to, label }))
    const extra = [
      { to: '/help', label: t('nav.help'), keywords: 'help faq docs' },
      { to: '/settings', label: t('nav.settings'), keywords: 'settings 2fa notification' },
      { to: '/strategies', label: t('nav.strategies'), keywords: 'strategy webhook' },
      { to: '/signals', label: t('nav.signals'), keywords: 'ai indicator signal' },
      { to: '/analytics', label: t('nav.analytics'), keywords: 'sharpe analytics' },
    ]
    const seen = new Set(core.map(c => c.to))
    return [...core, ...extra.filter(e => !seen.has(e.to))]
  }, [locale, role, t])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const sidebar = (
    <aside className="app-sidebar">
      <Link to="/" className="sidebar-brand framer-logo" onClick={() => setMobileOpen(false)}>
        <GeminiLogo size="md" />
        <span className="framer-logo-text">
          <strong>{t('brand.name')}</strong>
          <small>{t('brand.tagline')}</small>
        </span>
      </Link>

      <nav key={locale} className="sidebar-nav">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink key={to} to={to} onClick={() => setMobileOpen(false)}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            <Icon size={18} /> {label}
          </NavLink>
        ))}
      </nav>

      <div className="section-divider">
        <div className="text-muted sidebar-user">{displayName || t('common.user')}</div>
        <button className="btn btn-ghost sidebar-logout" onClick={handleLogout}>
          <LogOut size={16} /> {t('common.logout')}
        </button>
      </div>
    </aside>
  )

  return (
    <div className="app-shell">
      <TopToolbar />
      <div className="desktop-sidebar">{sidebar}</div>

      {mobileOpen && (
        <div className="mobile-overlay" onClick={() => setMobileOpen(false)}>
          <div onClick={e => e.stopPropagation()}>{sidebar}</div>
        </div>
      )}

      <main className="app-main">
        <div className="app-topbar glass">
          <button type="button" className="btn btn-ghost mobile-menu-btn" onClick={() => setMobileOpen(!mobileOpen)}>
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <AppSearchNav items={searchItems} onNavigate={() => setMobileOpen(false)} />
          <div className="app-topbar-actions">
            <NotificationDropdown />
          </div>
        </div>
        <div className="animate-in app-content">{children}</div>
      </main>
    </div>
  )
}
