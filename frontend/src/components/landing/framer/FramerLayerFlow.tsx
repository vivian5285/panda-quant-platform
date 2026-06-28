import { useI18n } from '../../../i18n'

const LAYERS = [
  'trendIntel',
  'momentumIntel',
  'structureIntel',
  'liquidityIntel',
  'volatilityIntel',
  'probability',
  'execution',
] as const

export default function FramerLayerFlow() {
  const t = useI18n(s => s.t)

  return (
    <section id="layers" className="framer-section framer-layer-section">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.layers.kicker')}</p>
        <h2>{t('framer.layers.title')}</h2>
        <p>{t('framer.layers.subtitle')}</p>
      </div>
      <div className="framer-layer-flow">
        {LAYERS.map((layer, i) => (
          <div key={layer} className="framer-layer-step">
            <div className="framer-layer-node">
              <span className="framer-layer-num">{String(i + 1).padStart(2, '0')}</span>
              <div>
                <strong>{t(`framer.layers.steps.${layer}.title`)}</strong>
                <p>{t(`framer.layers.steps.${layer}.desc`)}</p>
              </div>
            </div>
            {i < LAYERS.length - 1 && <div className="framer-layer-connector" aria-hidden />}
          </div>
        ))}
      </div>
    </section>
  )
}
