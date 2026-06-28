import { motion, useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'
import { useI18n } from '../../../i18n'

const cardVariants = {
  hidden: { opacity: 0, y: 32 },
  visible: { opacity: 1, y: 0 },
}

export default function FramerPlatformBento() {
  const t = useI18n(s => s.t)
  const reduce = useReducedMotion()

  const Card = ({ className, children }: { className?: string; children: ReactNode }) => {
    if (reduce) {
      return <div className={`framer-platform-card framer-bento-card ${className || ''}`}>{children}</div>
    }
    return (
      <motion.div
        className={`framer-platform-card framer-bento-card ${className || ''}`}
        variants={cardVariants}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
      >
        {children}
      </motion.div>
    )
  }

  const containerProps = reduce
    ? { className: 'framer-bento' }
    : {
        className: 'framer-bento',
        initial: 'hidden' as const,
        whileInView: 'visible' as const,
        viewport: { once: true, margin: '-60px' },
        variants: { visible: { transition: { staggerChildren: 0.07 } } },
      }

  const Container = reduce ? 'div' : motion.div

  return (
    <Container {...containerProps}>
      <Card className="span2 framer-bento-performance">
        <h4>{t('framer.platform.performance.title')}</h4>
        <div className="framer-vitals">
          <span className="framer-vitals-badge">{t('framer.platform.performance.grade')}</span>
          <div className="framer-vitals-grid">
            <div><strong>1.1s</strong><span>LCP</span></div>
            <div><strong>95ms</strong><span>INP</span></div>
            <div><strong>0.01</strong><span>CLS</span></div>
          </div>
        </div>
        <p>{t('framer.platform.performance.desc')}</p>
      </Card>

      <Card><h4>{t('framer.platform.security.title')}</h4><p>{t('framer.platform.security.desc')}</p></Card>
      <Card><h4>{t('framer.platform.latency.title')}</h4><p>{t('framer.platform.latency.desc')}</p></Card>

      <Card className="framer-bento-cms">
        <h4>{t('framer.platform.cms.title')}</h4>
        <div className="framer-mini-table">
          <div className="framer-mini-table-head">
            <span>{t('framer.platform.cms.colStrategy')}</span>
            <span>{t('framer.platform.cms.colStatus')}</span>
          </div>
          {(['a', 'b', 'c'] as const).map(k => (
            <div key={k} className="framer-mini-table-row">
              <span>{t(`framer.platform.cms.rows.${k}.name`)}</span>
              <span className="framer-badge-live">{t(`framer.platform.cms.rows.${k}.status`)}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card className="framer-bento-seo">
        <h4>{t('framer.platform.compliance.title')}</h4>
        <div className="framer-seo-mock">
          <div><label>{t('framer.platform.compliance.url')}</label><span>/dashboard</span></div>
          <div><label>{t('framer.platform.compliance.desc')}</label><span>{t('framer.platform.compliance.descVal')}</span></div>
        </div>
      </Card>

      <Card className="framer-bento-collab">
        <h4>{t('framer.platform.collab.title')}</h4>
        <div className="framer-branch-list">
          {(['main', 'risk', 'settle'] as const).map(k => (
            <div key={k} className="framer-branch-row">
              <span className="framer-branch-dot" />
              <span>{t(`framer.platform.collab.branches.${k}`)}</span>
              <small>{t(`framer.platform.collab.times.${k}`)}</small>
            </div>
          ))}
        </div>
      </Card>

      <Card className="framer-bento-i18n">
        <h4>{t('framer.platform.i18n.title')}</h4>
        <div className="framer-locale-list">
          {(['zh', 'en', 'sg', 'jp'] as const).map(k => (
            <div key={k} className="framer-locale-row">
              <span>{t(`framer.platform.i18n.locales.${k}.name`)}</span>
              <span>{t(`framer.platform.i18n.locales.${k}.pct`)}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card className="framer-bento-hosting">
        <h4>{t('framer.platform.hosting.title')}</h4>
        <div className="framer-uptime">
          <strong>99.99%</strong>
          <span>{t('framer.platform.hosting.uptime')}</span>
        </div>
        <p>{t('framer.platform.hosting.desc')}</p>
      </Card>

      <Card className="span2 framer-bento-analytics">
        <h4>{t('framer.platform.analytics.title')}</h4>
        <div className="framer-analytics-mock">
          <div className="framer-analytics-stat">
            <strong>1.7M</strong><span>{t('framer.platform.analytics.pageviews')}</span>
          </div>
          <div className="framer-analytics-bars">
            {[40, 55, 35, 70, 48, 62, 80, 52, 68, 45].map((h, i) => (
              <div key={i} style={{ height: `${h}%` }} />
            ))}
          </div>
        </div>
      </Card>

      <Card className="span2 framer-bento-ab">
        <h4>{t('framer.platform.ab.title')}</h4>
        <div className="framer-ab-table">
          <div className="framer-ab-head">
            <span>{t('framer.platform.ab.variant')}</span>
            <span>{t('framer.platform.ab.conversion')}</span>
            <span>{t('framer.platform.ab.lift')}</span>
          </div>
          <div className="framer-ab-row winner">
            <span>{t('framer.platform.ab.winner')}</span>
            <span>17.1%</span>
            <span>+14.1%</span>
          </div>
          <div className="framer-ab-row">
            <span>{t('framer.platform.ab.control')}</span>
            <span>15.0%</span>
            <span>—</span>
          </div>
        </div>
      </Card>

      <Card className="span4 framer-bento-partnership">
        <h4>{t('framer.platform.partnership.title')}</h4>
        <p>{t('framer.platform.partnership.desc')}</p>
      </Card>
    </Container>
  )
}
