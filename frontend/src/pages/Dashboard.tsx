import { useEffect, useState, useCallback } from 'react'
import ReactECharts from 'echarts-for-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import Skeleton from '../components/ui/Skeleton'
import { useDashboardWebSocket } from '../hooks/useDashboardWebSocket'
import { userApi } from '../api'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'
import { CHART } from '../theme/chartColors'

function fmt(n: number) {
  const prefix = n >= 0 ? '+$' : '-$'
  return prefix + Math.abs(n).toFixed(2)
}

export default function Dashboard() {
  const { t, locale } = useI18n()
  const { theme } = useTheme()
  const [data, setData] = useState<any>(null)
  const [analytics, setAnalytics] = useState<any>(null)
  const [trades, setTrades] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => Promise.all([
      userApi.dashboard().then(setData),
      userApi.analytics(90).then(setAnalytics),
      userApi.trades().then((r: any[]) => setTrades(r.slice(0, 8))),
    ]).finally(() => setLoading(false))
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  useDashboardWebSocket(useCallback((msg: any) => {
    if (msg?.analytics) setAnalytics(msg.analytics)
  }, []))

  const isDark = theme === 'dark'
  const weekLabels = analytics?.week_labels?.map((d: string) => {
    const dt = new Date(d)
    return locale === 'zh'
      ? `${dt.getMonth() + 1}/${dt.getDate()}`
      : dt.toLocaleDateString('en-US', { weekday: 'short' })
  }) || []

  const equityOption = {
    backgroundColor: 'transparent',
    grid: { top: 30, right: 20, bottom: 30, left: 50 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: analytics?.daily_series?.slice(-30).map((d: any) => d.date.slice(5)) || weekLabels,
      axisLine: { lineStyle: { color: CHART.axisLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark), fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark), fontSize: 11 },
    },
    series: [{
      data: analytics?.daily_series?.slice(-30).map((d: any) => d.cumulative)
        || analytics?.week_values || [],
      type: 'line',
      smooth: true,
      symbol: 'none',
      lineStyle: { color: CHART.green, width: 2.5 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: CHART.greenDim },
            { offset: 1, color: 'rgba(0,0,0,0)' },
          ],
        },
      },
    }],
  }

  const pieOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['42%', '68%'],
      itemStyle: { borderRadius: 8, borderColor: CHART.pieBorder(isDark), borderWidth: 2 },
      label: { color: CHART.label(isDark), fontSize: 11 },
      data: (analytics?.pnl_by_regime || [{ regime: 'R3', pnl: 0 }]).map((r: any) => ({
        name: r.regime,
        value: Math.abs(r.pnl) || 0.01,
      })),
      color: CHART.pie,
    }],
  }

  const heatmapData = analytics?.daily_series?.slice(-84) || []
  const heatmapOption = {
    backgroundColor: 'transparent',
    tooltip: { position: 'top' },
    grid: { top: 10, right: 10, bottom: 30, left: 40 },
    xAxis: { type: 'category', data: ['', '', '', '', '', '', ''], show: false },
    yAxis: { type: 'category', data: ['W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8', 'W9', 'W10', 'W11', 'W12'], axisLabel: { fontSize: 9, color: CHART.axisLabel(isDark) } },
    visualMap: {
      min: -100, max: 100, calculable: false, orient: 'horizontal', left: 'center', bottom: 0,
      inRange: { color: CHART.heatmap(isDark) },
      textStyle: { color: CHART.label(isDark), fontSize: 10 },
      show: false,
    },
    series: [{
      type: 'heatmap',
      data: heatmapData.map((d: any, i: number) => [i % 7, Math.floor(i / 7), d.pnl]),
      emphasis: { itemStyle: { shadowBlur: 8 } },
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

      {loading ? (
        <div className="stat-grid">{[1, 2, 3, 4].map(n => <Skeleton key={n} height={88} />)}</div>
      ) : (
        <div className="stat-grid">
          <StatCard label={t('dashboard.balance')} countUp={{ end: data?.balance || 0, prefix: '$', decimals: 2 }} delay={0.1} />
          <StatCard label={t('dashboard.todayPnl')} countUp={{ end: data?.today_pnl || 0, pnl: true, decimals: 2 }} positive={(data?.today_pnl || 0) >= 0} delay={0.15} />
          <StatCard label={t('dashboard.winRate')} countUp={{ end: analytics?.win_rate || 0, suffix: '%', decimals: 1 }} delay={0.18} />
          <StatCard label={t('dashboard.totalPnl')} countUp={{ end: data?.total_pnl || 0, pnl: true, decimals: 2 }} positive={(data?.total_pnl || 0) >= 0} delay={0.2} />
        </div>
      )}

      <div className="dash-chart-grid">
        <GlassCard className="p-6" delay={0.25}>
          <h3 className="card-heading">{t('dashboard.pnlChart')}</h3>
          {loading ? <Skeleton height={280} /> : <ReactECharts option={equityOption} style={{ height: 280 }} />}
        </GlassCard>
        <GlassCard className="p-6" delay={0.28}>
          <h3 className="card-heading">{t('dashboard.pnlSource')}</h3>
          {loading ? <Skeleton height={280} /> : <ReactECharts option={pieOption} style={{ height: 280 }} />}
        </GlassCard>
      </div>

      <GlassCard className="p-6" delay={0.32} style={{ marginBottom: 24 }}>
        <h3 className="card-heading">{t('dashboard.heatmap')}</h3>
        {loading ? <Skeleton height={180} /> : <ReactECharts option={heatmapOption} style={{ height: 180 }} />}
      </GlassCard>

      {trades.length > 0 && (
        <GlassCard className="p-6" delay={0.35}>
          <h3 className="card-heading">{t('dashboard.recentOrders')}</h3>
          <div className="recent-ticker">
            {[...trades, ...trades].map((tr, i) => (
              <span key={`${tr.id}-${i}`} className={`ticker-item ${(tr.realized_pnl || 0) >= 0 ? 'up' : 'down'}`}>
                {tr.side} · {tr.symbol} · {fmt(tr.realized_pnl || 0)}
              </span>
            ))}
          </div>
        </GlassCard>
      )}

      {data?.open_position?.has_position && (
        <GlassCard className="p-6" delay={0.38} style={{ marginTop: 24 }}>
          <h3 className="card-heading">{t('dashboard.currentPosition')}</h3>
          <div className="stat-grid" style={{ marginBottom: 0 }}>
            <div className="stat-tile">
              <p className="text-muted" style={{ fontSize: 12 }}>{t('dashboard.direction')}</p>
              <p className={data.open_position.side === 'LONG' ? 'text-green' : 'text-red'} style={{ fontSize: 18, fontWeight: 600 }}>{data.open_position.side}</p>
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
              <p className={data.open_position.unrealized_pnl >= 0 ? 'text-green' : 'text-red'} style={{ fontSize: 18, fontWeight: 600 }}>{fmt(data.open_position.unrealized_pnl)}</p>
            </div>
          </div>
        </GlassCard>
      )}
    </Layout>
  )
}
