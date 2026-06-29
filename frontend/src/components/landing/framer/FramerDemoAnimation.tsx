import { useEffect, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const PHASES = ['prompt', 'analyze', 'score', 'risk', 'execute', 'done'] as const

export default function FramerDemoAnimation() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    if (reduceMotion) return
    const timer = setInterval(() => setPhase(p => (p + 1) % PHASES.length), 2200)
    return () => clearInterval(timer)
  }, [reduceMotion])

  const cur = PHASES[phase]

  return (
    <div className="framer-demo-animation">
      <div className="framer-demo-animation-grid" aria-hidden />
      <div className="framer-demo-agent-head">
        <div className="framer-demo-agent-orb">
          <span className="framer-demo-agent-core" />
        </div>
        <div>
          <strong>GEMINI AI Agent</strong>
          <span>{t('framer.hero.demo.agentModel')}</span>
        </div>
        <span className="framer-demo-agent-live">{t('framer.hero.recording.live')}</span>
      </div>

      <div className="framer-demo-chat">
        <AnimatePresence mode="wait">
          <motion.div
            key={cur}
            className="framer-demo-chat-line"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.35 }}
          >
            {cur === 'prompt' && (
              <div className="framer-demo-bubble user">{t('framer.hero.demo.prompt')}</div>
            )}
            {cur === 'analyze' && (
              <div className="framer-demo-bubble thinking">
                <span className="framer-agent-dot" />
                {t('framer.hero.demo.analyzing')}
              </div>
            )}
            {(cur === 'score' || cur === 'risk' || cur === 'execute' || cur === 'done') && (
              <div className="framer-demo-metrics">
                <div className={`framer-demo-metric${cur === 'score' ? ' lit' : ''}`}>
                  <small>Trend</small><strong>Long</strong>
                </div>
                <div className={`framer-demo-metric${cur === 'score' ? ' lit' : ''}`}>
                  <small>Confidence</small><strong>92%</strong>
                </div>
                <div className={`framer-demo-metric${cur === 'risk' ? ' lit' : ''}`}>
                  <small>Risk</small><strong>Pass</strong>
                </div>
                <div className={`framer-demo-metric${cur === 'execute' || cur === 'done' ? ' lit' : ''}`}>
                  <small>Execute</small><strong>ETH</strong>
                </div>
              </div>
            )}
            {cur === 'done' && (
              <div className="framer-demo-bubble success">{t('framer.hero.demo.done')}</div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="framer-demo-pipeline-rail">
        {PHASES.slice(1, 5).map((p, i) => (
          <span
            key={p}
            className={`framer-demo-pipeline-dot${phase >= i + 1 ? ' lit' : ''}${phase === i + 1 ? ' active' : ''}`}
          />
        ))}
      </div>
    </div>
  )
}
