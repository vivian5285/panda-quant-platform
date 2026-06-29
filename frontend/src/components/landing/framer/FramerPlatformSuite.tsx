import { useI18n } from '../../../i18n'

const TILES = [
  'performance', 'webhook', 'settlement', 'security',
  'multiuser', 'analytics', 'hosting', 'referral',
] as const

export default function FramerPlatformSuite() {
  const t = useI18n(s => s.t)

  return (
    <section id="platform" className="framer-section framer-platform-suite">
      <div className="framer-platform-head-row">
        <h2>{t('framer.platform.title')}</h2>
        <p>{t('framer.platform.subtitle')}</p>
      </div>
      <div className="framer-platform-bento">
        {TILES.map(key => (
          <article
            key={key}
            className={`framer-platform-tile glass framer-glass-cell framer-platform-tile-${key}`}
          >
            <div className="framer-platform-tile-visual">
              {key === 'performance' && (
                <div className="framer-platform-float framer-platform-float-cwv">
                  <div className="framer-cwv-mock framer-cwv-mock-lg">
                    <span className="good">GOOD</span>
                    <div><small>LCP</small><strong>1.1s</strong></div>
                    <div><small>Win Rate</small><strong>68%</strong></div>
                    <div><small>Sharpe</small><strong>1.82</strong></div>
                  </div>
                </div>
              )}
              {key === 'webhook' && (
                <div className="framer-platform-float framer-platform-float-cms">
                  <table className="framer-mock-cms framer-mock-cms-sm">
                    <tbody>
                      <tr><td>Trend Intel</td><td className="live">Live</td></tr>
                      <tr><td>Structure AI</td><td className="live">Live</td></tr>
                      <tr><td>Liquidity</td><td className="live">Live</td></tr>
                    </tbody>
                  </table>
                </div>
              )}
              {key === 'settlement' && (
                <div className="framer-platform-float framer-platform-float-seo">
                  <div className="framer-platform-seo-mock">
                    <small>{t('framer.platform.seo.symbol')}</small>
                    <strong>ETHUSDT</strong>
                    <small>{t('framer.platform.seo.bias')}</small>
                    <span>92% Long</span>
                  </div>
                </div>
              )}
              {key === 'analytics' && (
                <div className="framer-platform-float framer-platform-float-analytics">
                  <div className="framer-platform-chart-mock">
                    {[40, 65, 45, 80, 55, 90, 70].map((h, i) => (
                      <span key={i} style={{ height: `${h}%` }} />
                    ))}
                  </div>
                </div>
              )}
              {key === 'hosting' && (
                <div className="framer-platform-float framer-platform-float-uptime">
                  <strong className="framer-platform-uptime">99.99%</strong>
                  <span>uptime</span>
                </div>
              )}
            </div>
            <div className="framer-platform-tile-copy">
              <h3>{t(`framer.platform.tiles.${key}.title`)}</h3>
              <p>{t(`framer.platform.tiles.${key}.desc`)}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
