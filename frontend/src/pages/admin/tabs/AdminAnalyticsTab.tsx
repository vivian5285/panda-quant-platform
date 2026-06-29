import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import ReactECharts from 'echarts-for-react'
import { useAdmin } from '../AdminContext'

export default function AdminAnalyticsTab() {
  const {
    t, platformAnalytics, monitor, online, confirmedRevenue,
    execBarOption, breakdownPieOption, errorsBarOption, signalCoverageOption,
  } = useAdmin()

  return (
    <>
      <div className="stat-grid">
        <StatCard label={t('admin.totalUsers')} countUp={{ end: platformAnalytics?.total_users || 0, decimals: 0 }} />
        <StatCard label={t('admin.activeApiUsers')} countUp={{ end: platformAnalytics?.active_api_users || 0, decimals: 0 }} />
        <StatCard label={t('admin.platformWinRate')} countUp={{ end: platformAnalytics?.win_rate || 0, suffix: '%', decimals: 1 }} />
        <StatCard label={t('admin.cumulativePlatformPnl')} countUp={{ end: platformAnalytics?.cumulative_pnl || 0, prefix: '$', decimals: 2, pnl: true }} />
        <StatCard label={t('admin.confirmedRevenue')} countUp={{ end: confirmedRevenue, prefix: '$', decimals: 2 }} />
        <StatCard label={t('admin.binanceLatency')} value={monitor?.binance_latency_ms > 0 ? `${monitor.binance_latency_ms}ms` : '—'} />
      </div>
      <div className="stat-grid section-mt-md">
        <GlassCard className="p-6">
          <h3 className="card-heading">{t('admin.platformExecutions')}</h3>
          <ReactECharts option={execBarOption} className="chart-h-sm" />
        </GlassCard>
        <GlassCard className="p-6">
          <h3 className="card-heading">{t('admin.executionBreakdown')}</h3>
          <ReactECharts option={breakdownPieOption} className="chart-h-sm" />
        </GlassCard>
      </div>
      <GlassCard className="p-6 section-mt-md">
        <h3 className="card-heading">{t('admin.signalCoverage')}</h3>
        {(platformAnalytics?.signal_coverage_series?.length || 0) > 0
          ? <ReactECharts option={signalCoverageOption} className="chart-h-sm" />
          : <p className="text-muted">{t('common.noData')}</p>}
      </GlassCard>
      <GlassCard className="p-6 section-mt-md">
        <h3 className="card-heading">{t('admin.topErrors')}</h3>
        {(platformAnalytics?.top_errors?.length || 0) > 0
          ? <ReactECharts option={errorsBarOption} style={{ height: Math.max(180, (platformAnalytics?.top_errors?.length || 0) * 28) }} />
          : <p className="text-muted">{t('common.noData')}</p>}
      </GlassCard>
      <GlassCard className="p-6 section-mt-md">
        <h3 className="card-heading">{t('admin.systemHealth')}</h3>
        <div className="admin-health-list">
          <div><span>Redis</span><strong className={monitor?.redis_connected ? 'text-green' : 'text-red'}>{monitor?.redis_connected ? 'OK' : 'DOWN'}</strong></div>
          <div><span>{t('admin.activeSupervisors')}</span><strong>{monitor?.active_supervisors ?? 0}</strong></div>
          <div><span>{t('admin.onlineUsers')}</span><strong>{online?.recent_logins_15m ?? 0}</strong></div>
        </div>
      </GlassCard>
    </>
  )
}
