import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { useI18n } from '../../i18n'
import ScrollReveal from '../ui/ScrollReveal'

const FAQ_KEYS = ['what', 'safe', 'strategy', 'settlement', 'fee'] as const

export default function FaqSection() {
  const t = useI18n(s => s.t)
  const [open, setOpen] = useState<string | null>(FAQ_KEYS[0])

  return (
    <section id="faq" className="landing-section">
      <ScrollReveal className="landing-section-head">
        <p className="landing-kicker">{t('landing.nav.faq')}</p>
        <h2>{t('saas.faq.title')}</h2>
      </ScrollReveal>
      <div className="faq-list">
        {FAQ_KEYS.map((key, i) => (
          <ScrollReveal key={key} delay={i * 0.05} className={`faq-item glass ${open === key ? 'open' : ''}`}>
            <button type="button" className="faq-q" onClick={() => setOpen(open === key ? null : key)}>
              {t(`saas.faq.items.${key}.q`)}
              <ChevronDown size={18} className="faq-chevron" />
            </button>
            {open === key && <div className="faq-a">{t(`saas.faq.items.${key}.a`)}</div>}
          </ScrollReveal>
        ))}
      </div>
    </section>
  )
}
