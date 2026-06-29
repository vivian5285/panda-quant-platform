import { useI18n } from '../../../i18n'

const LOGOS = ['emotionFree', 'multiDim', 'adaptive', 'institutional', 'nonCustodial', 'aiNative'] as const

export default function FramerTrustedStrip() {
  const t = useI18n(s => s.t)

  return (
    <section className="framer-trusted-section">
      <p className="framer-trusted-label">{t('framer.trusted.kicker')}</p>
      <div className="framer-trusted-logos">
        {LOGOS.map(key => (
          <span key={key} className="framer-trusted-logo">
            {t(`framer.trusted.logos.${key}`)}
          </span>
        ))}
      </div>
    </section>
  )
}
