import { NavLink, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'
import GeminiLogo from './GeminiLogo'
import TopToolbar from './TopToolbar'
import {
  Shield, LogOut, Menu, X, LayoutDashboard, Users, Wallet, Bell,
  Landmark, Banknote, KeyRound, Bot, Activity, Radio, FileText, Share2,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import ToastHost from './ui/ToastHost'

export type AdminTabKey =
  | 'home' | 'users' | 'signals' | 'execution' | 'risk' | 'analytics' | 'audit'
  | 'finance' | 'settlements' | 'withdrawals' | 'referrals' | 'addresses' | 'system'

const ADMIN_TABS: { key: AdminTabKey; icon: typeof LayoutDashboard; labelKey: string }[] = [
  { key: 'home', icon: LayoutDashboard, labelKey: 'admin.tabOverview' },
  { key: 'users', icon: Users, labelKey: 'admin.tabUsers' },
  { key: 'signals', icon: Bot, labelKey: 'admin.tabSignals' },
  { key: 'execution', icon: Radio, labelKey: 'admin.tabExecution' },
  { key: 'risk', icon: Bell, labelKey: 'admin.tabRisk' },
  { key: 'analytics', icon: Wallet, labelKey: 'admin.tabAnalytics' },
  { key: 'audit', icon: FileText, labelKey: 'admin.tabAudit' },
  { key: 'finance', icon: Wallet, labelKey: 'admin.tabFinance' },
  { key: 'settlements', icon: Landmark, labelKey: 'admin.tabSettlements' },
  { key: 'referrals', icon: Share2, labelKey: 'admin.tabReferrals' },
  { key: 'withdrawals', icon: Banknote, labelKey: 'admin.tabWithdrawals' },
  { key: 'addresses', icon: KeyRound, labelKey: 'admin.tabAddresses' },
  { key: 'system', icon: Activity, labelKey: 'admin.tabSystem' },
]

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { displayName, logout } = useAuth()
  const t = useI18n(s => s.t)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const activeTab = (searchParams.get('tab') || 'home') as AdminTabKey
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    useTheme.getState().setTheme('dark')
  }, [])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const sidebar = (
    <aside className="app-sidebar admin-sidebar">
      <Link to="/admin?tab=home" className="sidebar-brand framer-logo" onClick={() => setMobileOpen(false)}>
        <GeminiLogo size="md" />
        <span className="framer-logo-text">
          <strong>{t('admin.consoleTitle')}</strong>
          <small>{t('admin.consoleSubtitle')}</small>
        </span>
      </Link>

      <div className="admin-sidebar-badge">
        <Shield size={14} />
        <span>{t('admin.consoleBadge')}</span>
      </div>

      <nav className="sidebar-nav">
        {ADMIN_TABS.map(({ key, icon: Icon, labelKey }) => (
          <NavLink
            key={key}
            to={`/admin?tab=${key}`}
            onClick={() => setMobileOpen(false)}
            className={() => `nav-link${activeTab === key ? ' active' : ''}`}
          >
            <Icon size={18} /> {t(labelKey)}
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
    <div className="framer-site app-console admin-shell app-shell">
      <TopToolbar />
      <div className="desktop-sidebar">{sidebar}</div>

      {mobileOpen && (
        <div className="mobile-overlay" onClick={() => setMobileOpen(false)}>
          <div onClick={e => e.stopPropagation()}>{sidebar}</div>
        </div>
      )}

      <main className="app-main">
        <div className="app-topbar glass framer-glass-cell admin-topbar">
          <button type="button" className="btn btn-ghost mobile-menu-btn" onClick={() => setMobileOpen(!mobileOpen)}>
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <div className="admin-topbar-title">{t('admin.consoleTitle')}</div>
        </div>
        <div className="admin-scope-bar">
          <Shield size={14} />
          <span>{t('admin.consoleBadge')}</span>
        </div>
        <div className="animate-in app-content">{children}</div>
      </main>
      <ToastHost />
    </div>
  )
}
