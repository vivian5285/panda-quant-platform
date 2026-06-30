import type { CSSProperties } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { useI18n } from '../i18n'
import { Brain, Zap, Shield, Gauge, Activity, Clock, Layers, Target } from 'lucide-react'

const METRIC_ACCENTS = ['#007aff', '#5856d6', '#32d74b', '#ff9f0a', '#ff375f'] as const

const METRIC_BGS = METRIC_ACCENTS.map(
  c => `linear-gradient(160deg, color-mix(in srgb, ${c} 20%, #000) 0%, color-mix(in srgb, ${c} 8%, #0c0c0c) 50%, #141414 100%)`,
)

const AI_ICONS = [Brain, Clock, Layers, Target] as const
const EXEC_ICONS = [Zap, Gauge, Activity, Shield] as const

export default function StrategyAdvantages() {
  const t = useI18n(s => s.t)

  const aiKeys = ['discipline', 'speed', 'emotion', 'filter'] as const
  const riskKeys = ['dynamicSl', 'maxDrawdown', 'positionSize', 'volatility'] as const
  const execKeys = ['concurrent', 'slippage', 'funding', 'audit'] as const

  const metrics = [
    { key: 'winRate', accent: 0 },
    { key: 'profitFactor', accent: 1 },
    { key: 'maxDrawdown', accent: 2 },
    { key: 'totalReturn', accent: 3 },
    { key: 'tradeCount', accent: 4 },
  ] as const

  return (
    <Layout>
      <PageHeader
        kicker={t('strategies.kicker')}
        title={t('strategies.title')}
        subtitle={t('strategies.subtitle')}
      />

      <GlassCard className="p-8 section-mb-lg strategies-hero-card">
        <p className="strategies-lead">{t('strategies.coreLead')}</p>
        <ul className="strategies-bullet-list">
          {[1, 2, 3, 4].map(i => (
            <li key={i}>{t(`strategies.corePoints.${i}`)}</li>
          ))}
        </ul>
      </GlassCard>

      <section className="strategies-section">
        <div className="strategies-section-head">
          <p className="framer-kicker">{t('strategies.aiKicker')}</p>
          <h2>{t('strategies.aiTitle')}</h2>
        </div>
        <div className="strategies-grid-2">
          {aiKeys.map((key, i) => {
            const Icon = AI_ICONS[i]
            return (
              <GlassCard key={key} className="p-6 strategies-feature-card" delay={i * 0.05}>
                <Icon size={22} className="strategies-icon" />
                <h3>{t(`strategies.aiCards.${key}.title`)}</h3>
                <p className="text-muted">{t(`strategies.aiCards.${key}.desc`)}</p>
              </GlassCard>
            )
          })}
        </div>
      </section>

      <section className="strategies-section">
        <div className="strategies-section-head">
          <p className="framer-kicker">{t('strategies.backtestKicker')}</p>
          <h2>{t('strategies.backtestTitle')}</h2>
          <p className="text-muted strategies-section-sub">{t('strategies.backtestHint')}</p>
        </div>
        <div className="strategies-metrics-grid">
          {metrics.map(({ key, accent }, i) => (
            <div
              key={key}
              className="glass framer-glass-cell framer-color-card strategies-metric-card"
              style={{
                '--card-bg': METRIC_BGS[accent],
                '--card-accent': METRIC_ACCENTS[accent],
              } as CSSProperties}
            >
              <strong>{t(`strategies.metrics.${key}.value`)}</strong>
              <span>{t(`strategies.metrics.${key}.label`)}</span>
            </div>
          ))}
        </div>
        <p className="text-muted strategies-disclaimer">{t('strategies.backtestDisclaimer')}</p>
      </section>

      <section className="strategies-section">
        <div className="strategies-section-head">
          <p className="framer-kicker">{t('strategies.riskKicker')}</p>
          <h2>{t('strategies.riskTitle')}</h2>
        </div>
        <div className="strategies-grid-2">
          {riskKeys.map((key, i) => (
            <GlassCard key={key} className="p-6 strategies-feature-card" delay={i * 0.05}>
              <Shield size={20} className="strategies-icon" />
              <h3>{t(`strategies.riskItems.${key}.title`)}</h3>
              <p className="text-muted">{t(`strategies.riskItems.${key}.desc`)}</p>
            </GlassCard>
          ))}
        </div>
      </section>

      <section className="strategies-section">
        <div className="strategies-section-head">
          <p className="framer-kicker">{t('strategies.execKicker')}</p>
          <h2>{t('strategies.execTitle')}</h2>
        </div>
        <div className="strategies-grid-2">
          {execKeys.map((key, i) => {
            const Icon = EXEC_ICONS[i]
            return (
              <GlassCard key={key} className="p-6 strategies-feature-card" delay={i * 0.05}>
                <Icon size={20} className="strategies-icon" />
                <h3>{t(`strategies.execItems.${key}.title`)}</h3>
                <p className="text-muted">{t(`strategies.execItems.${key}.desc`)}</p>
              </GlassCard>
            )
          })}
        </div>
      </section>
    </Layout>
  )
}
