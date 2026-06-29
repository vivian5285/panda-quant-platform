import { useEffect, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const LAYERS = [
  'trendIntel',
  'momentumIntel',
  'structureIntel',
  'liquidityIntel',
  'volatilityIntel',
  'probability',
  'riskEngine',
  'execution',
] as const

export default function FramerLayerFlow() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const [active, setActive] = useState(0)

  useEffect(() => {
    if (reduceMotion) return
    const timer = setInterval(() => setActive(i => (i + 1) % LAYERS.length), 1600)
    return () => clearInterval(timer)
  }, [reduceMotion])

  return (
    <section id="layers" className="framer-section framer-layer-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.layers.kicker')}</p>
        <h2>{t('framer.layers.title')}</h2>
        <p>{t('framer.layers.subtitle')}</p>
      </div>
      <div className="framer-layer-flow-horizontal">
        {LAYERS.map((layer, i) => (
          <div key={layer} className="framer-layer-h-item">
            <div
              className={[
                'framer-layer-h-node glass',
                i <= active ? 'lit' : '',
                i === active ? 'active' : '',
              ].filter(Boolean).join(' ')}
            >
              <span className="framer-layer-num">{String(i + 1).padStart(2, '0')}</span>
              <strong>{t(`framer.layers.steps.${layer}.title`)}</strong>
              <p>{t(`framer.layers.steps.${layer}.desc`)}</p>
            </div>
            {i < LAYERS.length - 1 && (
              <div className={`framer-layer-h-arrow${i < active ? ' lit' : ''}`} aria-hidden>→</div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
