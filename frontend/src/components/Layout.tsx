import { NavLink, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import GeminiLogo from './GeminiLogo'
import NotificationDropdown from './NotificationDropdown'
import TopToolbar from './TopToolbar'
import AppSearchNav, { SearchNavItem } from './AppSearchNav'
import ToastHost from './ui/ToastHost'
import {
  LayoutDashboard, ArrowLeftRight, Wallet, LogOut,
  Menu, X, UserCircle, TrendingUp, KeyRound, BarChart3, ShieldAlert, Share2, Layers,
  Sparkles, HelpCircle,
} from 'lucide-react'
import { useMemo, useState } from 'react'

export default function Layout({ children }: { children: React.ReactNode }) {
  const { displayName, logout, uid } = useAuth()
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

  const nav = [
    { to: '/dashboard', icon: LayoutDashboard, label: t('nav.dashboard') },
    { to: '/strategies', icon: Sparkles, label: t('nav.strategies') },
    { to: '/trading', icon: TrendingUp, label: t('nav.trading') },
    { to: '/positions', icon: Layers, label: t('nav.positions') },
    { to: '/trades', icon: ArrowLeftRight, label: t('nav.trades') },
    { to: '/risk', icon: ShieldAlert, label: t('nav.risk') },
    { to: '/api', icon: KeyRound, label: t('nav.api') },
    { to: '/analytics', icon: BarChart3, label: t('nav.analytics') },
    { to: '/help', icon: HelpCircle, label: t('nav.help') },
    { to: '/referrals', icon: Share2, label: t('nav.referrals') },
    { to: '/settlements', icon: Wallet, label: t('nav.settlements') },
    { to: '/profile', icon: UserCircle, label: t('nav.profile') },
  ]

  const searchItems: SearchNavItem[] = useMemo(() => {
    const core: SearchNavItem[] = nav.map(({ to, label }) => ({ to, label }))
    return [...core, { to: '/withdraw', label: t('nav.withdraw'), keywords: 'withdraw reward transfer' }]
  }, [locale, t, nav])

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
    <div className="framer-site app-console app-shell">
      <TopToolbar />
      <div className="desktop-sidebar">{sidebar}</div>

      {mobileOpen && (
        <div className="mobile-overlay" onClick={() => setMobileOpen(false)}>
          <div onClick={e => e.stopPropagation()}>{sidebar}</div>
        </div>
      )}

      <main className="app-main">
        <div className="app-topbar glass framer-glass-cell">
          <button type="button" className="btn btn-ghost mobile-menu-btn" onClick={() => setMobileOpen(!mobileOpen)}>
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <AppSearchNav items={searchItems} onNavigate={() => setMobileOpen(false)} />
          <div className="app-topbar-actions">
            <NotificationDropdown />
          </div>
        </div>
        <div className="user-scope-bar">
          <span>{t('scope.userAccount')}</span>
          {uid && <span className="user-scope-uid">UID {uid}</span>}
        </div>
        <div className="animate-in app-content">{children}</div>
      </main>
      <ToastHost />
    </div>
  )
}
