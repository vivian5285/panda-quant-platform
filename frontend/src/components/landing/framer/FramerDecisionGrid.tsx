import { useI18n } from '../../../i18n'

const CARDS = ['trend', 'structure', 'regime', 'momentum', 'liquidity', 'probability'] as const

export default function FramerDecisionGrid() {
  const t = useI18n(s => s.t)

  return (
    <section id="engine" className="framer-section">
      <div className="framer-section-head framer-section-head-left">
        <p className="framer-kicker">{t('framer.think.kicker')}</p>
        <h2>{t('framer.think.title')}</h2>
        <p>{t('framer.think.subtitle')}</p>
      </div>
      <div className="framer-decision-grid">
        {CARDS.map(key => (
          <article key={key} className="framer-decision-card">
            <div className="framer-decision-card-head">
              <span className={`framer-decision-icon framer-decision-icon-${key}`} aria-hidden />
              <h3>{t(`framer.think.cards.${key}.title`)}</h3>
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
          </article>
        ))}
      </div>
    </section>
  )
}
