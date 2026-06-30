import GlassCard from '../../../components/GlassCard'
import { adminApi } from '../../../api'
import { toast } from '../../../store/toast'
import { useAdmin } from '../AdminContext'

export default function AdminSettlementsTab() {
  const { t, settlements, payStatus, confirm, exportSettlementsCsv, load } = useAdmin()

  const toggleDefer = async (userId: number, allow: boolean) => {
    try {
      await adminApi.userTradingControl(userId, { settlement_fee_deferred: allow })
      toast.success(t('admin.settlementDeferSuccess'))
      load()
    } catch {
      toast.error(t('admin.settlementDeferFail'))
    }
  }

  const unsettled = (s: any) => s.payment_status === 'pending' || s.payment_status === 'paid'

  return (
    <>
      <p className="text-muted text-sm section-mb-sm">{t('admin.settlementDeferHint')}</p>
      <GlassCard className="p-0 table-wrap">
        <div className="table-toolbar">
          <button className="btn btn-ghost btn-sm" type="button" onClick={exportSettlementsCsv}>{t('admin.exportCsv')}</button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('admin.cols.id')}</th><th>{t('common.user')}</th><th>{t('admin.cols.cycle')}</th>
              <th>{t('admin.cols.netProfit')}</th><th>{t('admin.cols.payable')}</th><th>{t('admin.cols.payment')}</th>
              <th>{t('common.status')}</th><th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {settlements.map((s: any) => (
              <tr key={s.id}>
                <td>{s.id}</td><td>#{s.user_id}</td>
                <td>{s.cycle_days}{t('common.days')}</td>
                <td className="text-green">${s.net_profit?.toFixed(2)}</td>
                <td>${s.user_payable?.toFixed(2)}</td>
                <td className="text-xs">
                  {s.payment_chain && `${s.payment_chain} $${s.payment_amount}`}
                  {s.payment_tx_hash && <div className="text-muted">{s.payment_tx_hash.slice(0, 16)}...</div>}
                </td>
                <td>
                  <span className="badge badge-gray">{payStatus(s.payment_status)}</span>
                  {s.settlement_fee_deferred && unsettled(s) && (
                    <div className="text-xs text-green section-mt-xs">{t('admin.settlementDeferAllowed')}</div>
                  )}
                </td>
                <td className="table-actions">
                  {s.payment_status === 'paid' && (
                    <button className="btn btn-ghost btn-xs" onClick={() => confirm(s.id)}>{t('common.confirm')}</button>
                  )}
                  {s.payment_status === 'paid' && (
                    <button className="btn btn-ghost btn-xs" onClick={() => adminApi.rejectSettlement(s.id).then(load)}>{t('common.reject')}</button>
                  )}
                  {unsettled(s) && !s.settlement_fee_deferred && (
                    <button className="btn btn-primary btn-xs" type="button" onClick={() => toggleDefer(s.user_id, true)}>
                      {t('admin.settlementDeferAllow')}
                    </button>
                  )}
                  {unsettled(s) && s.settlement_fee_deferred && (
                    <button className="btn btn-ghost btn-xs" type="button" onClick={() => toggleDefer(s.user_id, false)}>
                      {t('admin.settlementDeferRevoke')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </>
  )
}
