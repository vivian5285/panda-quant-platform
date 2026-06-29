import { useEffect, useState, type CSSProperties } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const CARDS = ['trend', 'structure', 'regime', 'momentum', 'liquidity', 'probability'] as const

const TAG_COLORS: Record<(typeof CARDS)[number], string> = {
  trend: '#007aff',
  structure: '#a855f7',
  regime: '#22c55e',
  momentum: '#06b6d4',
  liquidity: '#f59e0b',
  probability: '#ec4899',
}

export default function FramerDecisionGrid() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const [active, setActive] = useState(0)

  useEffect(() => {
    if (reduceMotion) return
    const timer = setInterval(() => setActive(i => (i + 1) % CARDS.length), 2800)
    return () => clearInterval(timer)
  }, [reduceMotion])

  const activeKey = CARDS[active]

  return (
    <section id="engine" className="framer-section framer-think-section">
      <div className="framer-section-head framer-section-head-left">
        <p className="framer-kicker">{t('framer.think.kicker')}</p>
        <h2>{t('framer.think.title')}</h2>
        <p>{t('framer.think.subtitle')}</p>
      </div>

      <div className="framer-think-tags-wrap">
        <div className="framer-think-tags-row">
          {CARDS.map((key, i) => (
            <button
              key={key}
              type="button"
              className={`framer-think-tag${i === active ? ' active' : ''}`}
              style={{ '--tag-color': TAG_COLORS[key] } as CSSProperties}
              onClick={() => setActive(i)}
            >
              <span className="framer-think-tag-dot" />
              {t(`framer.think.tags.${key}`)}
            </button>
          ))}
        </div>
        <div className="framer-think-tags-marquee" aria-hidden>
          <div className="framer-think-tags-track">
            {[...CARDS, ...CARDS].map((key, i) => (
              <span
                key={`${key}-${i}`}
                className="framer-think-tag-ghost"
                style={{ '--tag-color': TAG_COLORS[key] } as CSSProperties}
              >
                {t(`framer.think.tags.${key}`)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="framer-decision-grid">
        {CARDS.map(key => {
          const lit = key === activeKey
          return (
            <motion.article
              key={key}
              className={`framer-decision-card glass${lit ? ' framer-decision-card-lit' : ''}`}
              style={{ '--tag-color': TAG_COLORS[key] } as CSSProperties}
              animate={lit ? { y: -4, scale: 1.01 } : { y: 0, scale: 1 }}
              transition={{ duration: 0.35, ease: 'easeOut' }}
            >
              <div className="framer-decision-card-head">
                <span className={`framer-decision-icon framer-decision-icon-${key}`} aria-hidden />
                <h3>{t(`framer.think.cards.${key}.title`)}</h3>
                {lit && <span className="framer-decision-live-pill">{t('framer.think.live')}</span>}
              </div>
              <p className="framer-decision-lead">{t(`framer.think.cards.${key}.lead`)}</p>
              <ul>
                {(['a', 'b', 'c', 'd'] as const).map(pt => {
                  const text = t(`framer.think.cards.${key}.points.${pt}`)
                  if (!text || text.startsWith('framer.think')) return null
                  return <li key={pt}>{text}</li>
                })}
              </ul>
              {key === 'probability' && (
                <div className="framer-confidence-meter">
                  <span className="framer-confidence-value">92%</span>
                  <span className="framer-confidence-label">{t('framer.think.confidence')}</span>
                </div>
              )}
            </motion.article>
          )
        })}
      </div>
    </section>
  )
}
