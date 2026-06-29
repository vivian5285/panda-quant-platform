import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'
import { useAuth } from '../../../store/auth'

const EXPLORE = ['desktop', 'tablet', 'agent'] as const
const FEATURES = ['signal', 'execution', 'connect'] as const

export default function FramerAgentsSection() {
  const t = useI18n(s => s.t)
  const token = useAuth(s => s.token)
  const reduceMotion = useReducedMotion()
  const [panel, setPanel] = useState(0)
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    if (reduceMotion) return
    const p = setInterval(() => setPanel(i => (i + 1) % EXPLORE.length), 4500)
    return () => clearInterval(p)
  }, [reduceMotion])

  useEffect(() => {
    if (reduceMotion) return
    setPhase(0)
    const steps = [600, 2000, 3500, 5000]
    const timers = steps.map((ms, i) => setTimeout(() => setPhase(i + 1), ms))
    const loop = setInterval(() => {
      setPhase(0)
      steps.forEach((ms, i) => setTimeout(() => setPhase(i + 1), ms))
    }, 6500)
    return () => {
      timers.forEach(clearTimeout)
      clearInterval(loop)
    }
  }, [reduceMotion, panel])

  return (
    <section id="agents" className="framer-section framer-agents-framer">
      <div className="framer-agents-top-row">
        <div>
          <p className="framer-kicker">{t('framer.agents.kicker')}</p>
          <h2>{t('framer.agents.title')}</h2>
        </div>
        <Link to={token ? '/dashboard' : '/register'} className="framer-btn-secondary framer-agents-top-cta">
          {t('framer.agents.ctaStart')}
        </Link>
      </div>

      <div className="framer-agents-explore-wrap glass">
        <div className="framer-agents-explore-main">
          <div className="framer-agents-explore-tabs">
            {EXPLORE.map((key, i) => (
              <button
                key={key}
                type="button"
                className={`framer-agents-explore-tab${panel === i ? ' active' : ''}`}
                onClick={() => setPanel(i)}
              >
                {t(`framer.agents.explore.${key}`)}
              </button>
            ))}
          </div>
          <div className="framer-agents-explore-panels">
            {EXPLORE.map((key, i) => (
              <motion.div
                key={key}
                className={`framer-agents-explore-panel framer-agents-explore-${key}`}
                animate={{ opacity: panel === i ? 1 : 0, scale: panel === i ? 1 : 0.96 }}
                transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
                style={{ pointerEvents: panel === i ? 'auto' : 'none', position: panel === i ? 'relative' : 'absolute', inset: panel === i ? undefined : 0 }}
              >
                <div className="framer-agents-explore-label">{t(`framer.agents.explore.${key}`)}</div>
                <div className="framer-agents-explore-content">
                  {key === 'desktop' && (
                    <>
                      <div className="framer-agents-mock-title">{t('framer.agents.explore.desktopTitle')}</div>
                      <div className="framer-agents-mock-sub">{t('framer.agents.explore.desktopSub')}</div>
                    </>
                  )}
                  {key === 'tablet' && (
                    <div className="framer-agents-mock-chart">
                      {[72, 58, 85, 64, 91, 78].map((h, j) => (
                        <span key={j} style={{ height: `${h}%` }} />
                      ))}
                    </div>
                  )}
                  {key === 'agent' && (
                    <div className="framer-agents-mock-agent-preview">
                      <span>GEMINI AI</span>
                      <p>{t('framer.agents.signal.reply')}</p>
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        <aside className="framer-agents-sidebar">
          <div className="framer-agents-sidebar-head">
            <span className="framer-agents-sidebar-icon" />
            <span>{t('framer.agents.sidebar.title')}</span>
          </div>
          <div className="framer-agent-chat framer-agents-sidebar-chat">
            {phase >= 1 && (
              <div className="framer-agent-user framer-rec-fade-in">{t('framer.agents.sidebar.prompt')}</div>
            )}
            {phase >= 2 && (
              <div className="framer-agent-thinking framer-rec-fade-in">
                <span className="framer-agent-dot" />
                {t('framer.agents.sidebar.thinking')}
              </div>
            )}
            {phase >= 3 && (
              <div className="framer-agents-sidebar-step framer-rec-fade-in">
                <span className="framer-agents-sidebar-link" />
                {t('framer.agents.sidebar.plan')}
                <small>2s</small>
              </div>
            )}
            {phase >= 4 && (
              <div className="framer-agent-reply framer-rec-fade-in">{t('framer.agents.sidebar.done')}</div>
            )}
          </div>
          <div className="framer-agents-sidebar-foot">
            <span>GEMINI · v3</span>
          </div>
        </aside>
      </div>

      <div className="framer-agents-features">
        {FEATURES.map(key => (
          <article key={key} className="framer-agents-feature glass">
            <div className={`framer-agents-feature-mock framer-agents-feature-mock-${key}`}>
              {key === 'signal' && (
                <div className="framer-agent-panel">
                  <div className="framer-agent-panel-head">
                    <span>GEMINI AI</span>
                    <span className="framer-agent-model">{t('framer.agents.signal.title')}</span>
                  </div>
                  <div className="framer-agent-chat">
                    <div className="framer-agent-user">{t('framer.agents.signal.prompt')}</div>
                    <div className="framer-agent-reply">{t('framer.agents.signal.reply')}</div>
                  </div>
                </div>
              )}
              {key === 'execution' && (
                <table className="framer-mock-cms">
                  <thead>
                    <tr>
                      <th>{t('framer.agents.cms.symbol')}</th>
                      <th>{t('framer.agents.cms.bias')}</th>
                      <th>{t('framer.agents.cms.conf')}</th>
                      <th>{t('framer.agents.cms.status')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr><td>ETHUSDT</td><td>Long</td><td>92%</td><td className="live">Live</td></tr>
                    <tr><td>BTCUSDT</td><td>Long</td><td>87%</td><td className="live">Live</td></tr>
                    <tr><td>SOLUSDT</td><td>—</td><td>41%</td><td className="draft">Skip</td></tr>
                  </tbody>
                </table>
              )}
              {key === 'connect' && (
                <div className="framer-mock-terminal">
                  <div className="framer-mock-terminal-head">GEMINI AI · Exchange Router</div>
                  <div className="framer-terminal-line ok">Binance · connected · 12ms</div>
                  <div className="framer-terminal-line ok">OKX · connected · 18ms</div>
                  <div className="framer-terminal-line dim">Bybit · routing standby</div>
                  <div className="framer-terminal-line ok">Order routed · ETHUSDT Long · 0.42</div>
                </div>
              )}
            </div>
            <div className="framer-agents-feature-copy">
              <h3>{t(`framer.agents.${key}.title`)}</h3>
              <p>{t(`framer.agents.${key}.desc`)}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
