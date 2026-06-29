import { motion, useReducedMotion } from 'framer-motion'
import { Activity, BarChart3, Shield, Zap } from 'lucide-react'
import { useI18n } from '../i18n'
import FramerBrand from './FramerBrand'

const CHIPS = [
  { icon: Zap, key: 'latency' as const },
  { icon: Shield, key: 'security' as const },
  { icon: BarChart3, key: 'analytics' as const },
  { icon: Activity, key: 'uptime' as const },
]

export default function AuthVisualPanel() {
  const t = useI18n(s => s.t)
  const reduce = useReducedMotion()

  return (
    <div className="auth-visual">
      <div className="auth-visual-bg">
        <div className="auth-visual-grid" />
        <div className="auth-visual-orb auth-visual-orb-a" />
        <div className="auth-visual-orb auth-visual-orb-b" />
        <div className="auth-visual-orb auth-visual-orb-c" />
      </div>
      <div className="auth-visual-content">
        <FramerBrand showTagline />
        <h1>
          <span>{t('framer.hero.titleLine1')}</span>
          <span className="auth-visual-accent">{t('framer.hero.titleLine2')}</span>
        </h1>
        <p>{t('framer.hero.subtitle')}</p>
        <div className="auth-visual-chips">
          {CHIPS.map(({ icon: Icon, key }, i) => (
            <motion.div
              key={key}
              className="auth-visual-chip"
              initial={reduce ? false : { opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 + i * 0.08, duration: 0.5 }}
            >
              <Icon size={16} strokeWidth={1.75} />
              <div>
                <strong>{t(`auth.visual.${key}.title`)}</strong>
                <span>{t(`auth.visual.${key}.desc`)}</span>
              </div>
            </motion.div>
          ))}
        </div>
        <div className="auth-visual-mock">
          <div className="auth-visual-mock-bar">
            <span /><span /><span />
            <small>GEMINI AI · Dashboard</small>
          </div>
          <div className="auth-visual-mock-body">
            <div className="auth-visual-spark" />
            <div className="auth-visual-metrics">
              <div><small>Balance</small><strong>$12,480</strong></div>
              <div><small>Today PNL</small><strong className="text-green">+$342</strong></div>
              <div><small>Win Rate</small><strong>58.2%</strong></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
