import GlassCard from '../../../components/GlassCard'
import { adminApi } from '../../../api'
import { useAdmin } from '../AdminContext'

export default function AdminWithdrawalsTab() {
  const {
    t, withdrawThresholds, withdrawals, wStatus, completeTx, setCompleteTx,
    completeWd, load,
  } = useAdmin()

  return (
    <div>
      {withdrawThresholds && (
        <GlassCard className="p-4 section-mb-md">
          <p className="text-sm">{t('admin.withdrawQueueHint', {
            instant: withdrawThresholds.auto_max_usd,
            review: withdrawThresholds.review_min_usd,
          })}</p>
        </GlassCard>
      )}
      <GlassCard className="p-0 table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('admin.cols.id')}</th><th>{t('common.user')}</th><th>{t('common.chain')}</th><th>{t('common.amount')}</th>
              <th>{t('admin.cols.fee')}</th><th>{t('admin.cols.received')}</th><th>{t('common.address')}</th>
              <th>{t('common.status')}</th><th>TxHash</th><th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {withdrawals.map((w: any) => (
              <tr key={w.id}>
                <td>{w.id}</td><td>#{w.user_id}</td>
                <td><span className="badge badge-gray">{w.chain}</span></td>
                <td>${w.amount?.toFixed(2)}</td>
                <td className="text-muted">${(w.network_fee ?? 0).toFixed(2)}</td>
                <td className="text-green">${(w.amount_net ?? w.amount)?.toFixed(2)}</td>
                <td className="mono-address-sm">{w.address.slice(0, 12)}...</td>
                <td>
                  <span className={`badge ${
                    w.status === 'completed' ? 'badge-green'
                    : w.status === 'processing' ? 'badge-yellow'
                    : w.auto_approved ? 'badge-green' : 'badge-gray'
                  }`}>
                    {w.status === 'processing'
                      ? t('admin.wStatus.processing')
                      : w.status === 'completed' && w.admin_note === 'auto_payout'
                        ? t('admin.wStatus.autoCompleted')
                        : w.auto_approved && w.status === 'auto_approved'
                          ? t('admin.wStatus.instantQueue')
                          : wStatus(w.status)}
                  </span>
                </td>
                <td className="mono-address-sm">
                  {w.explorer_url && w.tx_hash ? (
                    <a href={w.explorer_url} target="_blank" rel="noopener noreferrer" className="link-muted">
                      {w.tx_hash.slice(0, 12)}…
                    </a>
                  ) : w.tx_hash ? (
                    <span>{w.tx_hash.slice(0, 12)}…</span>
                  ) : '—'}
                </td>
                <td>
                  {w.status !== 'completed' && w.status !== 'rejected' && w.status !== 'processing' && (
                    <div className="form-actions-stack">
                      <input className="input input-compact" placeholder={t('admin.txHashPh')}
                        value={completeTx[w.id] || ''} onChange={e => setCompleteTx({ ...completeTx, [w.id]: e.target.value })} />
                      <div className="table-actions">
                        {!w.auto_approved && w.status === 'pending' && (
                          <button className="btn btn-ghost btn-xs" onClick={() => adminApi.approveWithdrawal(w.id).then(load)}>{t('admin.approveReview')}</button>
                        )}
                        <button className="btn btn-primary btn-xs" onClick={() => completeWd(w.id)}>{t('admin.completePayout')}</button>
                        <button className="btn btn-ghost btn-xs" onClick={() => adminApi.rejectWithdrawal(w.id).then(load)}>{t('common.reject')}</button>
                      </div>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  )
}
