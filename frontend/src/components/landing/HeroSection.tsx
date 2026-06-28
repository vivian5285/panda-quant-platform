import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Play, Sparkles, TrendingUp } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useAuth } from '../../store/auth'
import ParticleBackground from '../ui/ParticleBackground'

export default function HeroSection() {
  const t = useI18n(s => s.t)
  const token = useAuth(s => s.token)

  return (
    <section className="saas-hero cyber-hero">
      <ParticleBackground />
      <div className="cyber-grid-bg" aria-hidden />
      <div className="cyber-scanline" aria-hidden />

      <div className="saas-hero-inner">
        <motion.div
          className="saas-hero-copy"
          initial={{ opacity: 0, x: -30 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.7 }}
        >
          <div className="landing-badge saas-badge cyber-badge">
            <Sparkles size={14} />
            <span>{t('hero.badge')}</span>
          </div>

          <h1 className="saas-hero-title cyber-title">
            <span className="cyber-title-main">{t('hero.titleMain')}</span>
            <span className="saas-gradient-text cyber-glow-text">{t('hero.titleHighlight')}</span>
          </h1>

          <p className="saas-hero-sub">{t('hero.subtitle')}</p>

          <div className="landing-hero-actions">
            <Link to={token ? '/dashboard' : '/register'} className="btn btn-primary landing-hero-btn cyber-cta">
              {token ? t('landing.nav.console') : t('hero.ctaPrimary')}
            </Link>
            <button
              type="button"
              className="btn btn-secondary landing-hero-btn cyber-cta-secondary"
              onClick={() => document.getElementById('markets')?.scrollIntoView({ behavior: 'smooth' })}
            >
              <Play size={16} /> {t('hero.ctaSecondary')}
            </button>
          </div>

          <div className="hero-trust-row">
            {(['api', 'tv', 'settle'] as const).map(k => (
              <span key={k}><TrendingUp size={14} /> {t(`hero.trust.${k}`)}</span>
            ))}
          </div>
        </motion.div>

        <motion.div
          className="saas-hero-globe cyber-orb"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8, delay: 0.15 }}
        >
          <div className="globe-ring globe-ring-1" />
          <div className="globe-ring globe-ring-2" />
          <div className="globe-ring globe-ring-3" />
          <div className="globe-core cyber-core">
            <span>🐼</span>
            <div className="globe-orbit"><i /></div>
            <div className="globe-orbit globe-orbit-2"><i /></div>
          </div>
          <div className="globe-node globe-node-1">BTC</div>
          <div className="globe-node globe-node-2 gold">ETH</div>
          <div className="globe-node globe-node-3">AI</div>
          <div className="globe-beam" />
        </motion.div>
      </div>
    </section>
  )
}
