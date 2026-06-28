import { useI18n } from '../../../i18n'
import { PartnerBrandIcon, type PartnerBrandId } from './PartnerBrandIcons'

const PARTNERS: PartnerBrandId[] = ['binance', 'onchain', 'redis', 'fastapi']

export default function FramerPartnerLogos() {
  const t = useI18n(s => s.t)

  return (
    <div className="framer-partners-row">
      {PARTNERS.map(k => (
        <div
          key={k}
          className={`framer-partner-logo framer-partner-${k}`}
          title={t(`framer.partners.logos.${k}`)}
          aria-label={t(`framer.partners.logos.${k}`)}
        >
          <div className="framer-partner-mark">
            <PartnerBrandIcon id={k} className={`framer-partner-svg framer-partner-svg-${k}`} />
          </div>
        </div>
      ))}
    </div>
  )
}
