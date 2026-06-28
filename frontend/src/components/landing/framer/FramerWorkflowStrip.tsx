import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n'

const STEPS = [
  'marketData',
  'featureExtraction',
  'patternRecognition',
  'confidenceScore',
  'riskEngine',
  'positionSizing',
  'execution',
  'riskMonitoring',
  'exitOptimization',
] as const

export default function FramerWorkflowStrip() {
  const t = useI18n(s => s.t)
  const [active, setActive] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => setActive(i => (i + 1) % STEPS.length), 1200)
    return () => clearInterval(timer)
  }, [])

  return (
    <section id="workflow" className="framer-section framer-workflow-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.workflow.kicker')}</p>
        <h2>{t('framer.workflow.title')}</h2>
      </div>
      <div className="framer-workflow-strip">
        {STEPS.map((step, i) => (
          <div key={step} className="framer-workflow-item">
            <div className={`framer-workflow-node${i <= active ? ' lit' : ''}${i === active ? ' active' : ''}`}>
              <span className="framer-workflow-index">{i + 1}</span>
              <span>{t(`framer.workflow.steps.${step}`)}</span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`framer-workflow-line${i < active ? ' lit' : ''}`} aria-hidden />
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
