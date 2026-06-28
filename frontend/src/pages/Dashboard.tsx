import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'

function fmt(n: number) {
  const prefix = n >= 0 ? '+$' : '-$'
  return prefix + Math.abs(n).toFixed(2)
}

export default function Dashboard() {
  const { t, locale } = useI18n()
  const { theme } = useTheme()
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    userApi.dashboard().then(setData).catch(console.error)
    const timer = setInterval(() => userApi.dashboard().then(setData), 30000)
    return () => clearInterval(timer)
  }, [])

  const weekdays = locale === 'zh'
    ? ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    : ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  const isDark = theme === 'dark'
  const chartOption = {
    backgroundColor: 'transparent',
    grid: { top: 30, right: 20, bottom: 30, left: 50 },
    xAxis: {
      type: 'category',
      data: weekdays,
      axisLine: { lineStyle: { color: isDark ? 'rgba(52,199,89,0.15)' : 'rgba(52,199,89,0.12)' } },
      axisLabel: { color: isDark ? '#6b756d' : '#8a938e', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: isDark ? 'rgba(52,199,89,0.08)' : 'rgba(52,199,89,0.06)' } },
      axisLabel: { color: isDark ? '#6b756d' : '#8a938e', fontSize: 11 },
    },
    series: [{
      data: [120, 280, -50, 390, 210, 328, data?.today_pnl || 0],
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { color: isDark ? '#30d158' : '#34c759', width: 2 },
      itemStyle: { color: isDark ? '#30d158' : '#34c759' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: isDark ? 'rgba(48,209,88,0.2)' : 'rgba(52,199,89,0.15)' },
            { offset: 1, color: 'rgba(0,0,0,0)' },
          ],
        },
      },
    }],
  }

  return (
    <Layout>
      <PageHeader
        title={t('dashboard.title')}
        action={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="pulse-dot" />
            <span className="text-muted" style={{ fontSize: 13 }}>{t('dashboard.running')}</span>
          </div>
        }
      />

      <div className="stat-grid">
        <StatCard label={t('dashboard.balance')} value={`$${(data?.balance || 0).toFixed(2)}`} delay={0.1} />
        <StatCard label={t('dashboard.unrealized')} value={fmt(data?.unrealized_pnl || 0)} positive={(data?.unrealized_pnl || 0) >= 0} delay={0.15} />
        <StatCard label={t('dashboard.cyclePnl')} value={fmt(data?.cycle_pnl || 0)} positive={(data?.cycle_pnl || 0) >= 0} delay={0.18} />
        <StatCard label={t('dashboard.principal')} value={`$${(data?.initial_principal || 0).toFixed(2)}`} delay={0.2} />
        <StatCard label={t('dashboard.todayPnl')} value={fmt(data?.today_pnl || 0)} positive={(data?.today_pnl || 0) >= 0} delay={0.22} />
        <StatCard label={t('dashboard.totalPnl')} value={fmt(data?.total_pnl || 0)} positive={(data?.total_pnl || 0) >= 0} delay={0.25} />
      </div>

      <GlassCard className="p-6" delay={0.3} style={{ marginBottom: 24 }}>
        <h3 className="card-heading">{t('dashboard.pnlChart')}</h3>
        <ReactECharts option={chartOption} style={{ height: 280 }} />
      </GlassCard>

      {data?.open_position?.has_position && (
        <GlassCard green className="p-6" delay={0.35}>
          <h3 className="card-heading">{t('dashboard.currentPosition')}</h3>
          <div className="stat-grid" style={{ marginBottom: 0 }}>
            <div className="stat-tile">
              <p className="text-muted" style={{ fontSize: 12 }}>{t('dashboard.direction')}</p>
              <p className={data.open_position.side === 'LONG' ? 'text-green' : 'text-red'} style={{ fontSize: 18, fontWeight: 600 }}>
                {data.open_position.side}
              </p>
            </div>
            <div className="stat-tile">
              <p className="text-muted" style={{ fontSize: 12 }}>{t('dashboard.qty')}</p>
              <p style={{ fontSize: 18, fontWeight: 600 }}>{data.open_position.qty} ETH</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted" style={{ fontSize: 12 }}>{t('dashboard.entry')}</p>
              <p style={{ fontSize: 18, fontWeight: 600 }}>${data.open_position.entry_price?.toFixed(2)}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted" style={{ fontSize: 12 }}>{t('dashboard.floatingPnl')}</p>
              <p className={data.open_position.unrealized_pnl >= 0 ? 'text-green' : 'text-red'} style={{ fontSize: 18, fontWeight: 600 }}>
                {fmt(data.open_position.unrealized_pnl)}
              </p>
            </div>
          </div>
        </GlassCard>
      )}
    </Layout>
  )
}
