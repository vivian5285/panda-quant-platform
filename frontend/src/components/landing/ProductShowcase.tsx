import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useI18n } from '../../i18n'
import ScrollReveal from '../ui/ScrollReveal'
import DashboardPreview from './DashboardPreview'

const SLIDES = ['dashboard', 'trading', 'analytics'] as const

export default function ProductShowcase() {
  const t = useI18n(s => s.t)
  const [idx, setIdx] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => setIdx(i => (i + 1) % SLIDES.length), 4500)
    return () => clearInterval(timer)
  }, [])

  const slide = SLIDES[idx]

  return (
    <section id="showcase" className="landing-section showcase-section">
      <ScrollReveal className="landing-section-head">
        <p className="landing-kicker">{t('saas.showcase.kicker')}</p>
        <h2>{t('saas.showcase.title')}</h2>
        <p>{t('saas.showcase.subtitle')}</p>
      </ScrollReveal>

      <div className="showcase-dots">
        {SLIDES.map((s, i) => (
          <button
            key={s}
            type="button"
            className={`showcase-dot${i === idx ? ' active' : ''}`}
            onClick={() => setIdx(i)}
            aria-label={t(`saas.showcase.slides.${s}`)}
          />
        ))}
      </div>

      <div className="showcase-stage">
        <div className="device device-mac glass showcase-device">
          <div className="device-bar">
            <span /><span /><span />
            <span className="device-title">{t(`saas.showcase.slides.${slide}`)}</span>
          </div>
          <AnimatePresence mode="wait">
            <motion.div
              key={slide}
              className="device-screen showcase-screen"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.35 }}
            >
              <DashboardPreview slide={slide} />
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="device device-phone glass showcase-phone">
          <div className="device-notch" />
          <div className="showcase-phone-inner">
            <DashboardPreview slide="dashboard" />
          </div>
        </div>

        <div className="device device-tablet glass showcase-tablet">
          <DashboardPreview slide="analytics" />
        </div>
      </div>
    </section>
  )
}
