import { useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const FAQ_KEYS = ['advantage', 'pipeline', 'principle', 'confidence', 'custody'] as const

export default function FramerLandingFAQ() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const [open, setOpen] = useState<string | null>('advantage')

  return (
    <section id="faq" className="framer-section framer-faq-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.faq.kicker')}</p>
        <h2>{t('framer.faq.title')}</h2>
        <p className="framer-faq-sub">{t('framer.faq.subtitle')}</p>
      </div>
      <div className="framer-faq-list">
        {FAQ_KEYS.map(key => {
          const isOpen = open === key
          return (
            <div key={key} className={`framer-faq-item glass${isOpen ? ' open' : ''}`}>
              <button
                type="button"
                className="framer-faq-q"
                onClick={() => setOpen(isOpen ? null : key)}
                aria-expanded={isOpen}
              >
                {t(`framer.faq.items.${key}.q`)}
                <span className="framer-faq-toggle" aria-hidden>{isOpen ? '−' : '+'}</span>
              </button>
              <AnimatePresence initial={false}>
                {isOpen && (
                  <motion.div
                    className="framer-faq-a"
                    initial={reduceMotion ? false : { height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                  >
                    <div className="framer-faq-a-inner">{t(`framer.faq.items.${key}.a`)}</div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )
        })}
      </div>
    </section>
  )
}
