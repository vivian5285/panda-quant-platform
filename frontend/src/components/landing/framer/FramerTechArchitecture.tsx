import { useI18n } from '../../../i18n'

const NODES = [
  'aiEngine',
  'cloud',
  'execution',
  'binance',
  'websocket',
  'riskEngine',
  'analytics',
  'settlement',
] as const

export default function FramerTechArchitecture() {
  const t = useI18n(s => s.t)

  return (
    <section id="tech" className="framer-section framer-tech-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.tech.kicker')}</p>
        <h2>{t('framer.tech.title')}</h2>
        <p>{t('framer.tech.subtitle')}</p>
      </div>
      <div className="framer-tech-diagram">
        {NODES.map((node, i) => (
          <div key={node} className="framer-tech-row">
            <div className="framer-tech-node">
              <span className="framer-tech-dot" />
              <div>
                <strong>{t(`framer.tech.nodes.${node}.title`)}</strong>
                <p>{t(`framer.tech.nodes.${node}.desc`)}</p>
              </div>
            </div>
            {i < NODES.length - 1 && <div className="framer-tech-arrow" aria-hidden>↓</div>}
          </div>
        ))}
      </div>
    </section>
  )
}
