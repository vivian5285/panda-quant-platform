import { useI18n } from '../../../i18n'

const CARDS = ['emotionFree', 'alwaysOn', 'multiDim', 'adaptive'] as const

export default function FramerWhyAI() {
  const t = useI18n(s => s.t)

  return (
    <section id="why" className="framer-section framer-why-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.why.kicker')}</p>
        <h2>{t('framer.why.title')}</h2>
      </div>
      <div className="framer-why-grid">
        {CARDS.map(key => (
          <article key={key} className="framer-why-card">
            <h3>{t(`framer.why.cards.${key}.title`)}</h3>
            <p>{t(`framer.why.cards.${key}.desc`)}</p>
          </article>
        ))}
      </div>
    </section>
  )
}
