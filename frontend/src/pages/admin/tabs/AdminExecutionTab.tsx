import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

export default function AdminExecutionTab() {
  const {
    t, locale, latestSignal, monitor, renderDispatchUserResults, signalLogs,
    selectedDispatchId, loadDispatchResults, orders, formatOrderUser,
  } = useAdmin()

  return (
    <>
      <div className="dash-live-badge section-mb-sm">
        <div className="pulse-dot" />
        <span>{t('admin.liveWsBadge', { n: 3 })}</span>
      </div>
      <div className="stat-grid section-mb-md">
        <StatCard label={t('admin.execUsersCovered')} value={String(latestSignal?.dispatched_count ?? '—')} />
        <StatCard label={t('admin.execSuccess')} value={String(latestSignal?.success_count ?? latestSignal?.dispatched_count ?? '—')} />
        <StatCard label={t('admin.execFailed')} value={String(latestSignal?.error_count ?? '—')} />
        <StatCard label={t('admin.execRiskBlocked')} value={String(latestSignal?.skipped_count ?? '—')} />
        <StatCard label={t('admin.activeSupervisors')} value={String(monitor?.active_supervisors || 0)} />
        <StatCard label={t('admin.binanceLatency')} value={monitor?.binance_latency_ms > 0 ? `${monitor.binance_latency_ms}ms` : '—'} />
      </div>
      {renderDispatchUserResults()}
      <GlassCard className="p-0 table-wrap section-mb-md">
        <div className="table-toolbar table-toolbar-flush"><h3 className="card-heading">{t('admin.signalHistory')}</h3></div>
        <table className="data-table">
          <thead><tr><th>{t('common.time')}</th><th>{t('trades.signal')}</th><th>{t('common.status')}</th><th>{t('admin.execUsersCovered')}</th><th>{t('admin.execSuccess')}</th><th>{t('admin.execFailed')}</th><th>{t('admin.execRiskBlocked')}</th><th>{t('common.action')}</th></tr></thead>
          <tbody>
            {signalLogs.slice(0, 15).map((log: any) => (
              <tr key={log.id} className={selectedDispatchId === log.id ? 'row-active' : undefined}>
                <td className="text-xs">{localeDate(log.created_at, locale)}</td>
                <td>{log.action}</td>
                <td><span className="badge badge-gray">{log.status}</span></td>
                <td>{(log.dispatched_count ?? 0) + (log.error_count ?? 0) + (log.skipped_count ?? 0)}</td>
                <td className="text-green">{log.dispatched_count ?? 0}</td>
                <td className="text-red">{log.error_count ?? 0}</td>
                <td>{log.skipped_count ?? 0}</td>
                <td>
                  <button type="button" className="btn btn-ghost btn-xs" onClick={() => loadDispatchResults(log.id)}>
                    {t('admin.viewDispatchDetail')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-0 table-wrap">
        <div className="table-toolbar table-toolbar-flush"><h3 className="card-heading">{t('admin.executionDetails')}</h3></div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('admin.cols.id')}</th><th>{t('admin.cols.owner')}</th><th>{t('trades.side')}</th>
              <th>{t('trades.pnl')}</th><th>{t('admin.cols.slippage')}</th><th>{t('common.status')}</th><th>{t('common.time')}</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 && <tr><td colSpan={7} className="empty-cell">{t('common.noData')}</td></tr>}
            {orders.map((o: any) => (
              <tr key={o.id}>
                <td>{o.id}</td><td>{formatOrderUser(o)}</td><td>{o.side}</td>
                <td className={(o.realized_pnl || 0) >= 0 ? 'text-green' : 'text-red'}>{o.realized_pnl?.toFixed(2)}</td>
                <td>{o.slippage != null ? o.slippage.toFixed(4) : '—'}</td>
                <td>{o.status}</td><td className="text-xs">{localeDate(o.created_at, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </>
  )
}
