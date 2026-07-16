import { useEffect, useState, useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import Skeleton from '../components/ui/Skeleton'
import { userApi } from '../api'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'
import { CHART } from '../theme/chartColors'
import { buildCalendarHeatmap } from '../utils/heatmapCalendar'
import { mcBucketLabel } from '../utils/monteCarlo'
import SymbolPnlStrip from '../components/SymbolPnlStrip'

function fmt(n: number) {
  const prefix = n >= 0 ? '+$' : '-$'
  return prefix + Math.abs(n).toFixed(2)
}

export default function Analytics() {
  const { t } = useI18n()
  const { theme } = useTheme()
  const [a, setA] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    userApi.analytics(90, true).then(setA).finally(() => setLoading(false))
  }, [])

  const isDark = theme === 'dark'
  const calendar = useMemo(
    () => buildCalendarHeatmap(a?.daily_series || []),
    [a?.daily_series],
  )

  const barOption = {
    backgroundColor: 'transparent',
    grid: { top: 20, right: 16, bottom: 30, left: 44 },
    xAxis: {
      type: 'category',
      data: a?.daily_series?.slice(-14).map((d: any) => d.date.slice(5)) || [],
      axisLabel: { fontSize: 10, color: CHART.axisLabel(isDark) },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark) },
    },
    series: [{
      type: 'bar',
      data: a?.daily_series?.slice(-14).map((d: any) => d.pnl) || [],
      itemStyle: {
        color: (p: { value: number }) => (p.value >= 0 ? CHART.green : CHART.red),
        borderRadius: [4, 4, 0, 0],
      },
    }],
  }

  const heatmapOption = {
    backgroundColor: 'transparent',
    tooltip: {
      formatter: (p: { data: [string, number] }) => {
        const [date, val] = p.data
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
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: calendar.data }],
  }

  const metrics = [
    { label: t('analytics.sharpe'), countUp: { end: a?.sharpe || 0, decimals: 2 } },
    { label: t('analytics.sortino'), countUp: { end: a?.sortino || 0, decimals: 2 } },
    { label: t('analytics.calmar'), countUp: { end: a?.calmar || 0, decimals: 2 } },
    { label: t('analytics.profitFactor'), countUp: { end: a?.profit_factor || 0, decimals: 2 } },
    { label: t('analytics.mdd'), countUp: { end: a?.max_drawdown_pct || 0, suffix: '%', decimals: 1 } },
    { label: t('analytics.sqn'), countUp: { end: a?.sqn || 0, decimals: 2 } },
    { label: t('analytics.expectancy'), countUp: { end: a?.expectancy || 0, pnl: true, decimals: 2 } },
    { label: t('analytics.kelly'), countUp: { end: a?.kelly || 0, decimals: 2 } },
    { label: t('dashboard.winRate'), countUp: { end: a?.win_rate || 0, suffix: '%', decimals: 1 } },
  ]

  const mc = a?.monte_carlo as {
    p5?: number
    median?: number
    p95?: number
    histogram?: { label: string; count: number }[]
  } | undefined
  const mcMin = mc?.p5 ?? 0
  const mcMax = mc?.p95 ?? 0
  const mcSpan = Math.max(mcMax - mcMin, 0.01)
  const mcMedianPct = mc?.median != null ? ((mc.median - mcMin) / mcSpan) * 100 : 50

  const riskChartOption = useMemo(() => ({
    backgroundColor: 'transparent',
    grid: { top: 20, right: 16, bottom: 28, left: 44 },
    xAxis: {
      type: 'category',
      data: [t('analytics.sharpe'), t('analytics.sortino'), t('analytics.profitFactor'), t('analytics.mdd')],
      axisLabel: { fontSize: 10, color: CHART.axisLabel(isDark) },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark) },
    },
    series: [{
      type: 'bar',
      data: [a?.sharpe ?? a?.sharpe_ratio ?? 0, a?.sortino ?? a?.sortino_ratio ?? 0, a?.profit_factor || 0, a?.max_drawdown_pct || 0],
      itemStyle: { color: '#3B82F6', borderRadius: [4, 4, 0, 0] },
    }],
  }), [a, isDark, t])

  const mcHistOption = useMemo(() => {
    const hist = mc?.histogram || []
    const p5Label = mc?.p5 != null ? mcBucketLabel(mc.p5, hist) : ''
    const p95Label = mc?.p95 != null ? mcBucketLabel(mc.p95, hist) : ''
    return {
      backgroundColor: 'transparent',
      grid: { top: 28, right: 12, bottom: 28, left: 40 },
      tooltip: {
        trigger: 'axis',
        formatter: (p: { name: string; value: number }[]) => {
          const row = p[0]
          return row ? `${row.name}<br/>${t('analytics.monteCarloDist')}: ${row.value}` : ''
        },
      },
      xAxis: {
        type: 'category',
        data: hist.map(h => h.label),
        axisLabel: { fontSize: 9, color: CHART.axisLabel(isDark), rotate: hist.length > 8 ? 35 : 0 },
        axisLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      },
      yAxis: {
        type: 'value',
        name: t('analytics.monteCarloDist'),
        nameTextStyle: { color: CHART.axisLabel(isDark), fontSize: 10 },
        splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
        axisLabel: { color: CHART.axisLabel(isDark), fontSize: 10 },
      },
      series: [{
        type: 'bar',
        data: hist.map(h => h.count),
        itemStyle: {
          color: CHART.green,
          borderRadius: [4, 4, 0, 0],
        },
        markLine: p5Label && p95Label ? {
          symbol: ['none', 'none'],
          lineStyle: { type: 'dashed', width: 1.5 },
          label: {
            fontSize: 10,
            color: CHART.label(isDark),
            formatter: (p: { name: string }) => p.name,
          },
          data: [
            {
              xAxis: p5Label,
              name: `${t('analytics.monteCarloP5')} ${mc?.p5?.toFixed(2)}`,
              lineStyle: { color: CHART.red },
            },
            {
              xAxis: p95Label,
              name: `${t('analytics.monteCarloP95')} ${mc?.p95?.toFixed(2)}`,
              lineStyle: { color: '#22c55e' },
            },
          ],
        } : undefined,
      }],
    }
  }, [mc?.histogram, mc?.p5, mc?.p95, isDark, t])

  return (
    <Layout>
      <PageHeader title={t('nav.analytics')} subtitle={t('analytics.subtitle')} />
      {loading ? (
        <div className="stat-grid">{[1, 2, 3, 4].map(n => <Skeleton key={n} height={88} />)}</div>
      ) : (
        <div className="stat-grid">
          {metrics.map((m, i) => (
            <StatCard key={m.label} label={m.label} countUp={m.countUp} delay={i * 0.05} />
          ))}
        </div>
      )}
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('analytics.riskChartTitle')}</h3>
        {loading ? <Skeleton height={220} /> : (
          <ReactECharts option={riskChartOption} style={{ height: 220 }} />
        )}
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('analytics.monteCarloTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('analytics.monteCarloHint')}</p>
        {loading ? (
          <Skeleton height={72} />
        ) : mc ? (
          <>
            <div className="monte-carlo-range section-mb-md">
              <div className="monte-carlo-track">
                <div className="monte-carlo-fill" />
                <div
                  className="monte-carlo-marker"
                  style={{ '--mc-median-pct': `${mcMedianPct}%` } as React.CSSProperties}
                />
              </div>
              <div className="monte-carlo-labels">
                <span><em>{t('analytics.monteCarloP5')}</em> {mc.p5?.toFixed(2) ?? '—'}</span>
                <span><em>{t('analytics.monteCarloP50')}</em> {mc.median?.toFixed(2) ?? '—'}</span>
                <span><em>{t('analytics.monteCarloP95')}</em> {mc.p95?.toFixed(2) ?? '—'}</span>
              </div>
            </div>
            {mc.histogram && mc.histogram.length > 0 && (
              <>
                <h4 className="card-heading text-sm section-mb-sm">{t('analytics.monteCarloDist')}</h4>
                <ReactECharts option={mcHistOption} className="chart-h-sm" />
              </>
            )}
          </>
        ) : (
          <p className="text-muted">{t('common.none')}</p>
        )}
      </GlassCard>
      <div className="dash-chart-grid">
        <GlassCard className="p-6">
          <h3 className="card-heading">{t('analytics.dailyPnl')}</h3>
          {loading ? <Skeleton height={260} /> : <ReactECharts option={barOption} className="chart-h-sm" />}
        </GlassCard>
        <GlassCard className="p-6">
          <h3 className="card-heading">{t('dashboard.pnlSource')}</h3>
          {loading ? <Skeleton height={260} /> : (
            <ReactECharts
              option={{
                backgroundColor: 'transparent',
                tooltip: { trigger: 'item' },
                series: [{
                  type: 'pie',
                  radius: ['42%', '68%'],
                  itemStyle: { borderRadius: 8, borderColor: CHART.pieBorder(isDark), borderWidth: 2 },
                  label: { color: CHART.label(isDark), fontSize: 11 },
                  data: (a?.pnl_by_regime || [{ regime: 'Trend', pnl: 1 }]).map((r: { regime: string; pnl: number }) => ({
                    name: r.regime,
                    value: Math.abs(r.pnl) || 0.01,
                  })),
                  color: CHART.pie,
                }],
              }}
              className="chart-h-sm"
            />
          )}
        </GlassCard>
      </div>
      {(a?.pnl_by_symbol?.length > 0) && (
        <GlassCard className="p-6 section-mb-lg">
          <SymbolPnlStrip
            title={t('analytics.pnlBySymbol')}
            hint={
              a?.window_start
                ? (a.since_activation
                  ? t('analytics.sinceActivationHint', { date: a.window_start })
                  : t('analytics.windowHint', { date: a.window_start }))
                : t('dashboard.dualSymbolHint')
            }
            rows={a.pnl_by_symbol}
          />
        </GlassCard>
      )}
      <GlassCard className="p-6 dash-heatmap-card mt-xs">
        <h3 className="card-heading">{t('dashboard.heatmap')}</h3>
        {loading ? <Skeleton height={220} /> : (
          calendar.data.length > 0
              ? <ReactECharts option={heatmapOption} className="chart-h-heatmap" />
            : <p className="text-muted dash-empty-hint">{t('dashboard.heatmapEmpty')}</p>
        )}
      </GlassCard>
    </Layout>
  )
}
