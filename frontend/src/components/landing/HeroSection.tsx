import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Sparkles } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useAuth } from '../../store/auth'

export default function HeroSection() {
  const t = useI18n(s => s.t)
  const token = useAuth(s => s.token)

  return (
    <section className="premium-hero">
      <div className="premium-hero-glow" aria-hidden />
      <div className="premium-hero-inner">
        <motion.div
          className="premium-hero-copy"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65 }}
        >
          <div className="landing-badge premium-badge">
            <Sparkles size={14} />
            <span>{t('landing.hero.badge')}</span>
          </div>

          <h1 className="premium-hero-title display-font">
            {t('landing.hero.titleLine1')}
            <span className="premium-gradient-text">{t('landing.hero.titleHighlight')}</span>
            {t('landing.hero.titleLine2')}
          </h1>

          <p className="premium-hero-sub">{t('landing.hero.subtitle')}</p>

          <div className="landing-hero-actions">
            <Link to={token ? '/dashboard' : '/register'} className="btn btn-primary landing-hero-btn ripple-btn">
              {token ? t('landing.nav.console') : t('landing.hero.ctaPrimary')}
              <ArrowRight size={16} />
            </Link>
            <button
              type="button"
              className="btn btn-secondary landing-hero-btn"
              onClick={() => document.getElementById('showcase')?.scrollIntoView({ behavior: 'smooth' })}
            >
              {t('landing.hero.ctaSecondary')}
            </button>
          </div>

          <div className="premium-hero-stats">
            {(['uptime', 'pairs', 'latency', 'cycles'] as const).map(k => (
              <div key={k} className="premium-stat-pill">
                <strong>{t(`landing.hero.stats.${k}.value`)}</strong>
                <span>{t(`landing.hero.stats.${k}.label`)}</span>
              </div>
            ))}
          </div>
        </motion.div>

        <motion.div
          className="premium-hero-panel"
          initial={{ opacity: 0, y: 32 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.12 }}
        >
          <div className="ai-workspace-mock glass">
            <div className="ai-workspace-bar">
              <span /><span /><span />
              <em>{t('landing.hero.terminalTitle')}</em>
            </div>
            <div className="ai-workspace-body">
              <div className="ai-chat ai-chat-user">
                <p>{t('landing.agents.prompt')}</p>
              </div>
              <div className="ai-chat ai-chat-agent">
                <span className="ai-agent-label">{t('landing.hero.live')}</span>
                <p>{t('landing.agents.reply')}</p>
                <ul>
                  {(['a', 'b', 'c'] as const).map(k => (
                    <li key={k}>{t(`landing.agents.replyItems.${k}`)}</li>
                  ))}
                </ul>
              </div>
              <div className="ai-workspace-metrics">
                {(['regime', 'pnl', 'supervisor'] as const).map(k => (
                  <div key={k} className="ai-metric">
                    <span>{t(`landing.agents.metrics.${k}.label`)}</span>
                    <strong>{t(`landing.agents.metrics.${k}.value`)}</strong>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
