import { useState } from 'react'
import { useI18n } from '../../../i18n'

const MODELS = [
  'kernelRegression',
  'mlTrendFilter',
  'marketStructure',
  'trendlineBreakout',
  'volumeSupertrend',
  'divergenceAi',
  'harmonicAi',
  'liquidityZone',
  'supportResistance',
  'marketRegime',
  'imbalance',
  'orderBlock',
  'fvg',
  'rangeDetector',
  'swingAnalyzer',
  'trendProbability',
  'signalConfidence',
  'adaptiveAtr',
  'volatilityFilter',
] as const

export default function FramerModelsGrid() {
  const t = useI18n(s => s.t)
  const [hovered, setHovered] = useState<string | null>(null)

  return (
    <section id="models" className="framer-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.models.kicker')}</p>
        <h2>{t('framer.models.title')}</h2>
        <p>{t('framer.models.subtitle')}</p>
      </div>
      <div className="framer-models-grid">
        {MODELS.map(key => (
          <article
            key={key}
            className={`framer-model-card${hovered === key ? ' expanded' : ''}`}
            onMouseEnter={() => setHovered(key)}
            onMouseLeave={() => setHovered(null)}
            onFocus={() => setHovered(key)}
            onBlur={() => setHovered(null)}
            tabIndex={0}
          >
            <h3>{t(`framer.models.items.${key}.name`)}</h3>
            <p>{t(`framer.models.items.${key}.desc`)}</p>
            <div className="framer-model-expand">
              <span>{t(`framer.models.items.${key}.detail`)}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
