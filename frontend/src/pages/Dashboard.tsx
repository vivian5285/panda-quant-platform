import { Link } from 'react-router-dom'
import { useEffect, useState, useCallback, useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import Skeleton from '../components/ui/Skeleton'
import TradingViewWidget from '../components/landing/TradingViewWidget'
import { useDashboardWebSocket } from '../hooks/useDashboardWebSocket'
import { userApi } from '../api'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'
import { CHART } from '../theme/chartColors'
import { buildCalendarHeatmap } from '../utils/heatmapCalendar'
import SettlementGateBanner from '../components/SettlementGateBanner'

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
  const [signals, setSignals] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    return Promise.all([
      userApi.dashboard().then(setData),
      userApi.analytics(90).then(setAnalytics),
      userApi.trades().then((r: any[]) => setTrades(r.slice(0, 12))),
      userApi.signals(50).then(setSignals).catch(() => setSignals(null)),
    ]).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [load])

  useDashboardWebSocket(useCallback((msg: any) => {
    if (msg?.analytics) setAnalytics(msg.analytics)
    if (msg?.dashboard) setData(msg.dashboard)
    if (Array.isArray(msg?.trades)) setTrades(msg.trades.slice(0, 12))
  }, []))

  const isDark = theme === 'dark'
  const calendar = useMemo(
    () => buildCalendarHeatmap(analytics?.daily_series || []),
    [analytics?.daily_series],
  )

  const equityOption = {
    backgroundColor: 'transparent',
    grid: { top: 36, right: 16, bottom: 28, left: 52 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: isDark ? '#141414' : '#fff',
      borderColor: CHART.axisLine(isDark),
      textStyle: { color: CHART.label(isDark), fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: analytics?.daily_series?.slice(-30).map((d: any) => d.date.slice(5)) || [],
      axisLine: { lineStyle: { color: CHART.axisLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark), fontSize: 10 },
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark), fontSize: 11, formatter: (v: number) => `$${v}` },
    },
    series: [{
      data: analytics?.daily_series?.slice(-30).map((d: any) => d.cumulative) || [],
      type: 'line',
      smooth: 0.35,
      symbol: 'circle',
      symbolSize: 4,
      showSymbol: false,
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
      data: (analytics?.pnl_by_regime || [{ regime: 'Trend', pnl: 1 }, { regime: 'Range', pnl: 1 }]).map((r: any) => ({
        name: r.regime,
        value: Math.abs(r.pnl) || 0.01,
      })),
      color: CHART.pie,
    }],
  }

  const heatmapOption = {
    backgroundColor: 'transparent',
    tooltip: {
      formatter: (p: any) => {
        const [date, val] = p.data as [string, number]
        return `${date}<br/>PNL: ${fmt(val || 0)}`
      },
    },
    visualMap: {
      min: calendar.min,
      max: calendar.max,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: CHART.heatmap(isDark) },
      textStyle: { color: CHART.label(isDark), fontSize: 10 },
    },
    calendar: {
      top: 48,
      left: 40,
      right: 20,
      cellSize: ['auto', 14],
      range: calendar.range,
      itemStyle: { borderWidth: 3, borderColor: isDark ? '#000' : '#fff' },
      dayLabel: { color: CHART.axisLabel(isDark), fontSize: 10, firstDay: 1 },
      monthLabel: { color: CHART.axisLabel(isDark), fontSize: 10 },
      yearLabel: { show: false },
    },
    series: [{
      type: 'heatmap',
      coordinateSystem: 'calendar',
      data: calendar.data,
    }],
  }

  const tickerTrack = trades.length > 0 ? [...trades, ...trades] : []

  return (
    <Layout>
      <PageHeader
        title={t('dashboard.title')}
        action={
          <div className={`dash-live-badge${data?.settlement_blocked ? ' dash-live-badge--paused' : ''}`}>
            <div className={data?.settlement_blocked ? 'pulse-dot pulse-dot--muted' : 'pulse-dot'} />
            <span>{data?.settlement_blocked ? t('dashboard.settlementPaused') : t('dashboard.running')}</span>
          </div>
        }
      />

      <SettlementGateBanner
        blocked={data?.settlement_blocked}
        deferred={data?.settlement_fee_deferred}
        settlement={data?.pending_settlement}
      />

      {loading ? (
        <div className="stat-grid">{[1, 2, 3, 4].map(n => <Skeleton key={n} height={96} />)}</div>
      ) : (
        <div className="stat-grid dash-stat-grid">
          <StatCard label={t('dashboard.balance')} countUp={{ end: data?.balance || 0, prefix: '$', decimals: 2 }} delay={0.1} />
          <StatCard label={t('dashboard.tradeCyclePnl')} countUp={{ end: data?.trade_cycle_pnl || 0, pnl: true, decimals: 2 }} positive={(data?.trade_cycle_pnl || 0) >= 0} delay={0.12} />
          <StatCard label={t('dashboard.todayPnl')} countUp={{ end: data?.today_pnl || 0, pnl: true, decimals: 2 }} positive={(data?.today_pnl || 0) >= 0} delay={0.15} />
          <StatCard label={t('dashboard.totalPnl')} countUp={{ end: data?.total_pnl || 0, pnl: true, decimals: 2 }} positive={(data?.total_pnl || 0) >= 0} delay={0.18} />
          <StatCard label={t('dashboard.equityCyclePnl')} countUp={{ end: data?.cycle_pnl || 0, pnl: true, decimals: 2 }} positive={(data?.cycle_pnl || 0) >= 0} delay={0.2} />
        </div>
      )}

      {!loading && Math.abs(data?.profit_divergence || 0) >= 50 && (
        <GlassCard className="p-4 section-mb-md admin-alert-banner">
          <p className="text-sm">{t('dashboard.divergenceWarn', { amount: Math.abs(data?.profit_divergence || 0).toFixed(2) })}</p>
          <Link to="/snapshots" className="text-sm link-inline section-mt-xs">{t('dashboard.viewSnapshots')}</Link>
        </GlassCard>
      )}

      <div className="dash-main-grid">
        <GlassCard className="p-6" delay={0.22}>
          <h3 className="card-heading">{t('dashboard.equityCurve')}</h3>
          {loading ? <Skeleton height={280} /> : <ReactECharts option={equityOption} className="chart-h-md" />}
        </GlassCard>
        <GlassCard className="p-6 dash-ai-card" delay={0.24}>
          <h3 className="card-heading">{t('dashboard.aiScore')}</h3>
          {loading ? <Skeleton height={200} /> : (
            <>
              <div className="dash-ai-confidence">
                <span className="dash-ai-value">{signals?.confidence_score ?? 0}%</span>
                <span className="text-muted">{t('dashboard.aiConfidence')}</span>
              </div>
              <div className="dash-ai-meta">
                <div><span className="text-muted">{t('dashboard.aiBias')}</span><br /><strong>{signals?.direction_bias || t('dashboard.aiPending')}</strong></div>
                <div><span className="text-muted">{t('dashboard.aiSuccessRate')}</span><br /><strong>{signals?.success_rate ?? 0}%</strong></div>
                <div><span className="text-muted">{t('dashboard.aiLastSignal')}</span><br /><strong>{signals?.last_signal_at ? new Date(signals.last_signal_at).toLocaleString() : t('common.none')}</strong></div>
              </div>
            </>
          )}
        </GlassCard>
      </div>

      <GlassCard className="dash-ticker-strip" delay={0.12}>
        <div className="dash-ticker-label">{t('dashboard.liveTicker')}</div>
        {tickerTrack.length > 0 ? (
          <div className="recent-ticker">
            {tickerTrack.map((tr, i) => (
              <span key={`${tr.id}-${i}`} className={`ticker-item ${(tr.realized_pnl || 0) >= 0 ? 'up' : 'down'}`}>
                {tr.action || tr.side} · {tr.symbol} · {tr.quantity} · {fmt(tr.realized_pnl || 0)}
              </span>
            ))}
          </div>
        ) : (
          <p className="dash-ticker-empty">{t('dashboard.tickerEmpty')}</p>
        )}
      </GlassCard>

      {data?.open_position?.has_position && (
        <GlassCard className="p-6 section-mb-lg" delay={0.28}>
          <h3 className="card-heading">{t('dashboard.currentPosition')}</h3>
          <div className="stat-grid stat-grid-flush">
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.direction')}</p>
              <p className={data.open_position.side === 'LONG' ? 'text-green stat-value-xl' : 'text-red stat-value-xl'}>{data.open_position.side}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.qty')}</p>
              <p className="stat-value-xl">{data.open_position.qty} {t('admin.ethUnit')}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.entry')}</p>
              <p className="stat-value-xl">${data.open_position.entry_price?.toFixed(2)}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.floatingPnl')}</p>
              <p className={`stat-value-xl ${data.open_position.unrealized_pnl >= 0 ? 'text-green' : 'text-red'}`}>{fmt(data.open_position.unrealized_pnl)}</p>
            </div>
          </div>
        </GlassCard>
      )}

      <GlassCard className="p-6 section-mb-lg" delay={0.3}>
        <h3 className="card-heading">{t('dashboard.recentOrders')}</h3>
        {trades.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('trades.signal')}</th>
                  <th>{t('trades.side')}</th>
                  <th>{t('common.time')}</th>
                  <th>{t('trades.pnl')}</th>
                  <th>{t('common.status')}</th>
                </tr>
              </thead>
              <tbody>
                {trades.map(tr => (
                  <tr key={tr.id}>
                    <td><span className="badge badge-gray">{tr.action || '—'}</span></td>
                    <td>{tr.side}</td>
                    <td className="text-muted">{tr.closed_at ? new Date(tr.closed_at).toLocaleString() : new Date(tr.created_at).toLocaleString()}</td>
                    <td className={(tr.realized_pnl || 0) >= 0 ? 'text-green' : 'text-red'}>{fmt(tr.realized_pnl || 0)}</td>
                    <td>{tr.status || 'FILLED'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-muted dash-empty-hint">{t('trades.empty')}</p>
        )}
      </GlassCard>

      <GlassCard className="p-4 dash-tv-card" delay={0.32}>
        <h3 className="card-heading">{t('dashboard.marketChart')}</h3>
        <TradingViewWidget
          scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
          className="chart-h-lg"
          config={{
            autosize: true,
            symbol: 'BINANCE:ETHUSDT',
            interval: '15',
            timezone: 'Etc/UTC',
            theme: isDark ? 'dark' : 'light',
            style: '1',
            locale: locale === 'zh' ? 'zh_CN' : 'en',
            enable_publishing: false,
            hide_top_toolbar: true,
            hide_legend: false,
            allow_symbol_change: false,
            backgroundColor: 'transparent',
          }}
        />
      </GlassCard>

      <div className="dash-chart-grid">
        <GlassCard className="p-6" delay={0.35}>
          <h3 className="card-heading">{t('dashboard.pnlSource')}</h3>
          {loading ? <Skeleton height={280} /> : <ReactECharts option={pieOption} className="chart-h-md" />}
        </GlassCard>
        <GlassCard className="p-6 dash-heatmap-card" delay={0.38}>
          <h3 className="card-heading">{t('dashboard.heatmap')}</h3>
          {loading ? <Skeleton height={220} /> : (
            calendar.data.length > 0
              ? <ReactECharts option={heatmapOption} className="chart-h-heatmap" />
              : <p className="text-muted dash-empty-hint">{t('dashboard.heatmapEmpty')}</p>
          )}
        </GlassCard>
      </div>
    </Layout>
  )
}
