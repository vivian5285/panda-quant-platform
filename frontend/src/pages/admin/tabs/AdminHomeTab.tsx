import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import { useAdmin } from '../AdminContext'

export default function AdminHomeTab() {
  const {
    t, overview, orders, online, monitor, riskAlerts, confirmedRevenue,
    setTab, formatOrderUser,
  } = useAdmin()

  return (
    <>
      {(overview?.settlement_blocked_users ?? 0) > 0 && (
        <GlassCard className="p-4 section-mb-md admin-settlement-alert">
          <p className="text-sm section-mb-sm">
            {t('admin.settlementDeferBanner', {
              blocked: overview?.settlement_blocked_users ?? 0,
              deferred: overview?.settlement_deferred_users ?? 0,
            })}
          </p>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setTab('settlements')}>
            {t('admin.settlementDeferBannerAction')}
          </button>
        </GlassCard>
      )}
      <div className="stat-grid admin-home-stats">
        <StatCard label={t('admin.totalUsers')} countUp={{ end: overview?.total_users || 0, decimals: 0 }} />
        <StatCard label={t('admin.todayExecutions')} countUp={{ end: overview?.today_executions || 0, decimals: 0 }} />
        <StatCard label={t('admin.todaySuccessRate')} value={`${overview?.today_success_rate ?? 0}%`} />
        <StatCard label={t('admin.onlineUsers')} countUp={{ end: online?.recent_logins_15m || 0, decimals: 0 }} />
        <StatCard label={t('admin.activeSupervisors')} countUp={{ end: overview?.active_supervisors || monitor?.active_supervisors || 0, decimals: 0 }} />
        <StatCard label={t('admin.orderCount')} countUp={{ end: orders.length, decimals: 0 }} />
        <StatCard label={t('admin.riskAlertCount')} value={`${riskAlerts.length}`} />
        <StatCard label={t('admin.pendingWithdraw')} countUp={{ end: overview?.pending_withdrawals || 0, decimals: 0 }} />
        <StatCard label={t('admin.serverStatus')} value={monitor?.redis_connected ? t('common.statusOk') : t('common.none')} />
        <StatCard label={t('admin.confirmedRevenue')} countUp={{ end: confirmedRevenue, prefix: '$', decimals: 2 }} />
      </div>
      <div className="admin-home-grid">
        <GlassCard className="p-6">
          <h3 className="card-heading">{t('admin.quickActions')}</h3>
          <div className="admin-quick-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setTab('users')}>{t('admin.tabUsers')}</button>
            <button type="button" className="btn btn-ghost" onClick={() => setTab('finance')}>{t('admin.tabFinance')}</button>
            <button type="button" className="btn btn-ghost" onClick={() => setTab('risk')}>{t('admin.tabRisk')}</button>
            <button type="button" className="btn btn-ghost" onClick={() => setTab('system')}>{t('admin.tabSystem')}</button>
          </div>
        </GlassCard>
        <GlassCard className="p-6">
          <h3 className="card-heading">{t('admin.systemHealth')}</h3>
          <div className="admin-health-list">
            <div><span>{t('admin.redis')}</span><strong className={monitor?.redis_connected ? 'text-green' : 'text-red'}>{monitor?.redis_connected ? t('common.statusOk') : t('common.statusDown')}</strong></div>
            <div><span>{t('admin.activeSupervisors')}</span><strong>{monitor?.active_supervisors ?? 0}</strong></div>
            <div><span>{t('admin.apiLatency')}</span><strong>{monitor?.api_latency_ms || 0}ms</strong></div>
            <div><span>{t('admin.pendingPay')}</span><strong>{overview?.pending_settlements ?? 0}</strong></div>
            <div><span>{t('admin.pendingWithdraw')}</span><strong>{overview?.pending_withdrawals ?? 0}</strong></div>
          </div>
        </GlassCard>
      </div>
      <GlassCard className="p-0 table-wrap section-mt-lg">
        <h3 className="card-heading p-6 mb-0">{t('admin.recentOrders')}</h3>
        <table className="data-table">
          <thead><tr><th>{t('admin.cols.id')}</th><th>{t('admin.cols.owner')}</th><th>{t('trades.side')}</th><th>{t('trades.pnl')}</th><th>{t('common.status')}</th></tr></thead>
          <tbody>
            {orders.slice(0, 10).map((o: any) => (
              <tr key={o.id}><td>{o.id}</td><td>{formatOrderUser(o)}</td><td>{o.side}</td><td>{o.realized_pnl?.toFixed(2)}</td><td>{o.status}</td></tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </>
  )
}
