import { Link, useNavigate } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useAuth } from '../../../store/auth'
import { useI18n } from '../../../i18n'
import { useTheme } from '../../../store/theme'
import FramerBrand from '../../FramerBrand'
import TopToolbar from '../../TopToolbar'
import ScrollReveal from '../../ui/ScrollReveal'
import FramerSiteEffects from './FramerSiteEffects'
import FramerHeroPipeline from './FramerHeroPipeline'
import FramerCryptoTicker from './FramerCryptoTicker'
import FramerIndicatorShowcase from './FramerIndicatorShowcase'
import FramerShowcaseMarquee from './FramerShowcaseMarquee'
import FramerAgentsSection from './FramerAgentsSection'
import FramerDecisionGrid from './FramerDecisionGrid'
import FramerPlatformSuite from './FramerPlatformSuite'
import FramerLayerFlow from './FramerLayerFlow'
import FramerWorkflowStrip from './FramerWorkflowStrip'
import FramerWhyAI from './FramerWhyAI'
import FramerRiskManagement from './FramerRiskManagement'
import FramerExchangePartners from './FramerExchangePartners'
import FramerStatsBand from './FramerStatsBand'
import FramerLandingFAQ from './FramerLandingFAQ'
import FramerGlobe3D from './FramerGlobe3D'

const NAV_IDS = ['indicators', 'showcase', 'agents', 'think', 'platform', 'workflow', 'partners', 'stats', 'faq'] as const

const SECTION_MAP: Record<string, string> = {
  indicators: 'indicators',
  showcase: 'showcase',
  agents: 'agents',
  think: 'engine',
  platform: 'platform',
  workflow: 'workflow',
  partners: 'partners',
  stats: 'stats',
  faq: 'faq',
}

export default function FramerLandingPage() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const { theme } = useTheme()
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
    document.getElementById(SECTION_MAP[id] || id)?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className="framer-site" key={`${locale}-${theme}`}>
      <FramerSiteEffects />
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
            <div className="framer-nav-toolbar">
              <TopToolbar />
            </div>
            {token ? (
              <button type="button" className="framer-btn-primary framer-btn-white" onClick={() => navigate('/dashboard')}>
                {t('framer.nav.console')}
              </button>
            ) : (
              <>
                <Link to="/login" className="framer-btn-ghost">{t('auth.login')}</Link>
                <Link to="/register" className="framer-btn-primary framer-btn-white">{t('framer.nav.signup')}</Link>
              </>
            )}
            <button type="button" className="framer-menu-btn" onClick={() => setMenuOpen(v => !v)} aria-label="Menu">
              {menuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
      </header>

      <FramerCryptoTicker />

      <FramerHeroPipeline />

      <ScrollReveal y={40}><FramerIndicatorShowcase /></ScrollReveal>
      <FramerShowcaseMarquee />
      <ScrollReveal y={40}><FramerAgentsSection /></ScrollReveal>
      <ScrollReveal y={40}><FramerDecisionGrid /></ScrollReveal>
      <ScrollReveal y={40}><FramerPlatformSuite /></ScrollReveal>
      <ScrollReveal y={40}><FramerLayerFlow /></ScrollReveal>
      <ScrollReveal y={32}><FramerWorkflowStrip /></ScrollReveal>
      <ScrollReveal y={40}><FramerWhyAI /></ScrollReveal>
      <ScrollReveal y={40}><FramerRiskManagement /></ScrollReveal>
      <ScrollReveal y={40}><FramerExchangePartners /></ScrollReveal>
      <FramerStatsBand />
      <ScrollReveal y={32}><FramerLandingFAQ /></ScrollReveal>

      <ScrollReveal blur={4}>
        <section className="framer-cta-final">
          <p className="framer-kicker">{t('framer.final.kicker')}</p>
          <h2>{t('framer.final.title')}</h2>
          <p className="framer-cta-final-sub">{t('framer.final.subtitle')}</p>
          <Link to={token ? '/dashboard' : '/register'} className="framer-btn-primary framer-btn-white framer-btn-glow">
            {t('framer.final.cta')}
          </Link>
        </section>
      </ScrollReveal>

      <ScrollReveal y={32}><FramerGlobe3D /></ScrollReveal>

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
              <h5>{t('framer.footer.legal')}</h5>
              <Link to="/help">{t('framer.footer.docs')}</Link>
              <Link to="/privacy">{t('framer.footer.privacy')}</Link>
              <Link to="/terms">{t('framer.footer.terms')}</Link>
            </div>
            <div>
              <h5>{t('framer.footer.product')}</h5>
              <a href="#indicators" onClick={e => { e.preventDefault(); scrollTo('indicators') }}>{t('framer.nav.indicators')}</a>
              <a href="#platform" onClick={e => { e.preventDefault(); scrollTo('platform') }}>{t('framer.nav.platform')}</a>
              <a href="#workflow" onClick={e => { e.preventDefault(); scrollTo('workflow') }}>{t('framer.nav.workflow')}</a>
              <Link to="/login">{t('auth.login')}</Link>
              <Link to="/register">{t('framer.nav.signup')}</Link>
            </div>
            <div>
              <h5>{t('framer.footer.company')}</h5>
              <a href="#partners" onClick={e => { e.preventDefault(); scrollTo('partners') }}>{t('framer.nav.partners')}</a>
              <a href="#faq" onClick={e => { e.preventDefault(); scrollTo('faq') }}>{t('framer.nav.faq')}</a>
              <Link to="/help">{t('framer.footer.docs')}</Link>
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
