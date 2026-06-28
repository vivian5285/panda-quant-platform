import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n'

const INDICATOR_KEYS = [
  'mkr',
  'marketStructure',
  'imbalance',
  'trendline',
  'tradeIq',
  'volumeSupertrend',
  'rangeDetector',
  'diyBuilder',
  'harmonic',
  'divergence',
] as const

const GRADIENTS = [
  'linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #6366f1 100%)',
  'linear-gradient(135deg, #0c4a6e 0%, #0369a1 50%, #38bdf8 100%)',
  'linear-gradient(135deg, #134e4a 0%, #0f766e 50%, #2dd4bf 100%)',
  'linear-gradient(135deg, #1e293b 0%, #334155 50%, #94a3b8 100%)',
  'linear-gradient(135deg, #312e81 0%, #4f46e5 50%, #818cf8 100%)',
  'linear-gradient(135deg, #172554 0%, #1d4ed8 50%, #60a5fa 100%)',
  'linear-gradient(135deg, #18181b 0%, #27272a 50%, #52525b 100%)',
  'linear-gradient(135deg, #4c1d95 0%, #7c3aed 50%, #a78bfa 100%)',
  'linear-gradient(135deg, #831843 0%, #be185d 50%, #f472b6 100%)',
  'linear-gradient(135deg, #713f12 0%, #ca8a04 50%, #fde047 100%)',
]

export default function FramerIndicatorShowcase() {
  const t = useI18n(s => s.t)
  const [active, setActive] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setActive(i => (i + 1) % INDICATOR_KEYS.length)
    }, 4500)
    return () => clearInterval(timer)
  }, [])

  const key = INDICATOR_KEYS[active]

  return (
    <section id="indicators" className="framer-section framer-indicators">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.indicators.kicker')}</p>
        <h2>{t('framer.indicators.title')}</h2>
        <p>{t('framer.indicators.subtitle')}</p>
      </div>

      <div className="framer-indicator-stage">
        <div
          className="framer-indicator-spotlight"
          style={{ background: GRADIENTS[active] }}
          key={key}
        >
          <div className="framer-indicator-spotlight-inner">
            <span className="framer-indicator-tag">{t(`framer.indicators.items.${key}.tag`)}</span>
            <h3>{t(`framer.indicators.items.${key}.name`)}</h3>
            <p>{t(`framer.indicators.items.${key}.desc`)}</p>
            <ul>
              {(['a', 'b', 'c'] as const).map(s => (
                <li key={s}>{t(`framer.indicators.items.${key}.points.${s}`)}</li>
              ))}
            </ul>
          </div>
          <div className="framer-indicator-wave" aria-hidden />
        </div>

        <div className="framer-indicator-rail">
          {INDICATOR_KEYS.map((k, i) => (
            <button
              key={k}
              type="button"
              className={`framer-indicator-chip${i === active ? ' active' : ''}`}
              onClick={() => setActive(i)}
            >
              <span className="framer-indicator-chip-dot" style={{ background: GRADIENTS[i] }} />
              <span>{t(`framer.indicators.items.${k}.short`)}</span>
            </button>
          ))}
        </div>
      </div>

      <p className="framer-indicator-footnote">{t('framer.indicators.footnote')}</p>
    </section>
  )
}
