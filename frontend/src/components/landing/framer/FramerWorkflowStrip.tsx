import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useI18n } from '../../../i18n'
import { useTheme } from '../../../store/theme'
import { accentCardGradient } from '../../../utils/framerThemeGradients'

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

const STEP_ACCENTS = [
  '#007aff',
  '#5856d6',
  '#00c7be',
  '#ff9f0a',
  '#ff375f',
  '#32d74b',
  '#64d2ff',
  '#bf5af2',
  '#ffd60a',
] as const

export default function FramerWorkflowStrip() {
  const t = useI18n(s => s.t)
  const { theme } = useTheme()
  const stepBgs = useMemo(
    () => STEP_ACCENTS.map(c => accentCardGradient(c, theme)),
    [theme],
  )
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
            <div
              className={`framer-workflow-node glass framer-glass-cell framer-color-card${i <= active ? ' lit' : ''}${i === active ? ' active' : ''}`}
              style={{
                '--card-bg': stepBgs[i],
                '--card-accent': STEP_ACCENTS[i],
              } as CSSProperties}
            >
              <span className="framer-workflow-index">{i + 1}</span>
              <span>{t(`framer.workflow.steps.${step}`)}</span>
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={`framer-workflow-line${i < active ? ' lit' : ''}`}
                style={i < active ? {
                  '--line-from': STEP_ACCENTS[i],
                  '--line-to': STEP_ACCENTS[i + 1],
                } as CSSProperties : undefined}
                aria-hidden
              />
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
