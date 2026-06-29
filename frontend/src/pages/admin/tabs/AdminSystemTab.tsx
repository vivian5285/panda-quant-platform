import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

export default function AdminSystemTab() {
  const {
    t, locale, webhookPayload, setWebhookPayload, runWebhookTest,
    online, monitor, signalLogs, riskAlerts, loginRecords, auditLogs,
    tradeLogs, exportTradeLogsCsv, orders, formatOrderUser, startupAudit, setTab,
  } = useAdmin()

  const audits = startupAudit?.audits || []
  const failures = startupAudit?.failures || []
  const secWarnings = startupAudit?.security_warnings || []
  const infraNotes = startupAudit?.infra_notes || []
  const productionReady = startupAudit?.production_ready
  const hasDepositInfraNote = infraNotes.some((n: string) => n.includes('收款地址') || n.includes('二维码'))

  return (
    <>
      {productionReady === false && (
        <GlassCard className="p-6 section-mb-lg production-checklist-card">
          <h3 className="card-heading">{t('admin.productionChecklistTitle')}</h3>
          <p className="text-muted text-sm section-mb-sm">{t('admin.productionChecklistHint')}</p>
          <ul className="production-checklist-list">
            {secWarnings.map((w: string, i: number) => (
              <li key={`chk-sec-${i}`} className="text-sm text-red">⚠ {w}</li>
            ))}
          </ul>
          <p className="text-muted text-xs section-mt-sm">{t('admin.productionStrictNote')}</p>
        </GlassCard>
      )}
      {hasDepositInfraNote && (
        <GlassCard className="p-4 section-mb-lg">
          <p className="text-sm section-mb-sm">{t('admin.depositInfraHint')}</p>
          <button className="btn btn-primary btn-sm" type="button" onClick={() => setTab('addresses')}>
            {t('admin.tabAddresses')}
          </button>
        </GlassCard>
      )}
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.startupAuditTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.startupAuditHint')}</p>
        <div className="admin-health-list section-mb-sm">
          <div><span>{t('admin.activeSupervisors')}</span><strong>{startupAudit?.active_supervisors ?? monitor?.active_supervisors ?? 0}</strong></div>
          <div><span>{t('admin.startupWithPosition')}</span><strong>{audits.filter((a: any) => a.has_position).length}</strong></div>
          <div><span>{t('admin.startupMonitoring')}</span><strong>{audits.filter((a: any) => a.monitoring).length}</strong></div>
          <div><span>{t('admin.startupFailures')}</span><strong className={failures.length ? 'text-red' : ''}>{failures.length}</strong></div>
        </div>
        {(secWarnings.length > 0 || infraNotes.length > 0) && (
          <div className="section-mb-sm">
            {secWarnings.map((w: string, i: number) => (
              <div key={`sec-${i}`} className="text-sm text-red section-mb-xs">⚠ {w}</div>
            ))}
            {infraNotes.map((n: string, i: number) => (
              <div key={`infra-${i}`} className="text-sm text-muted section-mb-xs">· {n}</div>
            ))}
          </div>
        )}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('common.user')}</th>
                <th>{t('trades.side')}</th>
                <th>{t('admin.cols.qty')}</th>
                <th>{t('admin.startupAligned')}</th>
                <th>{t('admin.startupMonitoring')}</th>
              </tr>
            </thead>
            <tbody>
              {audits.length === 0 && <tr><td colSpan={5} className="empty-cell">{t('common.noData')}</td></tr>}
              {audits.map((a: any) => (
                <tr key={a.user_id}>
                  <td>{a.uid || `#${a.user_id}`}</td>
                  <td>{a.has_position ? a.side : '—'}</td>
                  <td>{a.has_position ? a.qty : '—'}</td>
                  <td>{a.has_position ? (a.direction_aligned ? t('common.yes') : t('common.no')) : '—'}</td>
                  <td>{a.monitoring ? t('common.yes') : t('common.no')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.webhookTestTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.webhookTestHint')}</p>
        <textarea className="input input-mono section-mb-sm" rows={8} value={webhookPayload} onChange={e => setWebhookPayload(e.target.value)} />
        <button className="btn btn-primary btn-sm" type="button" onClick={runWebhookTest}>{t('admin.webhookTestRun')}</button>
      </GlassCard>
      <div className="stat-grid">
        <StatCard label={t('admin.onlineUsers')} value={String(online?.recent_logins_15m || 0)} />
        <StatCard label={t('admin.activeSupervisors')} value={String(monitor?.active_supervisors || 0)} />
        <StatCard label={t('admin.webhookStatus')} value={monitor?.webhook_status || '—'} />
        <StatCard label={t('admin.binanceLatency')} value={monitor?.binance_latency_ms > 0 ? `${monitor.binance_latency_ms}ms` : '—'} />
        <StatCard label={t('admin.webhookTotal')} value={String(monitor?.webhook_received_total || 0)} />
        <StatCard label={t('admin.queueDepth')} value={String(monitor?.queue_depth ?? 0)} />
        <StatCard label={t('admin.redis')} value={monitor?.redis_connected ? t('common.statusOk') : t('common.none')} />
        <StatCard label={t('admin.webhookLast')} value={monitor?.webhook_last_received_at ? localeDate(monitor.webhook_last_received_at, locale) : '—'} />
      </div>
      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="table-toolbar table-toolbar-flush"><h3 className="card-heading">{t('admin.webhookReceiveLogs')}</h3></div>
        <table className="data-table">
          <thead><tr><th>{t('common.time')}</th><th>{t('trades.signal')}</th><th>{t('admin.cols.source')}</th><th>{t('admin.execUsersCovered')}</th><th>{t('admin.execFailed')}</th><th>{t('common.status')}</th></tr></thead>
          <tbody>
            {signalLogs.length === 0 && <tr><td colSpan={6} className="empty-cell">{t('common.noData')}</td></tr>}
            {signalLogs.slice(0, 30).map((log: any) => (
              <tr key={log.id}>
                <td className="text-xs">{localeDate(log.created_at, locale)}</td>
                <td>{log.action}</td>
                <td>{log.source}</td>
                <td>{log.dispatched_count ?? 0}</td>
                <td>{log.error_count ?? 0}</td>
                <td><span className="badge badge-gray">{log.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.riskAlerts')}</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>{t('common.time')}</th><th>{t('admin.cols.type')}</th><th>{t('admin.cols.detail')}</th></tr></thead>
            <tbody>
              {riskAlerts.length === 0 && <tr><td colSpan={3} className="empty-cell">{t('admin.noRiskAlerts')}</td></tr>}
              {riskAlerts.slice(0, 20).map((r: any, i: number) => (
                <tr key={i}><td>{localeDate(r.created_at || r.timestamp, locale)}</td><td>{r.alert_type || r.type}</td><td>{r.message || r.title}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.loginRecords')}</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>{t('common.user')}</th><th>{t('admin.cols.ip')}</th><th>{t('admin.device')}</th><th>{t('common.time')}</th></tr></thead>
            <tbody>
              {loginRecords.length === 0 && <tr><td colSpan={4} className="empty-cell">{t('admin.noLoginRecords')}</td></tr>}
              {loginRecords.slice(0, 30).map((r: any) => (
                <tr key={r.id}><td>{r.user_id || r.uid}</td><td>{r.ip_address || r.ip}</td><td>{r.user_agent?.slice(0, 40) || '—'}</td><td>{localeDate(r.created_at, locale)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.auditLogs')}</h3>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>{t('common.action')}</th><th>{t('common.user')}</th><th>{t('admin.cols.ip')}</th><th>{t('common.time')}</th></tr></thead>
          <tbody>{auditLogs.slice(0, 30).map((l: any) => <tr key={l.id}><td>{l.action}</td><td>{l.user_id}</td><td>{l.ip_address}</td><td>{localeDate(l.created_at, locale)}</td></tr>)}</tbody></table></div>
      </GlassCard>
      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="table-toolbar table-toolbar-between table-toolbar-flush">
          <h3 className="card-heading">{t('admin.allTradeLogs')}</h3>
          <button className="btn btn-ghost btn-sm" type="button" onClick={exportTradeLogsCsv}>{t('admin.exportCsv')}</button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('common.time')}</th><th>{t('admin.cols.owner')}</th><th>{t('admin.cols.type')}</th>
              <th>{t('admin.cols.detail')}</th>
            </tr>
          </thead>
          <tbody>
            {tradeLogs.length === 0 && <tr><td colSpan={4} className="empty-cell">{t('common.noData')}</td></tr>}
            {tradeLogs.slice(0, 50).map((l: any) => (
              <tr key={l.id}>
                <td className="text-xs">{localeDate(l.created_at, locale)}</td>
                <td>{l.user_uid || `#${l.user_id}`}</td>
                <td><span className="badge badge-gray">{l.event_type}</span></td>
                <td className="text-sm cell-max-md">{l.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-0 table-wrap">
        <h3 className="card-heading p-6 mb-0">{t('admin.allOrders')}</h3>
        <table className="data-table"><thead><tr><th>{t('admin.cols.id')}</th><th>{t('admin.cols.owner')}</th><th>{t('trades.side')}</th><th>{t('trades.pnl')}</th><th>{t('common.status')}</th></tr></thead>
          <tbody>{orders.slice(0, 50).map((o: any) => <tr key={o.id}><td>{o.id}</td><td>{formatOrderUser(o)}</td><td>{o.side}</td><td>{o.realized_pnl}</td><td>{o.status}</td></tr>)}</tbody></table>
      </GlassCard>
    </>
  )
}
