import { useI18n } from '../../../i18n'

const ITEMS = [
  'dynamicSl',
  'adaptiveTp',
  'riskScore',
  'volatilityProtection',
  'maxDrawdown',
  'positionSizeAi',
  'newsRisk',
  'emergencyExit',
] as const

export default function FramerRiskManagement() {
  const t = useI18n(s => s.t)

  return (
    <section id="risk" className="framer-section framer-risk-section">
      <div className="framer-section-head framer-section-head-left">
        <p className="framer-kicker">{t('framer.risk.kicker')}</p>
        <h2>{t('framer.risk.title')}</h2>
        <p>{t('framer.risk.subtitle')}</p>
      </div>
      <div className="framer-risk-grid">
        {ITEMS.map(key => (
          <article key={key} className="framer-risk-card">
            <h3>{t(`framer.risk.items.${key}.title`)}</h3>
            <p>{t(`framer.risk.items.${key}.desc`)}</p>
          </article>
        ))}
      </div>
    </section>
  )
}
