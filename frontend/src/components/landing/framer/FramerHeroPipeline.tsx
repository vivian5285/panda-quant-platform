import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'
import { useAuth } from '../../../store/auth'
import FramerHeroBackdrop from './FramerHeroBackdrop'

const PIPELINE = [
  'symbol',
  'trend',
  'momentum',
  'liquidity',
  'structure',
  'volatility',
  'probability',
  'decision',
  'execute',
] as const

const heroEase = [0.22, 1, 0.36, 1] as const

export default function FramerHeroPipeline() {
  const t = useI18n(s => s.t)
  const token = useAuth(s => s.token)
  const reduceMotion = useReducedMotion()
  const [active, setActive] = useState(0)

  useEffect(() => {
    if (reduceMotion) return
    const timer = setInterval(() => setActive(i => (i + 1) % PIPELINE.length), 850)
    return () => clearInterval(timer)
  }, [reduceMotion])

  const item = (delay: number) =>
    reduceMotion
      ? {}
      : {
          initial: { opacity: 0, y: 28 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.65, delay, ease: heroEase },
        }

  return (
    <div className="framer-hero-zone">
      <FramerHeroBackdrop />
      <section className="framer-hero-split">
        <div className="framer-hero-copy">
          <motion.div className="framer-pill framer-pill-shimmer" {...item(0.05)}>
            {t('framer.hero.pill')}
          </motion.div>
          <motion.h1 {...item(0.12)}>{t('framer.hero.title')}</motion.h1>
          <motion.p className="framer-hero-sub framer-hero-sub-left" {...item(0.2)}>
            {t('framer.hero.subtitle')}
          </motion.p>
          <motion.div className="framer-hero-cta framer-hero-cta-left" {...item(0.28)}>
            <Link to={token ? '/dashboard' : '/register'} className="framer-btn-primary">
              {t('framer.hero.ctaPrimary')}
            </Link>
            <Link to="#dashboard" className="framer-btn-secondary" onClick={e => {
              e.preventDefault()
              document.getElementById('dashboard')?.scrollIntoView({ behavior: 'smooth' })
            }}>
              {t('framer.hero.ctaSecondary')}
            </Link>
          </motion.div>
        </div>

        <motion.div className="framer-ai-pipeline-wrap" {...item(0.35)}>
          <div className="framer-ai-pipeline-card">
            <div className="framer-ai-pipeline-head">
              <span className="framer-ai-pulse" />
              {t('framer.hero.pipeline.live')}
            </div>
            <div className="framer-ai-pipeline">
              {PIPELINE.map((step, i) => (
                <div key={step} className="framer-pipe-segment">
                  <div
                    className={`framer-pipe-node${i <= active ? ' lit' : ''}${i === active ? ' active' : ''}`}
                  >
                    <span className="framer-pipe-label">{t(`framer.hero.pipeline.${step}`)}</span>
                    {step === 'probability' && i <= active && (
                      <span className="framer-pipe-badge">92%</span>
                    )}
                    {step === 'decision' && i <= active && (
                      <span className="framer-pipe-badge framer-pipe-badge-long">Long Bias</span>
                    )}
                  </div>
                  {i < PIPELINE.length - 1 && (
                    <div className={`framer-pipe-arrow${i < active ? ' lit' : ''}`} aria-hidden>↓</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      </section>
    </div>
  )
}
