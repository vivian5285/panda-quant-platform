import { useEffect, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const STEPS = [
  'trend',
  'structure',
  'liquidity',
  'volatility',
  'probability',
  'decision',
  'execute',
] as const

export default function FramerAiDecisionPipeline() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const [active, setActive] = useState(0)

  useEffect(() => {
    if (reduceMotion) return
    const timer = setInterval(() => setActive(i => (i + 1) % STEPS.length), 1400)
    return () => clearInterval(timer)
  }, [reduceMotion])

  return (
    <div className="framer-ai-pipeline-wrap">
      <div className="framer-ai-pipeline-card glass">
        <div className="framer-ai-pipeline-head">
          <span className="framer-ai-pulse" aria-hidden />
          {t('framer.hero.pipeline.live')}
          <span className="framer-pipe-symbol">{t('framer.hero.pipeline.symbol')}</span>
        </div>
        <div className="framer-ai-pipeline">
          {STEPS.map((step, i) => (
            <div key={step} className="framer-pipe-segment">
              <div
                className={[
                  'framer-pipe-node',
                  i <= active ? 'lit' : '',
                  i === active ? 'active' : '',
                ].filter(Boolean).join(' ')}
              >
                <span className="framer-pipe-label">{t(`framer.hero.pipeline.${step}`)}</span>
                {step === 'decision' && i === active && (
                  <span className="framer-pipe-badge">92%</span>
                )}
                {step === 'execute' && i === active && (
                  <span className="framer-pipe-badge framer-pipe-badge-long">LONG</span>
                )}
              </div>
              {i < STEPS.length - 1 && (
                <div className={`framer-pipe-arrow${i < active ? ' lit' : ''}`} aria-hidden>↓</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
