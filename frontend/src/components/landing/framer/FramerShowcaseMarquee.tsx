import { useI18n } from '../../../i18n'

const KEYS = ['dashboard', 'trading', 'signals', 'analytics', 'settlement'] as const

export default function FramerShowcaseMarquee() {
  const t = useI18n(s => s.t)
  const items = KEYS.map(k => ({
    key: k,
    label: t(`framer.shipped.items.${k}`),
    desc: t(`framer.shipped.itemsDesc.${k}`),
  }))

  const track = [...items, ...items, ...items]

  return (
    <div className="framer-marquee-section">
      <div className="framer-marquee framer-marquee-forward">
        <div className="framer-marquee-track">
          {track.map((item, i) => (
            <div key={`${item.key}-${i}`} className="framer-marquee-card">
              <div className="framer-marquee-visual">
                <span className="framer-marquee-glow" />
                <strong>{item.label}</strong>
              </div>
              <p>{item.desc}</p>
            </div>
          ))}
        </div>
      </div>
      <div className="framer-marquee framer-marquee-reverse">
        <div className="framer-marquee-track">
          {[...track].reverse().map((item, i) => (
            <div key={`${item.key}-r-${i}`} className="framer-marquee-card">
              <div className="framer-marquee-visual framer-marquee-visual-alt">
                <span className="framer-marquee-glow" />
                <strong>{item.label}</strong>
              </div>
              <p>{item.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
