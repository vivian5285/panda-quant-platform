import { useMemo } from 'react'
import GlassCard from '../../../components/GlassCard'
import StatCard from '../../../components/StatCard'
import { adminApi } from '../../../api'
import { toast } from '../../../store/toast'
import { useAdmin } from '../AdminContext'
import { formatSettlementCycle } from '../../../utils/settlementCycle'
import { localeDate } from '../../../i18n'

type StatusFilter = '' | 'pending' | 'paid' | 'confirmed' | 'rejected'

export default function AdminSettlementsTab() {
  const {
    t, locale, settlements, settlementSummary, settlementStatusFilter, setSettlementStatusFilter,
    payStatus, confirm, exportSettlementsCsv, load,
  } = useAdmin()

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
  const summary = settlementSummary || {}

  const filtered = useMemo(() => {
    if (!settlementStatusFilter) return settlements
    return settlements.filter((s: any) => s.payment_status === settlementStatusFilter)
  }, [settlements, settlementStatusFilter])

  const filters: { key: StatusFilter; label: string; count?: number }[] = [
    { key: '', label: t('admin.filterAll'), count: summary.total_bills },
    { key: 'pending', label: t('admin.settlementStats.pending'), count: summary.pending_payment },
    { key: 'paid', label: t('admin.settlementStats.paid'), count: summary.paid_awaiting_confirm },
    { key: 'confirmed', label: t('admin.settlementStats.confirmed'), count: summary.confirmed },
    { key: 'rejected', label: t('admin.settlementStats.rejected'), count: summary.rejected },
  ]

  return (
    <>
      <p className="text-muted text-sm section-mb-sm">{t('admin.settlementOverviewHint')}</p>

      <div className="stat-grid section-mb-lg">
        <StatCard label={t('admin.settlementStats.totalBills')} value={String(summary.total_bills ?? 0)} />
        <StatCard label={t('admin.settlementStats.unpaidUsers')} value={String(summary.unpaid_users ?? 0)} />
        <StatCard
          label={t('admin.settlementStats.pendingAmount')}
          value={`$${(summary.pending_amount_total ?? 0).toFixed(2)}`}
        />
        <StatCard
          label={t('admin.settlementStats.confirmedAmount')}
          value={`$${(summary.confirmed_amount_total ?? 0).toFixed(2)}`}
        />
        <StatCard label={t('admin.settlementStats.todayNew')} value={String(summary.today_new_bills ?? 0)} />
        <StatCard label={t('admin.settlementStats.todayConfirmed')} value={String(summary.today_confirmed ?? 0)} />
        <StatCard label={t('admin.settlementStats.approaching')} value={String(summary.approaching_cycle_count ?? 0)} />
      </div>

      {(summary.approaching_cycle_users?.length ?? 0) > 0 && (
        <GlassCard className="p-0 table-wrap section-mb-lg">
          <div className="card-section-head">
            <h3 className="panel-title-sm">{t('admin.settlementApproachingTitle')}</h3>
          </div>
          <table className="data-table data-table-sm">
            <thead>
              <tr>
                <th>{t('admin.cols.uid')}</th>
                <th>{t('admin.settlementStats.daysUntilDue')}</th>
                <th>{t('admin.cols.cycle')}</th>
                <th>{t('admin.cols.principal')}</th>
              </tr>
            </thead>
            <tbody>
              {summary.approaching_cycle_users.map((u: any) => (
                <tr key={u.user_id}>
                  <td>
                    <div>{u.user_uid}</div>
                    <div className="text-muted text-xs">{u.user_display}</div>
                  </td>
                  <td><span className="badge badge-gray">{u.days_until_due} {t('common.days')}</span></td>
                  <td>{u.cycle_start} · {u.cycle_target_days}{t('common.days')}</td>
                  <td>${u.initial_principal?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      <div className="admin-filter-chips section-mb-md">
        {filters.map(f => (
          <button
            key={f.key || 'all'}
            type="button"
            className={`btn btn-sm ${settlementStatusFilter === f.key ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setSettlementStatusFilter(f.key)}
          >
            {f.label}
            {f.count != null && <span className="chip-count">{f.count}</span>}
          </button>
        ))}
      </div>

      <GlassCard className="p-0 table-wrap">
        <div className="table-toolbar">
          <button className="btn btn-ghost btn-sm" type="button" onClick={exportSettlementsCsv}>{t('admin.exportCsv')}</button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('admin.cols.id')}</th>
              <th>{t('common.user')}</th>
              <th>{t('admin.cols.period')}</th>
              <th>{t('admin.cols.cycle')}</th>
              <th>{t('admin.cols.netProfit')}</th>
              <th>{t('admin.cols.payable')}</th>
              <th>{t('admin.cols.payment')}</th>
              <th>{t('common.status')}</th>
              <th>{t('common.time')}</th>
              <th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={10} className="empty-cell">{t('admin.noSettlements')}</td></tr>
            ) : filtered.map((s: any) => (
              <tr key={s.id} className={unsettled(s) ? 'settlement-pending-row' : undefined}>
                <td>{s.id}</td>
                <td>
                  <div>{s.user_uid || `#${s.user_id}`}</div>
                  <div className="text-muted text-xs">{s.user_display}</div>
                </td>
                <td className="text-xs">{s.period_start} ~ {s.period_end}</td>
                <td>{formatSettlementCycle(s.cycle_days, t)}</td>
                <td className="text-green">${s.net_profit?.toFixed(2)}</td>
                <td className="text-md-strong">${s.user_payable?.toFixed(2)}</td>
                <td className="text-xs">
                  {s.payment_chain && `${s.payment_chain} $${s.payment_amount}`}
                  {s.payment_tx_hash && <div className="text-muted">{s.payment_tx_hash.slice(0, 16)}...</div>}
                </td>
                <td>
                  <span className={`badge ${s.payment_status === 'confirmed' ? 'badge-green' : s.payment_status === 'pending' ? 'badge-red' : 'badge-gray'}`}>
                    {payStatus(s.payment_status)}
                  </span>
                  {s.settlement_fee_deferred && unsettled(s) && (
                    <div className="text-xs text-green section-mt-xs">{t('admin.settlementDeferAllowed')}</div>
                  )}
                </td>
                <td className="text-muted text-xs">{localeDate(s.created_at, locale)}</td>
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
