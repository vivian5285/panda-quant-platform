import { Link } from 'react-router-dom'
import { useI18n } from '../../../i18n'

const ITEMS = [
  { key: 'trend', layout: 'wide' },
  { key: 'structure', layout: 'tall' },
  { key: 'regime', layout: 'sq' },
  { key: 'momentum', layout: 'wide' },
  { key: 'liquidity', layout: 'sq' },
  { key: 'probability', layout: 'tall' },
] as const

const GRADIENTS: Record<string, string> = {
  trend: 'linear-gradient(160deg, #0a0a0a 0%, #1e3a8a 50%, #0f172a 100%)',
  structure: 'linear-gradient(180deg, #0a0a0a 0%, #4c1d95 45%, #1e1b4b 100%)',
  regime: 'linear-gradient(145deg, #050505 0%, #065f46 40%, #0f172a 100%)',
  momentum: 'linear-gradient(160deg, #000 0%, #0e7490 35%, #111827 100%)',
  liquidity: 'linear-gradient(145deg, #0a0a0a 0%, #7c3aed 35%, #1e1b4b 100%)',
  probability: 'linear-gradient(180deg, #050505 0%, #0891b2 40%, #0f172a 100%)',
}

export default function FramerShowcaseMarquee() {
  const t = useI18n(s => s.t)

  return (
    <section id="showcase" className="framer-showcase-section">
      <div className="framer-showcase-head-row">
        <div>
          <h2>{t('framer.showcase.title')}</h2>
        </div>
        <Link to="#indicators" className="framer-showcase-cta-pill" onClick={e => {
          e.preventDefault()
          document.getElementById('indicators')?.scrollIntoView({ behavior: 'smooth' })
        }}>
          {t('framer.showcase.cta')}
        </Link>
      </div>

      <div className="framer-showcase-masonry">
        {ITEMS.map(({ key, layout }) => (
          <article
            key={key}
            className={`framer-showcase-tile framer-showcase-tile-${layout} glass`}
          >
            <div className="framer-showcase-tile-chrome">
              <span /><span /><span />
              <span className="framer-showcase-tile-name">{t(`framer.showcase.cards.${key}`)}</span>
            </div>
            <div className="framer-showcase-tile-body" style={{ background: GRADIENTS[key] }}>
              <span className="framer-showcase-tile-label">{t(`framer.showcase.cards.${key}`)}</span>
              <div className="framer-showcase-tile-mock" aria-hidden>
                {layout === 'tall' && (
                  <div className="framer-showcase-mock-tall">
                    <div className="framer-showcase-mock-line lg" />
                    <div className="framer-showcase-mock-line" />
                    <div className="framer-showcase-mock-chart" />
                  </div>
                )}
                {layout === 'wide' && (
                  <div className="framer-showcase-mock-wide">
                    <div className="framer-showcase-mock-stat">92%</div>
                    <div className="framer-showcase-mock-bars">
                      <span /><span /><span /><span />
                    </div>
                  </div>
                )}
                {layout === 'sq' && (
                  <div className="framer-showcase-mock-sq">
                    <div /><div /><div /><div />
                  </div>
                )}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
