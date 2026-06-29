import { useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const PARTNERS = ['binance', 'okx', 'bybit', 'bitget', 'gate'] as const

const GRADIENTS: Record<string, string> = {
  binance: 'linear-gradient(160deg, #1a1400 0%, #3d3200 35%, #000 100%)',
  okx: 'linear-gradient(160deg, #0a0a0a 0%, #1a1a1a 50%, #000 100%)',
  bybit: 'linear-gradient(160deg, #1a0a00 0%, #7c2d12 40%, #000 100%)',
  bitget: 'linear-gradient(160deg, #001a14 0%, #065f46 40%, #000 100%)',
  gate: 'linear-gradient(160deg, #0a001a 0%, #4c1d95 40%, #000 100%)',
}

const ACCENTS: Record<string, string> = {
  binance: '#f0b90b',
  okx: '#ffffff',
  bybit: '#f7a600',
  bitget: '#00f0a0',
  gate: '#8b5cf6',
}

export default function FramerExchangePartners() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const [hovered, setHovered] = useState<string | null>(null)

  return (
    <section id="partners" className="framer-section framer-partners-section">
      <div className="framer-partners-head">
        <div>
          <p className="framer-kicker">{t('framer.partners.kicker')}</p>
          <h2>{t('framer.partners.title')}</h2>
        </div>
        <span className="framer-partners-meta">{t('framer.partners.meta')}</span>
      </div>

      <div className="framer-partners-track">
        {PARTNERS.map((key, i) => (
          <motion.article
            key={key}
            className={`framer-partner-card glass framer-glass-cell framer-color-card${hovered === key ? ' hovered' : ''}`}
            style={{
              '--card-bg': GRADIENTS[key],
              '--card-accent': ACCENTS[key],
            } as React.CSSProperties}
            onMouseEnter={() => setHovered(key)}
            onFocus={() => setHovered(key)}
            tabIndex={0}
            initial={reduceMotion ? false : { opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-40px' }}
            transition={{ duration: 0.45, delay: i * 0.06 }}
          >
            <span className="framer-partner-logo">{t(`framer.partners.items.${key}.name`)}</span>
            <span className={`framer-partner-status status-${key === 'binance' ? 'live' : 'coming'}`}>
              {t(`framer.partners.items.${key}.status`)}
            </span>
            <p className="framer-partner-desc">{t(`framer.partners.items.${key}.desc`)}</p>
            <span className="framer-partner-cta">{t('framer.partners.readMore')} →</span>
          </motion.article>
        ))}
      </div>
    </section>
  )
}
