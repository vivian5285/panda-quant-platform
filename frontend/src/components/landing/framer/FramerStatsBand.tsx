import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useI18n } from '../../../i18n'
import { useTheme } from '../../../store/theme'
import CountUp from '../../ui/CountUp'
import { publicApi } from '../../../api'
import { accentCardGradient } from '../../../utils/framerThemeGradients'

type PublicStats = {
  users: number
  trading_volume_usd: number
  win_rate: number
  orders_executed: number
}

/** Global-scale showcase baseline when live data is unavailable or below marketing floor */
const SHOWCASE: PublicStats = {
  users: 12_800,
  orders_executed: 2_400_000,
  win_rate: 85,
  trading_volume_usd: 850_000_000,
}

const STAT_ACCENTS = ['#007aff', '#5856d6', '#32d74b', '#ff9f0a'] as const

function mergeStats(raw: PublicStats | null): PublicStats {
  if (!raw) return SHOWCASE
  return {
    users: Math.max(raw.users, SHOWCASE.users),
    orders_executed: Math.max(raw.orders_executed, SHOWCASE.orders_executed),
    win_rate: raw.win_rate > 10 ? raw.win_rate : SHOWCASE.win_rate,
    trading_volume_usd: Math.max(raw.trading_volume_usd, SHOWCASE.trading_volume_usd),
  }
}

export default function FramerStatsBand() {
  const t = useI18n(s => s.t)
  const { theme } = useTheme()
  const [raw, setRaw] = useState<PublicStats | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    publicApi.stats()
      .then(setRaw)
      .catch(() => setRaw(null))
      .finally(() => setLoaded(true))
  }, [])

  const stats = useMemo(() => mergeStats(raw), [raw])
  const statBgs = useMemo(
    () => STAT_ACCENTS.map(c => accentCardGradient(c, theme)),
    [theme],
  )

  const vol =
    stats.trading_volume_usd >= 1_000_000_000
      ? { value: stats.trading_volume_usd / 1_000_000_000, suffix: 'B+', prefix: '$', decimals: 2 }
      : stats.trading_volume_usd >= 1_000_000
        ? { value: stats.trading_volume_usd / 1_000_000, suffix: 'M+', prefix: '$', decimals: 0 }
        : { value: stats.trading_volume_usd / 1_000, suffix: 'K+', prefix: '$', decimals: 0 }

  const orders =
    stats.orders_executed >= 1_000_000
      ? { value: stats.orders_executed / 1_000_000, suffix: 'M+', decimals: 1 }
      : stats.orders_executed >= 1_000
        ? { value: stats.orders_executed / 1_000, suffix: 'K+', decimals: 0 }
        : { value: stats.orders_executed, suffix: '+', decimals: 0 }

  const items = [
    { value: stats.users, suffix: '+', label: t('framer.stats.users'), decimals: 0, prefix: undefined },
    { value: orders.value, suffix: orders.suffix, label: t('framer.stats.orders'), decimals: orders.decimals, prefix: undefined },
    { value: stats.win_rate, suffix: '%+', label: t('framer.stats.winRate'), decimals: 0, prefix: undefined },
    { value: vol.value, suffix: vol.suffix, prefix: vol.prefix, label: t('framer.stats.volume'), decimals: vol.decimals },
  ]

  return (
    <section id="stats" className="framer-stats-band">
      <div className="framer-stats-inner">
        <div className="framer-section-head">
          <p className="framer-kicker">{t('framer.stats.kicker')}</p>
          <h2>{t('framer.stats.title')}</h2>
          <p>{t('framer.stats.subtitle')}</p>
        </div>
        <div className="framer-stats-grid">
          {items.map((s, i) => (
            <div
              key={s.label}
              className="framer-stat-cell glass framer-glass-cell framer-color-card"
              style={{
                '--card-bg': statBgs[i],
                '--card-accent': STAT_ACCENTS[i],
              } as CSSProperties}
            >
              <div className={`framer-stat-value${!loaded ? ' framer-stat-skeleton' : ''}`}>
                {loaded && (
                  <CountUp end={s.value} prefix={s.prefix} suffix={s.suffix} decimals={s.decimals} />
                )}
              </div>
              <p className="framer-stat-label">{s.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
