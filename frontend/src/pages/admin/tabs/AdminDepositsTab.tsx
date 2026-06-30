import GlassCard from '../../../components/GlassCard'
import { adminApi } from '../../../api'
import { useAdmin } from '../AdminContext'
import { localeDate } from '../../../i18n'

export default function AdminDepositsTab() {
  const {
    t, locale, settlementDeposits, settlementAppeals, appealFilter, setAppealFilter,
    depositFilter, setDepositFilter, sweepLogs, approveAppeal, rejectAppeal,
  } = useAdmin()

  return (
    <div>
      <p className="text-muted text-sm section-mb-sm">{t('admin.depositsTabHint')}</p>

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
                <td>{d.fee_fully_paid == null ? '—' : d.fee_fully_paid ? t('common.yes') : t('common.no')}</td>
                <td><span className="badge badge-gray">{t(`admin.depositStatus.${d.status}`) || d.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  )
}
