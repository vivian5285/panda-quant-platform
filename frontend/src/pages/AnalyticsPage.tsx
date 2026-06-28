import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import Skeleton from '../components/ui/Skeleton'
import { userApi } from '../api'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'

export default function Analytics() {
  const { t } = useI18n()
  const { theme } = useTheme()
  const [a, setA] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    userApi.analytics(90).then(setA).finally(() => setLoading(false))
  }, [])

  const isDark = theme === 'dark'
  const barOption = {
    backgroundColor: 'transparent',
    grid: { top: 20, right: 16, bottom: 30, left: 44 },
    xAxis: { type: 'category', data: a?.daily_series?.slice(-14).map((d: any) => d.date.slice(5)) || [], axisLabel: { fontSize: 10, color: isDark ? '#6b756d' : '#8a938e' } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: isDark ? 'rgba(59,130,246,0.08)' : 'rgba(59,130,246,0.06)' } }, axisLabel: { color: isDark ? '#6b756d' : '#8a938e' } },
    series: [{ type: 'bar', data: a?.daily_series?.slice(-14).map((d: any) => d.pnl) || [], itemStyle: { color: (p: any) => (p.value >= 0 ? '#22C55E' : '#EF4444'), borderRadius: [4, 4, 0, 0] } }],
  }

  const metrics = [
    { label: 'Sharpe', value: a?.sharpe },
    { label: 'Sortino', value: a?.sortino },
    { label: 'Calmar', value: a?.calmar },
    { label: 'Profit Factor', value: a?.profit_factor },
    { label: 'MDD %', value: a?.max_drawdown_pct },
    { label: 'SQN', value: a?.sqn },
    { label: 'Expectancy', value: a?.expectancy },
    { label: 'Kelly', value: a?.kelly },
    { label: t('dashboard.winRate'), value: `${a?.win_rate || 0}%` },
    { label: 'Monte Carlo (p50)', value: a?.monte_carlo?.median },
  ]

  return (
    <Layout>
      <PageHeader title={t('nav.analytics')} subtitle={t('analytics.subtitle')} />
      {loading ? (
        <div className="stat-grid">{[1, 2, 3, 4].map(n => <Skeleton key={n} height={88} />)}</div>
      ) : (
        <div className="stat-grid">
          {metrics.map((m, i) => (
            <StatCard key={m.label} label={m.label} value={String(m.value ?? '—')} delay={i * 0.05} />
          ))}
        </div>
      )}
      <GlassCard className="p-6" style={{ marginTop: 8 }}>
        <h3 className="card-heading">{t('analytics.dailyPnl')}</h3>
        {loading ? <Skeleton height={260} /> : <ReactECharts option={barOption} style={{ height: 260 }} />}
      </GlassCard>
    </Layout>
  )
}
