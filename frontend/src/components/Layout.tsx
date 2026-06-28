import { NavLink, useNavigate } from 'react-router-dom'

import { useAuth } from '../store/auth'

import { useI18n } from '../i18n'

import TopToolbar from './TopToolbar'

import {

  LayoutDashboard, ArrowLeftRight, ScrollText, Link2,

  Wallet, Settings, Shield, LogOut, Menu, X, Banknote, UserCircle

} from 'lucide-react'

import { useState } from 'react'



export default function Layout({ children }: { children: React.ReactNode }) {

  const { displayName, logout, isAdmin } = useAuth()

  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)

  const navigate = useNavigate()

  const [mobileOpen, setMobileOpen] = useState(false)



  const userNav = [

    { to: '/dashboard', icon: LayoutDashboard, label: t('nav.dashboard') },

    { to: '/trades', icon: ArrowLeftRight, label: t('nav.trades') },

    { to: '/logs', icon: ScrollText, label: t('nav.logs') },

    { to: '/referrals', icon: Link2, label: t('nav.referrals') },

    { to: '/settlements', icon: Wallet, label: t('nav.settlements') },

    { to: '/withdraw', icon: Banknote, label: t('nav.withdraw') },

    { to: '/profile', icon: UserCircle, label: t('nav.profile') },

    { to: '/api', icon: Settings, label: t('nav.api') },

  ]



  const adminNav = [{ to: '/admin', icon: Shield, label: t('nav.admin') }]

  const nav = [...userNav, ...(isAdmin() ? adminNav : [])]



  const handleLogout = () => {

    logout()

    navigate('/login')

  }



  const sidebar = (

    <aside className="app-sidebar">

      <div className="sidebar-brand">

        <span className="sidebar-brand-icon">🐼</span>

        <div>

          <div className="sidebar-brand-name">{t('brand.name')}</div>

          <div className="sidebar-brand-tag">{t('brand.tagline')}</div>

        </div>

      </div>



      <nav key={locale} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>

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

        <div className="text-muted" style={{ fontSize: 12, padding: '0 14px', marginBottom: 8 }}>

          {displayName || t('common.user')}

        </div>

        <button className="btn btn-ghost" style={{ width: '100%', fontSize: 13 }} onClick={handleLogout}>

          <LogOut size={16} /> {t('common.logout')}

        </button>

      </div>

    </aside>

  )



  return (

    <div style={{ display: 'flex', minHeight: '100vh' }}>

      <TopToolbar />

      <div className="desktop-sidebar">{sidebar}</div>



      {mobileOpen && (

        <div className="mobile-overlay" onClick={() => setMobileOpen(false)}>

          <div onClick={e => e.stopPropagation()}>{sidebar}</div>

        </div>

      )}



      <main className="app-main">

        <button

          className="btn btn-ghost mobile-menu-btn"

          style={{ display: 'none', marginBottom: 16 }}

          onClick={() => setMobileOpen(!mobileOpen)}

        >

          {mobileOpen ? <X size={18} /> : <Menu size={18} />}

        </button>

        <div className="animate-in">{children}</div>

      </main>

    </div>

  )

}


