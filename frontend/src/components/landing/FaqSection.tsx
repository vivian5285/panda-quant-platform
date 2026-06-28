import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { useI18n } from '../../i18n'

const FAQ_KEYS = ['what', 'safe', 'strategy', 'settlement', 'fee'] as const

export default function FaqSection() {
  const t = useI18n(s => s.t)
  const [open, setOpen] = useState<string | null>(FAQ_KEYS[0])

  return (
    <section id="faq" className="framer-faq">
      <div className="framer-faq-head">
        <p className="framer-kicker">{t('landing.nav.faq')}</p>
        <h2>{t('saas.faq.title')}</h2>
      </div>
      <div className="framer-faq-list">
        {FAQ_KEYS.map(key => (
          <div key={key} className={`framer-faq-item glass ${open === key ? 'open' : ''}`}>
            <button type="button" className="framer-faq-q" onClick={() => setOpen(open === key ? null : key)}>
              {t(`saas.faq.items.${key}.q`)}
              <ChevronDown size={18} className="framer-faq-chevron" />
            </button>
            {open === key && <div className="framer-faq-a">{t(`saas.faq.items.${key}.a`)}</div>}
          </div>
        ))}
      </div>
    </section>
  )
}
