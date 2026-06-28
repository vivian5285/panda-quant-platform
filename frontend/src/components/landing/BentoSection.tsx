import { useEffect, useState } from 'react'
import {
  BarChart3, Bot, LineChart, Radar, Shield, Users, Wallet, Zap,
} from 'lucide-react'
import { useI18n } from '../../i18n'
import BentoCard from '../ui/BentoCard'
import ScrollReveal from '../ui/ScrollReveal'
import CountUp from '../ui/CountUp'
import { publicApi } from '../../api'

const BENTO = [
  { icon: Bot, key: 'ai', span: 2 as const },
  { icon: Zap, key: 'auto', span: 1 as const },
  { icon: Wallet, key: 'binance', span: 1 as const },
  { icon: Shield, key: 'risk', span: 1 as const },
  { icon: LineChart, key: 'dashboard', span: 1 as const },
  { icon: Users, key: 'referral', span: 1 as const },
  { icon: BarChart3, key: 'settlement', span: 1 as const },
  { icon: Radar, key: 'analytics', span: 2 as const },
]

export default function BentoSection() {
  const t = useI18n(s => s.t)
  const [stats, setStats] = useState({ users: 1000, trading_volume_usd: 500000000, uptime_pct: 99.99, orders_executed: 1200000 })

  useEffect(() => {
    publicApi.stats().then(setStats).catch(() => {})
  }, [])

  const formatVolume = (v: number) => {
    if (v >= 1_000_000) return { value: v / 1_000_000, suffix: 'M+', prefix: '$', decimals: 1 }
    if (v >= 1_000) return { value: v / 1_000, suffix: 'K+', prefix: '$', decimals: 0 }
    return { value: v, suffix: '', prefix: '$', decimals: 0 }
  }

  const vol = formatVolume(stats.trading_volume_usd)
  const ordersDisplay = stats.orders_executed >= 1_000_000
    ? { value: stats.orders_executed / 1_000_000, suffix: 'M+', decimals: 1 }
    : stats.orders_executed >= 1_000
      ? { value: stats.orders_executed / 1_000, suffix: 'K+', decimals: 0 }
      : { value: stats.orders_executed, suffix: '', decimals: 0 }

  return (
    <>
      <section id="platform" className="landing-section">
        <ScrollReveal className="landing-section-head">
          <p className="landing-kicker">{t('saas.bento.kicker')}</p>
          <h2>{t('saas.bento.title')}</h2>
          <p>{t('saas.bento.subtitle')}</p>
        </ScrollReveal>
        <div className="bento-grid">
          {BENTO.map(({ icon, key, span }, i) => (
            <BentoCard
              key={key}
              icon={icon}
              span={span}
              delay={i * 0.05}
              title={t(`saas.bento.items.${key}.title`)}
              desc={t(`saas.bento.items.${key}.desc`)}
            />
          ))}
        </div>
      </section>

      <section id="stats" className="landing-section landing-section-alt">
        <ScrollReveal className="landing-section-head">
          <p className="landing-kicker">{t('saas.stats.kicker')}</p>
          <h2>{t('saas.stats.title')}</h2>
        </ScrollReveal>
        <div className="saas-stats-grid">
          {[
            { value: stats.users, suffix: stats.users > 0 ? '+' : '', label: t('saas.stats.users'), decimals: 0 },
            { value: vol.value, suffix: vol.suffix, label: t('saas.stats.volume'), prefix: vol.prefix, decimals: vol.decimals },
            { value: stats.uptime_pct, suffix: '%', label: t('saas.stats.uptime'), decimals: 2 },
            { value: ordersDisplay.value, suffix: ordersDisplay.suffix, label: t('saas.stats.orders'), decimals: ordersDisplay.decimals },
          ].map((s, i) => (
            <ScrollReveal key={s.label} delay={i * 0.08} className="saas-stat-card glass">
              <div className="saas-stat-value">
                <CountUp end={s.value} prefix={s.prefix} suffix={s.suffix} decimals={s.decimals} />
              </div>
              <p>{s.label}</p>
            </ScrollReveal>
          ))}
        </div>
      </section>
    </>
  )
}
