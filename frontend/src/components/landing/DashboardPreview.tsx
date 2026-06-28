import { useI18n } from '../../i18n'
import GeminiLogo from '../GeminiLogo'

type Slide = 'dashboard' | 'trading' | 'analytics'

const CHART_PATH = 'M0,80 C40,70 60,40 100,35 S160,15 200,20 S280,5 320,8 S380,25 400,12'
const CHART_AREA = `${CHART_PATH} L400,100 L0,100 Z`
const BAR_HEIGHTS = [42, 58, 35, 72, 48, 65, 38, 55, 70, 45, 62, 50, 68, 44]
const TICKER = ['LONG ETH +$42.10', 'CLOSE BTC +$18.30', 'LONG ETH +$12.00', 'TP ETH +$28.50', 'SIGNAL R3 · ETH']

interface Props {
  slide: Slide
  live?: boolean
}

export default function DashboardPreview({ slide, live = false }: Props) {
  const t = useI18n(s => s.t)
  const rootClass = `product-preview${live ? ' product-preview-live' : ''}`

  if (slide === 'dashboard') {
    return (
      <div className={`${rootClass} product-preview-dashboard`}>
        <aside className="preview-sidebar">
          <div className="preview-brand" style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
            <GeminiLogo size={28} />
          </div>
          {['Dashboard', 'Trades', 'API', 'Referrals'].map(item => (
            <div key={item} className={`preview-nav-item${item === 'Dashboard' ? ' active' : ''}`}>{item}</div>
          ))}
        </aside>
        <div className="preview-main">
          <div className="preview-topbar">
            <span className="preview-pulse" />
            <span>{t('dashboard.running')}</span>
          </div>
          <div className="preview-stat-row">
            {[
              { label: t('dashboard.balance'), val: '$12,480.52', accent: false },
              { label: t('dashboard.todayPnl'), val: '+$186.40', accent: true },
              { label: t('dashboard.winRate'), val: '58.2%', accent: false },
              { label: t('dashboard.totalPnl'), val: '+$2,341.08', accent: true },
            ].map(s => (
              <div key={s.label} className="preview-stat glass">
                <small>{s.label}</small>
                <strong className={s.accent ? 'text-green' : ''}>{s.val}</strong>
              </div>
            ))}
          </div>
          <div className="preview-chart-row">
            <div className="preview-chart-panel glass">
              <small>{t('dashboard.pnlChart')}</small>
              <svg viewBox="0 0 400 100" preserveAspectRatio="none" className="preview-line-chart">
                <defs>
                  <linearGradient id="previewGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgba(0,176,80,0.35)" />
                    <stop offset="100%" stopColor="rgba(0,176,80,0)" />
                  </linearGradient>
                </defs>
                <path d={CHART_AREA} fill="url(#previewGrad)" className="preview-chart-area" />
                <path
                  d={CHART_PATH}
                  fill="none"
                  stroke="#00B050"
                  strokeWidth="2"
                  className="preview-chart-line"
                  pathLength={100}
                />
              </svg>
            </div>
            <div className="preview-chart-panel glass preview-pie-panel">
              <small>{t('dashboard.pnlSource')}</small>
              <div className="preview-pie">
                <div className="preview-pie-ring preview-pie-spin" />
                <span>R3</span>
              </div>
            </div>
          </div>
          <div className="preview-ticker glass">
            <div className="preview-ticker-track">
              {[...TICKER, ...TICKER].map((tx, i) => (
                <span key={`${tx}-${i}`} className="preview-ticker-item">{tx}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (slide === 'trading') {
    return (
      <div className={`${rootClass} product-preview-trading`}>
        <div className="preview-trading-stats">
          {[
            { l: t('dashboard.balance'), v: '$12,480.52' },
            { l: t('dashboard.unrealized'), v: '+$86.20' },
            { l: t('trading.leverage'), v: '20x' },
          ].map(s => (
            <div key={s.l} className="preview-stat glass"><small>{s.l}</small><strong>{s.v}</strong></div>
          ))}
        </div>
        <div className="preview-tv-chart glass">
          <div className="preview-tv-toolbar">
            <span className="preview-gold">ETHUSDT</span>
            <span>15m</span>
            <span className="text-green preview-price-flash">+1.24%</span>
          </div>
          <svg viewBox="0 0 400 120" preserveAspectRatio="none" className="preview-candle-chart">
            {[...Array(24)].map((_, i) => {
              const up = i % 3 !== 0
              const h = 20 + (i * 7) % 40
              const y = up ? 60 - h : 60
              const isLast = i === 23
              return (
                <g
                  key={i}
                  transform={`translate(${8 + i * 16}, 0)`}
                  className={isLast && live ? 'preview-candle-live' : undefined}
                >
                  <line x1="4" y1={y - 8} x2="4" y2={y + h + 8} stroke={up ? '#00B050' : '#EF4444'} strokeWidth="1" />
                  <rect x="1" y={y} width="6" height={h} fill={up ? '#00B050' : '#EF4444'} rx="1" />
                </g>
              )
            })}
          </svg>
        </div>
        <div className="preview-position glass preview-position-live">
          <span className="badge badge-green">LONG</span>
          <span>ETH · 0.42 · Entry $3,842</span>
          <span className="text-green">+$86.20</span>
        </div>
      </div>
    )
  }

  return (
    <div className={`${rootClass} product-preview-analytics`}>
      <div className="preview-metrics-grid">
        {[
          { l: 'Sharpe', v: '1.82' },
          { l: 'Sortino', v: '2.14' },
          { l: 'Profit Factor', v: '1.65' },
          { l: 'MDD', v: '12.4%' },
        ].map(m => (
          <div key={m.l} className="preview-metric glass"><small>{m.l}</small><strong>{m.v}</strong></div>
        ))}
      </div>
      <div className="preview-bar-chart glass">
        <small>{t('analytics.dailyPnl')}</small>
        <div className="preview-bars">
          {BAR_HEIGHTS.map((h, i) => (
            <div
              key={i}
              className="preview-bar preview-bar-grow"
              style={{
                height: `${h}%`,
                background: i % 4 === 1 ? '#EF4444' : '#00B050',
                animationDelay: live ? `${i * 0.05}s` : undefined,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
