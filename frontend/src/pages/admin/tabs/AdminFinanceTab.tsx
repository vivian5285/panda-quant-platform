import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import { useAdmin } from '../AdminContext'

export default function AdminFinanceTab() {
  const { t, confirmedRevenue, pendingRevenue, overview, settlements, payStatus } = useAdmin()

  return (
    <>
      <div className="stat-grid">
        <StatCard label={t('admin.confirmedRevenue')} countUp={{ end: confirmedRevenue, prefix: '$', decimals: 2 }} />
        <StatCard label={t('admin.pendingRevenue')} countUp={{ end: pendingRevenue, prefix: '$', decimals: 2 }} />
        <StatCard label={t('admin.pendingPay')} value={String(overview?.pending_settlements || 0)} />
        <StatCard label={t('admin.pendingConfirm')} value={String(overview?.pending_payments || 0)} />
      </div>
      <GlassCard className="p-0 table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('admin.cols.id')}</th><th>{t('common.user')}</th><th>{t('admin.cols.netProfit')}</th>
              <th>{t('admin.platformFee')}</th><th>{t('admin.cols.payable')}</th><th>{t('common.status')}</th>
            </tr>
          </thead>
          <tbody>
            {settlements.map((s: any) => (
              <tr key={s.id}>
                <td>{s.id}</td><td>#{s.user_id}</td>
                <td className="text-green">${s.net_profit?.toFixed(2)}</td>
                <td>${s.platform_fee?.toFixed(2)}</td>
                <td>${s.user_payable?.toFixed(2)}</td>
                <td><span className="badge badge-gray">{payStatus(s.payment_status)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </>
  )
}
