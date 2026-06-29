import { useState } from 'react'
import { useI18n } from '../../../i18n'
import DashboardPreview from '../DashboardPreview'

const SLIDES = ['dashboard', 'trading', 'analytics'] as const
const METRICS = ['score', 'pnl', 'winRate', 'analysis'] as const

export default function FramerDashboardProof() {
  const t = useI18n(s => s.t)
  const [slide, setSlide] = useState<(typeof SLIDES)[number]>('dashboard')

  return (
    <section id="dashboard" className="framer-section framer-dashboard-proof">
      <div className="framer-section-head">
        <p className="framer-kicker">{t('framer.dashboard.kicker')}</p>
        <h2>{t('framer.dashboard.title')}</h2>
        <p>{t('framer.dashboard.subtitle')}</p>
      </div>
      <div className="framer-dashboard-layout">
        <div className="framer-dashboard-stats">
          {METRICS.map(key => (
            <div key={key} className="framer-dashboard-stat">
              <small>{t(`framer.dashboard.metrics.${key}.label`)}</small>
              <strong>{t(`framer.dashboard.metrics.${key}.value`)}</strong>
            </div>
          ))}
        </div>
        <div className="framer-dashboard-preview-wrap">
          <div className="framer-dashboard-tabs">
            {SLIDES.map(id => (
              <button
                key={id}
                type="button"
                className={slide === id ? 'active' : ''}
                onClick={() => setSlide(id)}
              >
                {t(`framer.dashboard.slides.${id}`)}
              </button>
            ))}
          </div>
          <div className="framer-dashboard-frame">
            <DashboardPreview slide={slide} live />
          </div>
        </div>
      </div>
    </section>
  )
}
