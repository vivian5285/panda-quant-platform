import { useState } from 'react'
import { useI18n } from '../../../i18n'
import DashboardPreview from '../DashboardPreview'

const SLIDES = ['dashboard', 'trading', 'analytics'] as const

export default function FramerDashboardProof() {
  const t = useI18n(s => s.t)
  const [slide, setSlide] = useState<(typeof SLIDES)[number]>('dashboard')

  return (
    <section id="dashboard" className="framer-section framer-dashboard-proof">
      <div className="framer-section-head framer-section-head-left">
        <p className="framer-kicker">{t('framer.dashboard.kicker')}</p>
        <h2>{t('framer.dashboard.title')}</h2>
        <p>{t('framer.dashboard.subtitle')}</p>
      </div>
      <div className="framer-dashboard-layout">
        <div className="framer-dashboard-stats">
          {(['score', 'pnl', 'winRate', 'analysis'] as const).map(k => (
            <div key={k} className="framer-dashboard-stat">
              <small>{t(`framer.dashboard.metrics.${k}.label`)}</small>
              <strong>{t(`framer.dashboard.metrics.${k}.value`)}</strong>
            </div>
          ))}
        </div>
        <div className="framer-dashboard-preview-wrap">
          <div className="framer-dashboard-tabs">
            {SLIDES.map(s => (
              <button
                key={s}
                type="button"
                className={slide === s ? 'active' : ''}
                onClick={() => setSlide(s)}
              >
                {t(`framer.dashboard.slides.${s}`)}
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
