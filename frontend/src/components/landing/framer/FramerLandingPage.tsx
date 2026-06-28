import { Link, useNavigate } from 'react-router-dom'
import { Menu, X, ArrowRight } from 'lucide-react'
import { useState } from 'react'
import { useAuth } from '../../../store/auth'
import { useI18n } from '../../../i18n'
import DashboardPreview from '../DashboardPreview'

const NAV_IDS = ['product', 'agents', 'platform', 'partners', 'security'] as const

export default function FramerLandingPage() {
  const t = useI18n(s => s.t)
  const locale = useI18n(s => s.locale)
  const setLocale = useI18n(s => s.setLocale)
  const token = useAuth(s => s.token)
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  const scrollTo = (id: string) => {
    setMenuOpen(false)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className="framer-site">
      <header className="framer-nav">
        <div className="framer-nav-inner">
          <Link to="/" className="framer-logo">
            <span className="framer-logo-mark">G</span>
            <span>{t('brand.name')}</span>
          </Link>
          <nav className={`framer-nav-links ${menuOpen ? 'open' : ''}`}>
            {NAV_IDS.map(id => (
              <button key={id} type="button" onClick={() => scrollTo(id)}>{t(`framer.nav.${id}`)}</button>
            ))}
          </nav>
          <div className="framer-nav-actions">
            <button type="button" className="framer-lang" onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}>
              {locale === 'zh' ? 'EN' : '中文'}
            </button>
            {token ? (
              <button type="button" className="framer-btn-primary" onClick={() => navigate('/dashboard')}>
                {t('framer.nav.console')}
              </button>
            ) : (
              <>
                <Link to="/login" className="framer-btn-ghost">{t('auth.login')}</Link>
                <Link to="/register" className="framer-btn-primary">{t('framer.nav.signup')}</Link>
              </>
            )}
            <button type="button" className="framer-menu-btn" onClick={() => setMenuOpen(v => !v)} aria-label="Menu">
              {menuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
      </header>

      {/* Hero — Framer homepage hero */}
      <section className="framer-hero">
        <div className="framer-pill">{t('framer.hero.pill')}</div>
        <h1>{t('framer.hero.title')}</h1>
        <p className="framer-hero-sub">{t('framer.hero.subtitle')}</p>
        <div className="framer-hero-cta">
          <Link to={token ? '/dashboard' : '/register'} className="framer-btn-primary">
            {t('framer.hero.ctaPrimary')}
          </Link>
          <button type="button" className="framer-btn-secondary" onClick={() => scrollTo('product')}>
            {t('framer.hero.ctaSecondary')}
          </button>
        </div>

        <div className="framer-canvas-wrap">
          <div className="framer-canvas-bar">
            <span /><span /><span />
            <span style={{ marginLeft: 8 }}>{t('framer.hero.canvasLabel')}</span>
          </div>
          <div className="framer-canvas-body">
            <div className="framer-canvas-sidebar">
              <div className="active">{t('framer.hero.sidebar.dashboard')}</div>
              <div>{t('framer.hero.sidebar.trading')}</div>
              <div>{t('framer.hero.sidebar.signals')}</div>
              <div>{t('framer.hero.sidebar.analytics')}</div>
              <div>{t('framer.hero.sidebar.settlement')}</div>
            </div>
            <div className="framer-canvas-preview">
              <DashboardPreview slide="dashboard" />
            </div>
          </div>
        </div>
      </section>

      {/* Shipped with — product carousel */}
      <section id="product" className="framer-section framer-section-wide">
        <div className="framer-section-head">
          <p className="framer-kicker">{t('framer.shipped.kicker')}</p>
          <h2>{t('framer.shipped.title')}</h2>
        </div>
        <div className="framer-carousel">
          {(['dashboard', 'trading', 'signals', 'analytics', 'settlement'] as const).map(k => (
            <div key={k} className="framer-carousel-card">
              <div className="fr-mock">{t(`framer.shipped.items.${k}`)}</div>
              <p>{t(`framer.shipped.items.${k}`)}</p>
            </div>
          ))}
        </div>
        <p className="framer-kicker" style={{ textAlign: 'center', marginTop: 48 }}>{t('framer.shipped.customers')}</p>
      </section>

      {/* Agents — 3 blocks like Framer */}
      <section id="agents">
        <div className="framer-section-head" style={{ padding: '0 24px' }}>
          <h2>{t('framer.agents.title')}</h2>
          <p>{t('framer.agents.subtitle')}</p>
        </div>

        {(['signal', 'risk', 'settle'] as const).map((key, i) => (
          <div key={key} className={`framer-agent-block ${i % 2 === 1 ? 'reverse' : ''}`}>
            <div className="framer-agent-copy">
              <p className="framer-kicker">{t(`framer.agents.items.${key}.kicker`)}</p>
              <h3>{t(`framer.agents.items.${key}.title`)}</h3>
              <p>{t(`framer.agents.items.${key}.desc`)}</p>
              <Link to="/register">{t('framer.agents.learn')} →</Link>
            </div>
            <div className="framer-mock-ui">
              {key === 'signal' && (
                <div style={{ padding: 16, fontFamily: 'ui-monospace, monospace', fontSize: 12, lineHeight: 1.7 }}>
                  <div style={{ color: '#666', marginBottom: 8 }}>{t('framer.agents.items.signal.mockTitle')}</div>
                  <div>{t('framer.agents.items.signal.mockLine1')}</div>
                  <div style={{ color: '#2e7d32' }}>{t('framer.agents.items.signal.mockLine2')}</div>
                </div>
              )}
              {key === 'risk' && (
                <table className="framer-table-mock">
                  <thead>
                    <tr><th>{t('framer.agents.table.event')}</th><th>{t('framer.agents.table.status')}</th><th>{t('framer.agents.table.latency')}</th></tr>
                  </thead>
                  <tbody>
                    {(['a', 'b', 'c'] as const).map(r => (
                      <tr key={r}>
                        <td>{t(`framer.agents.items.risk.rows.${r}.event`)}</td>
                        <td><span className="framer-badge-live">{t(`framer.agents.items.risk.rows.${r}.status`)}</span></td>
                        <td>{t(`framer.agents.items.risk.rows.${r}.latency`)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {key === 'settle' && (
                <div style={{ padding: 20 }}>
                  <div className="framer-metric-row">
                    <div><strong>58%</strong><span>{t('framer.agents.items.settle.winRate')}</span></div>
                    <div><strong>&lt;1s</strong><span>{t('framer.agents.items.settle.latency')}</span></div>
                    <div><strong>7/10d</strong><span>{t('framer.agents.items.settle.cycle')}</span></div>
                  </div>
                  <p style={{ marginTop: 16, fontSize: 13, color: '#666' }}>{t('framer.agents.items.settle.note')}</p>
                </div>
              )}
            </div>
          </div>
        ))}
      </section>

      {/* Connect — API partnership */}
      <section className="framer-agent-block">
        <div className="framer-agent-copy">
          <p className="framer-kicker">{t('framer.api.kicker')}</p>
          <h3>{t('framer.api.title')}</h3>
          <p>{t('framer.api.desc')}</p>
          <Link to="/register" className="framer-btn-primary" style={{ marginTop: 8 }}>
            {t('framer.api.cta')} <ArrowRight size={16} />
          </Link>
        </div>
        <div className="framer-mock-ui" style={{ padding: 16, fontFamily: 'ui-monospace, monospace', fontSize: 11, background: '#1a1a1a', color: '#e0e0e0' }}>
          <div style={{ color: '#888' }}>$ bind-binance-api --futures-only --no-withdraw</div>
          <div style={{ color: '#7cfc7c' }}>✓ Connection verified</div>
          <div style={{ color: '#7cfc7c' }}>✓ One-way mode OK · Leverage 15x</div>
          <div style={{ color: '#7cfc7c' }}>✓ Supervisor loaded · Sentinel 6s</div>
          <div style={{ marginTop: 12, color: '#888' }}>{t('framer.api.terminalNote')}</div>
        </div>
      </section>

      {/* Platform grid — Not just vibes */}
      <section id="platform" className="framer-section" style={{ paddingTop: 0 }}>
        <div className="framer-section-head">
          <h2>{t('framer.platform.title')}</h2>
        </div>
        <div className="framer-platform-grid">
          <div className="framer-platform-card span2">
            <h4>{t('framer.platform.performance.title')}</h4>
            <div className="framer-metric-row">
              <div><strong>GOOD</strong><span>Core Web Vitals</span></div>
              <div><strong>&lt;1s</strong><span>{t('framer.platform.performance.lcp')}</span></div>
              <div><strong>95ms</strong><span>INP</span></div>
            </div>
          </div>
          <div className="framer-platform-card">
            <h4>{t('framer.platform.security.title')}</h4>
            <p>{t('framer.platform.security.desc')}</p>
          </div>
          <div className="framer-platform-card">
            <h4>{t('framer.platform.latency.title')}</h4>
            <p>{t('framer.platform.latency.desc')}</p>
          </div>
          <div className="framer-platform-card">
            <h4>{t('framer.platform.signals.title')}</h4>
            <p>{t('framer.platform.signals.desc')}</p>
          </div>
          <div className="framer-platform-card">
            <h4>{t('framer.platform.winrate.title')}</h4>
            <p>{t('framer.platform.winrate.desc')}</p>
          </div>
          <div className="framer-platform-card span2">
            <h4>{t('framer.platform.settlement.title')}</h4>
            <p>{t('framer.platform.settlement.desc')}</p>
          </div>
          <div className="framer-platform-card span4" style={{ textAlign: 'center' }}>
            <h4>{t('framer.platform.partnership.title')}</h4>
            <p>{t('framer.platform.partnership.desc')}</p>
          </div>
        </div>
      </section>

      {/* Partners & countries */}
      <section id="partners" className="framer-section">
        <div className="framer-section-head">
          <p className="framer-kicker">{t('framer.partners.kicker')}</p>
          <h2>{t('framer.partners.title')}</h2>
          <p>{t('framer.partners.subtitle')}</p>
        </div>
        <div className="framer-logos-row">
          {(['binance', 'tradingview', 'redis', 'fastapi'] as const).map(k => (
            <span key={k}>{t(`framer.partners.logos.${k}`)}</span>
          ))}
        </div>
        <div className="framer-countries">
          {(['sg', 'hk', 'ae', 'jp', 'uk', 'us', 'de', 'au'] as const).map(c => (
            <span key={c} className="framer-country-pill">{t(`framer.partners.countries.${c}`)}</span>
          ))}
        </div>
      </section>

      {/* Security */}
      <section id="security" className="framer-agent-block reverse">
        <div className="framer-agent-copy">
          <p className="framer-kicker">{t('framer.security.kicker')}</p>
          <h3>{t('framer.security.title')}</h3>
          <p>{t('framer.security.desc')}</p>
        </div>
        <div className="framer-mock-ui" style={{ padding: 24 }}>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {(['api', 'dual', 'audit', 'nocustody'] as const).map(k => (
              <li key={k} style={{ padding: '12px 0', borderBottom: '1px solid rgba(0,0,0,0.08)', fontSize: 14 }}>
                <strong>{t(`framer.security.points.${k}.title`)}</strong>
                <p style={{ margin: '4px 0 0', color: '#666', fontSize: 13 }}>{t(`framer.security.points.${k}.desc`)}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Final CTA */}
      <section className="framer-cta-final">
        <h2>{t('framer.final.title')}</h2>
        <Link to={token ? '/dashboard' : '/register'} className="framer-btn-primary">
          {t('framer.final.cta')}
        </Link>
      </section>

      {/* Footer — Framer-style */}
      <footer className="framer-footer">
        <div className="framer-footer-inner">
          <div className="framer-footer-grid">
            <div>
              <div className="framer-logo" style={{ marginBottom: 12 }}>
                <span className="framer-logo-mark">G</span>
                <span>{t('brand.name')}</span>
              </div>
              <p style={{ fontSize: 13, color: '#666', maxWidth: 280 }}>{t('framer.footer.tagline')}</p>
            </div>
            <div>
              <h5>{t('framer.footer.product')}</h5>
              <a href="#product" onClick={e => { e.preventDefault(); scrollTo('product') }}>{t('framer.nav.product')}</a>
              <Link to="/help">{t('nav.help')}</Link>
              <Link to="/register">{t('auth.register')}</Link>
            </div>
            <div>
              <h5>{t('framer.footer.company')}</h5>
              <a href="#partners" onClick={e => { e.preventDefault(); scrollTo('partners') }}>{t('framer.nav.partners')}</a>
              <a href="#security" onClick={e => { e.preventDefault(); scrollTo('security') }}>{t('framer.nav.security')}</a>
            </div>
            <div>
              <h5>{t('framer.footer.legal')}</h5>
              <Link to="/privacy">{t('saas.footer.privacy')}</Link>
              <Link to="/terms">{t('saas.footer.terms')}</Link>
            </div>
            <div>
              <h5>{t('framer.footer.connect')}</h5>
              <Link to="/login">{t('auth.login')}</Link>
            </div>
          </div>
          <div className="framer-footer-bottom">
            <span>{t('framer.footer.rights')}</span>
            <span>{t('framer.footer.risk')}</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
