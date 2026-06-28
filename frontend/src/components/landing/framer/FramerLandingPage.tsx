import { Link, useNavigate } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useAuth } from '../../../store/auth'
import { useI18n } from '../../../i18n'
import FramerBrand from '../../FramerBrand'
import ScrollReveal from '../../ui/ScrollReveal'
import FramerHeroPipeline from './FramerHeroPipeline'
import FramerDecisionGrid from './FramerDecisionGrid'
import FramerLayerFlow from './FramerLayerFlow'
import FramerModelsGrid from './FramerModelsGrid'
import FramerWorkflowStrip from './FramerWorkflowStrip'
import FramerDashboardProof from './FramerDashboardProof'
import FramerWhyAI from './FramerWhyAI'
import FramerRiskManagement from './FramerRiskManagement'
import FramerTechArchitecture from './FramerTechArchitecture'
import FramerLandingFAQ from './FramerLandingFAQ'

const NAV_IDS = ['engine', 'layers', 'models', 'workflow', 'dashboard', 'risk', 'tech', 'faq'] as const

export default function FramerLandingPage() {
  const t = useI18n(s => s.t)
  const locale = useI18n(s => s.locale)
  const setLocale = useI18n(s => s.setLocale)
  const token = useAuth(s => s.token)
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [navScrolled, setNavScrolled] = useState(false)

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

  return (
    <div className="framer-site">
      <header className={`framer-nav${navScrolled ? ' framer-nav-scrolled' : ''}`}>
        <div className="framer-nav-inner">
          <FramerBrand />
          <nav className={`framer-nav-links ${menuOpen ? 'open' : ''}`}>
            {NAV_IDS.map(id => (
              <button key={id} type="button" onClick={() => scrollTo(id)}>
                {t(`framer.nav.${id}`)}
              </button>
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

      <FramerHeroPipeline />

      <ScrollReveal>
        <blockquote className="framer-narrative">{t('framer.narrative.core')}</blockquote>
      </ScrollReveal>

      <ScrollReveal y={40}>
        <FramerDecisionGrid />
      </ScrollReveal>

      <ScrollReveal y={40}>
        <FramerLayerFlow />
      </ScrollReveal>

      <ScrollReveal y={40}>
        <FramerModelsGrid />
      </ScrollReveal>

      <ScrollReveal y={32}>
        <FramerWorkflowStrip />
      </ScrollReveal>

      <ScrollReveal y={48}>
        <FramerDashboardProof />
      </ScrollReveal>

      <ScrollReveal y={40}>
        <FramerWhyAI />
      </ScrollReveal>

      <ScrollReveal y={40}>
        <FramerRiskManagement />
      </ScrollReveal>

      <ScrollReveal y={40}>
        <FramerTechArchitecture />
      </ScrollReveal>

      <ScrollReveal y={32}>
        <FramerLandingFAQ />
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
              <a href="#engine" onClick={e => { e.preventDefault(); scrollTo('engine') }}>{t('framer.nav.engine')}</a>
              <a href="#models" onClick={e => { e.preventDefault(); scrollTo('models') }}>{t('framer.nav.models')}</a>
              <a href="#dashboard" onClick={e => { e.preventDefault(); scrollTo('dashboard') }}>{t('framer.nav.dashboard')}</a>
            </div>
            <div>
              <h5>{t('framer.footer.company')}</h5>
              <a href="#risk" onClick={e => { e.preventDefault(); scrollTo('risk') }}>{t('framer.nav.risk')}</a>
              <a href="#tech" onClick={e => { e.preventDefault(); scrollTo('tech') }}>{t('framer.nav.tech')}</a>
              <Link to="/help">{t('nav.help')}</Link>
            </div>
            <div>
              <h5>{t('framer.footer.legal')}</h5>
              <Link to="/privacy">{t('saas.footer.privacy')}</Link>
              <Link to="/terms">{t('saas.footer.terms')}</Link>
            </div>
            <div>
              <h5>{t('framer.footer.connect')}</h5>
              <Link to="/login">{t('auth.login')}</Link>
              <Link to="/register">{t('framer.nav.signup')}</Link>
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
