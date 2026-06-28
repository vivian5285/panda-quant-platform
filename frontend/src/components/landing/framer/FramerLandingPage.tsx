import { Link, useNavigate } from 'react-router-dom'
import { Menu, X, ArrowRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { useAuth } from '../../../store/auth'
import { useI18n } from '../../../i18n'
import FramerBrand from '../../FramerBrand'
import ScrollReveal from '../../ui/ScrollReveal'
import FramerHeroBackdrop from './FramerHeroBackdrop'
import FramerHeroMedia from './FramerHeroMedia'
import FramerShowcaseMarquee from './FramerShowcaseMarquee'
import FramerPlatformBento from './FramerPlatformBento'
import FramerCommunitySection from './FramerCommunitySection'
import FramerPartnerLogos from './FramerPartnerLogos'
import FramerCustomerStories from './FramerCustomerStories'

const NAV_IDS = ['product', 'agents', 'platform', 'community', 'partners', 'security'] as const
const agentKeys = ['signal', 'risk', 'settle', 'strategy'] as const

const heroEase = [0.22, 1, 0.36, 1] as const

export default function FramerLandingPage() {
  const t = useI18n(s => s.t)
  const locale = useI18n(s => s.locale)
  const setLocale = useI18n(s => s.setLocale)
  const token = useAuth(s => s.token)
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [navScrolled, setNavScrolled] = useState(false)
  const reduceMotion = useReducedMotion()

  useEffect(() => {
    const onScroll = () => setNavScrolled(window.scrollY > 16)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const scrollTo = (id: string) => {
    setMenuOpen(false)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  const heroItem = (delay: number) =>
    reduceMotion
      ? {}
      : {
          initial: { opacity: 0, y: 32 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.7, delay, ease: heroEase },
        }

  return (
    <div className="framer-site">
      <header className={`framer-nav${navScrolled ? ' framer-nav-scrolled' : ''}`}>
        <div className="framer-nav-inner">
          <FramerBrand />
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

      <div className="framer-hero-zone">
        <FramerHeroBackdrop />
        <section className="framer-hero framer-hero-inner">
          <motion.div className="framer-pill framer-pill-shimmer" {...heroItem(0.05)}>
            {t('framer.hero.pill')}
          </motion.div>
          <motion.h1 {...heroItem(0.12)}>
            <span className="framer-title-line">{t('framer.hero.titleLead')}</span>
            <span className="framer-title-accent">{t('framer.hero.titleAccent')}</span>
          </motion.h1>
          <motion.p className="framer-hero-sub" {...heroItem(0.2)}>{t('framer.hero.subtitle')}</motion.p>
          <motion.div className="framer-hero-cta" {...heroItem(0.28)}>
            <Link to={token ? '/dashboard' : '/register'} className="framer-btn-primary">
              {t('framer.hero.ctaPrimary')}
            </Link>
            <button type="button" className="framer-btn-secondary" onClick={() => scrollTo('product')}>
              {t('framer.hero.ctaSecondary')}
            </button>
          </motion.div>
          <motion.div {...heroItem(0.38)} className="framer-hero-canvas-wrap">
            <FramerHeroMedia />
          </motion.div>
        </section>
      </div>

      <section id="product" className="framer-section framer-section-wide framer-shipped">
        <ScrollReveal>
          <div className="framer-section-head">
            <p className="framer-kicker">{t('framer.shipped.kicker')}</p>
            <h2>{t('framer.shipped.title')}</h2>
            <Link to="/register" className="framer-inline-link">{t('framer.shipped.cta')}</Link>
          </div>
        </ScrollReveal>
        <ScrollReveal delay={0.08} y={24}>
          <FramerShowcaseMarquee />
        </ScrollReveal>
        <ScrollReveal delay={0.12}>
          <p className="framer-kicker framer-customers-kicker">{t('framer.shipped.customers')}</p>
        </ScrollReveal>
      </section>

      <section id="agents" className="framer-section framer-agents-intro">
        <ScrollReveal>
          <div className="framer-section-head">
            <p className="framer-kicker">{t('framer.agents.kicker')}</p>
            <h2>{t('framer.agents.title')}</h2>
            <p>{t('framer.agents.subtitle')}</p>
            <Link to="/register" className="framer-btn-primary framer-agents-cta">{t('framer.agents.cta')}</Link>
          </div>
        </ScrollReveal>

        {agentKeys.map((key, i) => (
          <ScrollReveal key={key} delay={i * 0.06} y={48}>
            <div className={`framer-agent-block${i % 2 === 1 ? ' reverse' : ''}`}>
              <div className="framer-agent-copy">
                <p className="framer-kicker">{t(`framer.agents.items.${key}.kicker`)}</p>
                <h3>{t(`framer.agents.items.${key}.title`)}</h3>
                <p>{t(`framer.agents.items.${key}.desc`)}</p>
                <Link to="/register">{t('framer.agents.learn')} →</Link>
              </div>
              <div className="framer-mock-ui framer-mock-hover">
                {key === 'signal' && (
                  <div className="framer-mock-terminal">
                    <div className="framer-mock-terminal-head">{t('framer.agents.items.signal.mockTitle')}</div>
                    <div>{t('framer.agents.items.signal.mockLine1')}</div>
                    <div className="framer-mock-success">{t('framer.agents.items.signal.mockLine2')}</div>
                  </div>
                )}
                {key === 'risk' && (
                  <table className="framer-table-mock">
                    <thead>
                      <tr>
                        <th>{t('framer.agents.table.event')}</th>
                        <th>{t('framer.agents.table.status')}</th>
                        <th>{t('framer.agents.table.latency')}</th>
                      </tr>
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
                  <div className="framer-mock-settle">
                    <div className="framer-metric-row">
                      <div><strong>58%</strong><span>{t('framer.agents.items.settle.winRate')}</span></div>
                      <div><strong>&lt;1s</strong><span>{t('framer.agents.items.settle.latency')}</span></div>
                      <div><strong>7/10d</strong><span>{t('framer.agents.items.settle.cycle')}</span></div>
                    </div>
                    <p>{t('framer.agents.items.settle.note')}</p>
                  </div>
                )}
                {key === 'strategy' && (
                  <div className="framer-mock-code">
                    <div className="framer-code-line"><span className="c-dim">#</span> {t('framer.agents.items.strategy.codeComment')}</div>
                    <div className="framer-code-line"><span className="c-key">regime</span> = <span className="c-str">&quot;trend&quot;</span></div>
                    <div className="framer-code-line"><span className="c-key">atr_mult</span> = <span className="c-num">2.4</span></div>
                    <div className="framer-code-line"><span className="c-key">supervisor</span>.<span className="c-fn">deploy</span>(<span className="c-str">&quot;ETHUSDT&quot;</span>)</div>
                    <div className="framer-code-line framer-mock-success">{t('framer.agents.items.strategy.codeResult')}</div>
                  </div>
                )}
              </div>
            </div>
          </ScrollReveal>
        ))}
      </section>

      <ScrollReveal>
        <section className="framer-agent-block framer-connect-block">
          <div className="framer-agent-copy">
            <p className="framer-kicker">{t('framer.api.kicker')}</p>
            <h3>{t('framer.api.title')}</h3>
            <p>{t('framer.api.desc')}</p>
            <Link to="/register" className="framer-btn-primary" style={{ marginTop: 8 }}>
              {t('framer.api.cta')} <ArrowRight size={16} />
            </Link>
          </div>
          <div className="framer-mock-ui framer-terminal-dark framer-mock-hover">
            <div className="framer-terminal-line dim">$ bind-binance-api --futures-only --no-withdraw</div>
            <div className="framer-terminal-line ok">✓ Connection verified</div>
            <div className="framer-terminal-line ok">✓ One-way mode OK · Leverage 15x</div>
            <div className="framer-terminal-line ok">✓ Supervisor loaded · Sentinel 6s</div>
            <div className="framer-terminal-line dim">{t('framer.api.terminalNote')}</div>
          </div>
        </section>
      </ScrollReveal>

      <section id="platform" className="framer-section framer-platform-section">
        <ScrollReveal>
          <div className="framer-section-head">
            <h2>{t('framer.platform.title')}</h2>
          </div>
        </ScrollReveal>
        <FramerPlatformBento />
      </section>

      <FramerCommunitySection />

      <section id="partners" className="framer-section framer-trusted">
        <ScrollReveal>
          <div className="framer-section-head">
            <p className="framer-kicker">{t('framer.partners.kicker')}</p>
            <h2>{t('framer.partners.title')}</h2>
            <p>{t('framer.partners.subtitle')}</p>
            <Link to="/help" className="framer-inline-link">{t('framer.partners.cta')}</Link>
          </div>
        </ScrollReveal>
        <ScrollReveal delay={0.1} y={28}>
          <FramerPartnerLogos />
        </ScrollReveal>
        <ScrollReveal delay={0.16}>
          <div className="framer-countries">
            {(['sg', 'hk', 'ae', 'jp', 'uk', 'us', 'de', 'au'] as const).map(c => (
              <span key={c} className="framer-country-pill">{t(`framer.partners.countries.${c}`)}</span>
            ))}
          </div>
        </ScrollReveal>
        <FramerCustomerStories />
      </section>

      <ScrollReveal y={48}>
        <section id="security" className="framer-agent-block reverse framer-security-block">
          <div className="framer-agent-copy">
            <p className="framer-kicker">{t('framer.security.kicker')}</p>
            <h3>{t('framer.security.title')}</h3>
            <p>{t('framer.security.desc')}</p>
          </div>
          <div className="framer-mock-ui framer-security-list framer-mock-hover">
            <ul>
              {(['api', 'dual', 'audit', 'nocustody'] as const).map(k => (
                <li key={k}>
                  <strong>{t(`framer.security.points.${k}.title`)}</strong>
                  <p>{t(`framer.security.points.${k}.desc`)}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </ScrollReveal>

      <ScrollReveal blur={4}>
        <section className="framer-cta-final">
          <p className="framer-kicker">{t('framer.final.kicker')}</p>
          <h2>{t('framer.final.title')}</h2>
          <p className="framer-cta-final-sub">{t('framer.final.subtitle')}</p>
          <Link to={token ? '/dashboard' : '/register'} className="framer-btn-primary framer-btn-glow">
            {t('framer.final.cta')}
          </Link>
        </section>
      </ScrollReveal>

      <footer className="framer-footer">
        <div className="framer-footer-inner">
          <div className="framer-footer-grid">
            <div>
              <div className="framer-logo" style={{ marginBottom: 12 }}>
                <FramerBrand to={undefined} />
              </div>
              <p className="framer-footer-tagline">{t('framer.footer.tagline')}</p>
            </div>
            <div>
              <h5>{t('framer.footer.product')}</h5>
              <a href="#product" onClick={e => { e.preventDefault(); scrollTo('product') }}>{t('framer.nav.product')}</a>
              <Link to="/help">{t('nav.help')}</Link>
              <Link to="/register">{t('auth.register')}</Link>
            </div>
            <div>
              <h5>{t('framer.footer.company')}</h5>
              <a href="#community" onClick={e => { e.preventDefault(); scrollTo('community') }}>{t('framer.nav.community')}</a>
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
