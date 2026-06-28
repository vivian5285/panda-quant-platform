import { useI18n } from '../../i18n'

const LOGOS = ['Binance', 'TradingView', 'USDT-M', 'WebSocket', 'OAuth 2.0', 'Redis', 'FastAPI', 'React']

export default function LogoMarquee() {
  const t = useI18n(s => s.t)
  const items = [...LOGOS, ...LOGOS]

  return (
    <section className="logo-marquee-section" aria-label={t('landing.logos.title')}>
      <p className="logo-marquee-label">{t('landing.logos.title')}</p>
      <div className="logo-marquee-track-wrap">
        <div className="logo-marquee-track">
          {items.map((name, i) => (
            <span key={`${name}-${i}`} className="logo-marquee-item">{name}</span>
          ))}
        </div>
      </div>
    </section>
  )
}
