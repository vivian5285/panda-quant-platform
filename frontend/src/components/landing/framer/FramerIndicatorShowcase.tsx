import { useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const INDICATORS = [
  'kernelRegression',
  'marketStructure',
  'imbalanceAlgo',
  'trendlineBreakout',
  'tradeIqToolkit',
  'volumeSupertrend',
  'rangeDetector',
  'diyStrategyBuilder',
  'harmonicPatterns',
  'divergenceV4',
] as const

const COLORS: Record<string, string> = {
  kernelRegression: '#007aff',
  marketStructure: '#5856d6',
  imbalanceAlgo: '#00c7be',
  trendlineBreakout: '#ff9f0a',
  tradeIqToolkit: '#bf5af2',
  volumeSupertrend: '#32d74b',
  rangeDetector: '#64d2ff',
  diyStrategyBuilder: '#ff375f',
  harmonicPatterns: '#ffd60a',
  divergenceV4: '#5e5ce6',
}

const GRADIENTS: Record<string, string> = {
  kernelRegression: 'linear-gradient(135deg, #001a33 0%, #003366 40%, #000000 100%)',
  marketStructure: 'linear-gradient(135deg, #1a0a2e 0%, #312e81 50%, #000 100%)',
  imbalanceAlgo: 'linear-gradient(135deg, #002622 0%, #0e7490 45%, #000 100%)',
  trendlineBreakout: 'linear-gradient(135deg, #1c1000 0%, #92400e 40%, #000 100%)',
  tradeIqToolkit: 'linear-gradient(135deg, #1a0a24 0%, #6b21a8 45%, #000 100%)',
  volumeSupertrend: 'linear-gradient(135deg, #001a0a 0%, #065f46 45%, #000 100%)',
  rangeDetector: 'linear-gradient(135deg, #001520 0%, #0369a1 45%, #000 100%)',
  diyStrategyBuilder: 'linear-gradient(135deg, #1a0008 0%, #9f1239 40%, #000 100%)',
  harmonicPatterns: 'linear-gradient(135deg, #1a1500 0%, #854d0e 45%, #000 100%)',
  divergenceV4: 'linear-gradient(135deg, #0a0a1a 0%, #4338ca 45%, #000 100%)',
}

export default function FramerIndicatorShowcase() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const [active, setActive] = useState(0)
  const [tilt, setTilt] = useState({ x: 0, y: 0 })
  const paused = useRef(false)
  const key = INDICATORS[active]

  useEffect(() => {
    if (reduceMotion) return
    const timer = setInterval(() => {
      if (paused.current) return
      setActive(i => (i + 1) % INDICATORS.length)
    }, 5500)
    return () => clearInterval(timer)
  }, [reduceMotion])

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (reduceMotion) return
    const rect = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientY - rect.top) / rect.height - 0.5) * -8
    const y = ((e.clientX - rect.left) / rect.width - 0.5) * 8
    setTilt({ x, y })
  }

  const select = (i: number) => {
    paused.current = true
    setActive(i)
    setTimeout(() => { paused.current = false }, 12000)
  }

  const points = ['a', 'b', 'c'] as const

  return (
    <section id="indicators" className="framer-section framer-indicators-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.indicators.kicker')}</p>
        <h2>{t('framer.indicators.title')}</h2>
        <p>{t('framer.indicators.subtitle')}</p>
      </div>

      <div className="framer-indicators">
        <motion.div
          key={key}
          className="framer-indicator-spotlight framer-glass-cell framer-color-card"
          style={{
            '--card-bg': GRADIENTS[key],
            '--card-accent': COLORS[key],
            transform: reduceMotion ? undefined : `perspective(900px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
          } as React.CSSProperties}
          onMouseMove={onMove}
          onMouseLeave={() => setTilt({ x: 0, y: 0 })}
          initial={reduceMotion ? false : { opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45 }}
        >
          <div className="framer-indicator-wave" />
          <div className="framer-indicator-glow" style={{ background: `radial-gradient(circle at 70% 30%, ${COLORS[key]}33, transparent 55%)` }} />
          <div className="framer-indicator-spotlight-inner glass">
            <span className="framer-indicator-tag">{t(`framer.indicators.items.${key}.tag`)}</span>
            <h3>{t(`framer.indicators.items.${key}.name`)}</h3>
            <p>{t(`framer.indicators.items.${key}.desc`)}</p>
            <ul>
              {points.map(pt => {
                const text = t(`framer.indicators.items.${key}.points.${pt}`)
                if (!text || text.startsWith('framer.')) return null
                return <li key={pt}>{text}</li>
              })}
            </ul>
          </div>
          <div className="framer-indicator-mock-3d" aria-hidden>
            {INDICATORS.slice(0, 5).map((k, i) => (
              <div
                key={k}
                className={`framer-indicator-3d-card${k === key ? ' active' : ''}`}
                style={{
                  '--i': i,
                  '--accent': COLORS[k],
                } as React.CSSProperties}
              />
            ))}
          </div>
        </motion.div>

        <div className="framer-indicator-rail">
          {INDICATORS.map((k, i) => (
            <button
              key={k}
              type="button"
              className={`framer-indicator-chip framer-glass-cell framer-color-card${i === active ? ' active' : ''}`}
              style={{ '--chip-accent': COLORS[k] } as React.CSSProperties}
              onClick={() => select(i)}
            >
              <span className="framer-indicator-chip-dot" style={{ background: COLORS[k] }} />
              {t(`framer.indicators.items.${k}.short`)}
            </button>
          ))}
        </div>
        <p className="framer-indicator-footnote">{t('framer.indicators.footnote')}</p>
      </div>
    </section>
  )
}
