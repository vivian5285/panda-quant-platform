import { useState } from 'react'
import { useI18n } from '../../../i18n'

const FAQ_KEYS = ['analyze', 'accuracy', 'tradingview', 'risk', 'execution'] as const

export default function FramerLandingFAQ() {
  const t = useI18n(s => s.t)
  const [open, setOpen] = useState<string | null>('analyze')

  return (
    <section id="faq" className="framer-section framer-faq-section">
      <div className="framer-section-head">
        <h2>{t('framer.faq.title')}</h2>
      </div>
      <div className="framer-faq-list">
        {FAQ_KEYS.map(key => (
          <div key={key} className={`framer-faq-item${open === key ? ' open' : ''}`}>
            <button
              type="button"
              className="framer-faq-q"
              onClick={() => setOpen(open === key ? null : key)}
              aria-expanded={open === key}
            >
              {t(`framer.faq.items.${key}.q`)}
              <span aria-hidden>{open === key ? '−' : '+'}</span>
            </button>
            {open === key && (
              <div className="framer-faq-a">{t(`framer.faq.items.${key}.a`)}</div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
