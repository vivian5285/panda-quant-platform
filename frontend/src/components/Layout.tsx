import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import {
  LayoutDashboard, ArrowLeftRight, ScrollText, Link2,
  Wallet, Settings, Shield, LogOut, Menu, X, Banknote, UserCircle
} from 'lucide-react'
import { useState } from 'react'

const userNav = [
  { to: '/dashboard', icon: LayoutDashboard, label: '仪表盘' },
  { to: '/trades', icon: ArrowLeftRight, label: '交易记录' },
  { to: '/logs', icon: ScrollText, label: '操作日志' },
  { to: '/referrals', icon: Link2, label: '推广中心' },
  { to: '/settlements', icon: Wallet, label: '结算记录' },
  { to: '/withdraw', icon: Banknote, label: '奖励提现' },
  { to: '/profile', icon: UserCircle, label: '个人资料' },
  { to: '/api', icon: Settings, label: 'API 管理' },
]

const adminNav = [
  { to: '/admin', icon: Shield, label: '管理后台' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { displayName, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const nav = [...userNav, ...(isAdmin() ? adminNav : [])]

  const sidebar = (
    <aside className="app-sidebar">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', marginBottom: 32 }}>
        <span style={{ fontSize: 28 }}>🐼</span>
        <div>
          <div style={{ fontWeight: 600, fontSize: 16, letterSpacing: '-0.02em' }}>熊猫量化</div>
          <div className="text-muted" style={{ fontSize: 11 }}>Panda Quant AI</div>
        </div>
      </div>

      <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="section-divider">
        <div className="text-muted" style={{ fontSize: 12, padding: '0 14px', marginBottom: 8 }}>{displayName || '用户'}</div>
        <button className="btn btn-ghost" style={{ width: '100%', fontSize: 13 }} onClick={handleLogout}>
          <LogOut size={16} /> 退出登录
        </button>
      </div>
    </aside>
  )

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <div className="desktop-sidebar">{sidebar}</div>

      {mobileOpen && (
        <div className="mobile-overlay" onClick={() => setMobileOpen(false)}>
          <div onClick={e => e.stopPropagation()}>{sidebar}</div>
        </div>
      )}

      <main style={{ flex: 1, padding: '32px 40px', maxWidth: 1200, background: 'transparent' }}>
        <button
          className="btn btn-ghost mobile-menu-btn"
          style={{ display: 'none', marginBottom: 16 }}
          onClick={() => setMobileOpen(!mobileOpen)}
        >
          {mobileOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        {children}
      </main>

      <style>{`
        @media (max-width: 768px) {
          .desktop-sidebar { display: none; }
          .mobile-menu-btn { display: inline-flex !important; }
          main { padding: 16px !important; }
        }
      `}</style>
    </div>
  )
}
