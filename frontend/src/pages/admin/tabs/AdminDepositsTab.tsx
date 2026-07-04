import GlassCard from '../../../components/GlassCard'
import { useAdmin } from '../AdminContext'
import { localeDate } from '../../../i18n'

function healthBadgeClass(health?: string) {
  if (health === 'healthy') return 'badge-green'
  if (health === 'stale' || health === 'pending') return 'badge-gray'
  return 'badge-red'
}

export default function AdminDepositsTab() {
  const {
    t, locale, settlementDeposits, settlementAppeals, appealFilter, setAppealFilter,
    depositFilter, setDepositFilter, sweepLogs, approveAppeal, rejectAppeal,
    depositMonitorStatus, paymentTracking, depositScanLoading, triggerDepositScan,
  } = useAdmin()

  const monitor = depositMonitorStatus
  const health = monitor?.health || 'pending'
  const intervalSec = monitor?.scan_interval_sec || 180

  return (
    <div>
      <p className="text-muted text-sm section-mb-sm">{t('admin.depositsTabHint')}</p>

      <GlassCard className="p-4 section-mb-lg deposit-monitor-card">
        <div className="flex-between-wrap gap-md">
          <div>
            <h3 className="panel-title-sm section-mb-xs">{t('admin.depositMonitorTitle')}</h3>
            <p className="text-muted text-sm">{t('admin.depositMonitorHint', { sec: intervalSec })}</p>
          </div>
          <button
            className="btn btn-primary btn-sm"
            type="button"
            disabled={depositScanLoading}
            onClick={() => triggerDepositScan()}
          >
            {depositScanLoading ? t('common.loading') : t('admin.scanDepositNow')}
          </button>
        </div>
        <div className="stat-grid stat-grid-flush section-mt-md">
          <div className="stat-tile">
            <p className="text-muted text-xs">{t('common.status')}</p>
            <span className={`badge ${healthBadgeClass(health)}`}>
              {t(`admin.depositMonitorHealth.${health}`) || health}
            </span>
          </div>
          <div className="stat-tile">
            <p className="text-muted text-xs">{t('settlements.lastScan')}</p>
            <p className="text-sm">{monitor?.last_scan_at ? localeDate(monitor.last_scan_at, locale) : '—'}</p>
          </div>
          <div className="stat-tile">
            <p className="text-muted text-xs">{t('admin.trackingAnomalies')}</p>
            <p className={`text-md-strong ${(monitor?.tracking_anomalies || 0) > 0 ? 'text-red' : ''}`}>
              {monitor?.tracking_anomalies ?? 0}
            </p>
          </div>
          <div className="stat-tile">
            <p className="text-muted text-xs">{monitor?.auto_confirm_enabled ? t('admin.autoConfirmOn') : t('admin.autoConfirmOff')}</p>
            <p className="text-sm">{monitor?.mnemonic_configured ? t('common.statusOk') : t('common.statusDown')}</p>
          </div>
        </div>
        {monitor?.last_error && (
          <p className="text-red text-xs section-mt-sm">{monitor.last_error}</p>
        )}
      </GlassCard>

      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="card-section-head flex-between-wrap">
          <h3 className="panel-title-sm">{t('admin.paymentTrackingTitle')}</h3>
        </div>
        <table className="data-table data-table-sm">
          <thead>
            <tr>
              <th>{t('admin.cols.uid')}</th>
              <th>{t('admin.cols.settlement')}</th>
              <th>{t('common.status')}</th>
              <th>{t('admin.cols.amount')}</th>
              <th>{t('admin.onChainBalance')}</th>
              <th>{t('admin.cols.depositAddr')}</th>
            </tr>
          </thead>
          <tbody>
            {paymentTracking.length === 0 ? (
              <tr><td colSpan={6} className="empty-cell">{t('admin.paymentTrackingEmpty')}</td></tr>
            ) : paymentTracking.map((row: any) => {
              const balances = row.on_chain_balances || []
              const maxBal = balances.reduce((m: number, b: any) => Math.max(m, b.usdt_balance || 0), 0)
              const addr = row.deposit_addresses?.[0]
              return (
                <tr key={row.settlement_id} className={row.tracking_phase === 'appeal_pending' ? 'settlement-pending-row' : undefined}>
                  <td>
                    <div>{row.user_uid}</div>
                    <div className="text-muted text-xs">{row.user_display}</div>
                  </td>
                  <td>
                    #{row.settlement_id}
                    <div className="text-muted text-xs">${row.user_payable?.toFixed(2)} · {row.net_profit != null ? `+${row.net_profit}` : ''}</div>
                  </td>
                  <td>
                    <span className="badge badge-gray">
                      {t(`admin.trackingPhase.${row.tracking_phase}`) || row.tracking_phase}
                    </span>
                  </td>
                  <td>
                    <div>${row.detected_total?.toFixed(2) ?? '0.00'}</div>
                    {row.split && (
                      <div className="text-muted text-xs">
                        L1 ${row.split.l1_reward} · L2 ${row.split.l2_reward}
                      </div>
                    )}
                  </td>
                  <td>
                    {balances.length === 0 ? '—' : (
                      <span className={maxBal >= (row.user_payable || 0) * 0.98 ? 'text-green' : 'text-muted'}>
                        ${maxBal.toFixed(2)}
                      </span>
                    )}
                  </td>
                  <td className="mono-cell cell-ellipsis" title={addr?.address}>
                    {addr ? `${addr.chain} · ${addr.address?.slice(0, 10)}…` : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </GlassCard>

      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="card-section-head flex-between-wrap">
          <h3 className="panel-title-sm">{t('admin.depositAppealsTitle')}</h3>
          <select className="input input-sm" value={appealFilter} onChange={e => setAppealFilter(e.target.value)}>
            <option value="">{t('admin.filterAll')}</option>
            <option value="submitted">{t('admin.appealStatus.submitted')}</option>
            <option value="approved">{t('admin.appealStatus.approved')}</option>
            <option value="rejected">{t('admin.appealStatus.rejected')}</option>
          </select>
        </div>
        <table className="data-table data-table-sm">
          <thead>
            <tr>
              <th>{t('common.time')}</th>
              <th>{t('admin.cols.uid')}</th>
              <th>{t('admin.cols.settlement')}</th>
              <th>{t('common.chain')}</th>
              <th>{t('admin.cols.depositAddr')}</th>
              <th>{t('admin.cols.txHash')}</th>
              <th>{t('admin.cols.amount')}</th>
              <th>{t('admin.cols.feePaid')}</th>
              <th>{t('common.status')}</th>
              <th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {settlementAppeals.length === 0 ? (
              <tr><td colSpan={10} className="empty-cell">{t('admin.noAppeals')}</td></tr>
            ) : settlementAppeals.map((a: any) => (
              <tr key={a.id} className={a.status === 'submitted' ? 'settlement-pending-row' : undefined}>
                <td>{localeDate(a.created_at, locale)}</td>
                <td>{a.user_uid || `#${a.user_id}`}</td>
                <td>#{a.settlement_id} · ${a.settlement_payable?.toFixed?.(2) ?? '—'}</td>
                <td><span className="badge badge-green">{a.chain}</span></td>
                <td className="mono-cell cell-ellipsis" title={a.deposit_address}>{a.deposit_address?.slice(0, 12) || '—'}…</td>
                <td className="mono-cell cell-ellipsis" title={a.tx_hash}>{a.tx_hash?.slice(0, 14)}…</td>
                <td>${a.claimed_amount?.toFixed(2)}</td>
                <td>{a.fee_fully_paid ? t('common.yes') : t('common.no')}</td>
                <td><span className="badge badge-gray">{t(`admin.appealStatus.${a.status}`) || a.status}</span></td>
                <td className="table-actions">
                  {a.status === 'submitted' && (
                    <>
                      <button className="btn btn-primary btn-xs" type="button" onClick={() => approveAppeal(a.id)}>{t('common.approve')}</button>
                      <button className="btn btn-ghost btn-xs" type="button" onClick={() => rejectAppeal(a.id)}>{t('common.reject')}</button>
                    </>
                  )}
                  {a.user_note && <span className="text-muted text-xs" title={a.user_note}>{a.user_note.slice(0, 20)}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="card-section-head flex-between-wrap">
          <h3 className="panel-title-sm">{t('admin.sweepLogTitle')}</h3>
        </div>
        <table className="data-table data-table-sm">
          <thead>
            <tr>
              <th>{t('common.time')}</th>
              <th>{t('admin.cols.uid')}</th>
              <th>{t('common.chain')}</th>
              <th>{t('admin.cols.depositAddr')}</th>
              <th>{t('admin.cols.amount')}</th>
              <th>{t('common.status')}</th>
              <th>{t('admin.cols.txHash')}</th>
            </tr>
          </thead>
          <tbody>
            {sweepLogs.length === 0 ? (
              <tr><td colSpan={7} className="empty-cell">{t('admin.noSweepLogs')}</td></tr>
            ) : sweepLogs.map((l: any) => (
              <tr key={l.id}>
                <td>{localeDate(l.created_at, locale)}</td>
                <td>{l.user_uid || `#${l.user_id}`}</td>
                <td><span className="badge badge-green">{l.chain}</span></td>
                <td className="mono-cell cell-ellipsis" title={l.from_address}>{l.from_address?.slice(0, 12) || '—'}…</td>
                <td>${l.amount?.toFixed(2)}</td>
                <td>
                  <span
                    className={`badge ${l.status === 'success' ? 'badge-green' : l.status === 'failed' ? 'badge-red' : 'badge-gray'}`}
                    title={l.error_message || undefined}
                  >
                    {t(`admin.sweepStatus.${l.status}`) || l.status}
                  </span>
                </td>
                <td className="mono-cell cell-ellipsis" title={l.sweep_tx_hash}>{l.sweep_tx_hash?.slice(0, 14) || '—'}…</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      <GlassCard className="p-0 table-wrap">
        <div className="card-section-head flex-between-wrap">
          <h3 className="panel-title-sm">{t('admin.depositLogTitle')}</h3>
          <select className="input input-sm" value={depositFilter} onChange={e => setDepositFilter(e.target.value)}>
            <option value="">{t('admin.filterAll')}</option>
            <option value="detected">{t('admin.depositStatus.detected')}</option>
            <option value="matched">{t('admin.depositStatus.matched')}</option>
          </select>
        </div>
        <table className="data-table data-table-sm">
          <thead>
            <tr>
              <th>{t('common.time')}</th>
              <th>{t('admin.cols.uid')}</th>
              <th>{t('admin.cols.settlement')}</th>
              <th>{t('common.chain')}</th>
              <th>{t('admin.cols.depositAddr')}</th>
              <th>{t('admin.cols.txHash')}</th>
              <th>{t('admin.cols.amount')}</th>
              <th>{t('admin.cols.source')}</th>
              <th>{t('admin.cols.feePaid')}</th>
              <th>{t('common.status')}</th>
            </tr>
          </thead>
          <tbody>
            {settlementDeposits.length === 0 ? (
              <tr><td colSpan={10} className="empty-cell">{t('admin.noDeposits')}</td></tr>
            ) : settlementDeposits.map((d: any) => (
              <tr key={d.id}>
                <td>{localeDate(d.detected_at, locale)}</td>
                <td>{d.user_uid || `#${d.user_id}`}</td>
                <td>
                  {d.settlement_id ? `#${d.settlement_id} · ${d.settlement_status}` : '—'}
                  {d.settlement_payable != null && <div className="text-muted text-xs">${d.settlement_payable.toFixed(2)}</div>}
                </td>
                <td><span className="badge badge-green">{d.chain}</span></td>
                <td className="mono-cell cell-ellipsis" title={d.deposit_address}>{d.deposit_address?.slice(0, 12) || '—'}…</td>
                <td className="mono-cell cell-ellipsis" title={d.tx_hash}>{d.tx_hash?.slice(0, 14)}…</td>
                <td>${d.amount?.toFixed(2)}</td>
                <td>{t(`admin.depositSource.${d.source}`) || d.source}</td>
                <td>{d.fee_fully_paid ? t('common.yes') : t('common.no')}</td>
                <td><span className="badge badge-gray">{t(`admin.depositStatus.${d.status}`) || d.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  )
}
