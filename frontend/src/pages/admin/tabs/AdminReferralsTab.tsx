import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import { useAdmin } from '../AdminContext'

export default function AdminReferralsTab() {
  const { t, referralOverview, loadUserDetail } = useAdmin()

  if (!referralOverview) {
    return (
      <GlassCard className="p-8"><p className="text-muted">{t('common.loading')}</p></GlassCard>
    )
  }

  return (
    <div>
      <div className="stat-grid section-mb-md">
        <StatCard label={t('admin.referralsPaid')} value={`$${referralOverview.total_rewards_paid?.toFixed(2) ?? '0'}`} />
        <StatCard label={t('admin.referralsPending')} value={`$${referralOverview.total_rewards_pending?.toFixed(2) ?? '0'}`} />
        <StatCard label={t('admin.referralsActive')} value={String(referralOverview.active_referrers ?? 0)} />
      </div>
      <GlassCard className="p-6 section-mb-md">
        <h3 className="card-heading">{t('admin.referralLeaderboard')}</h3>
        <table className="data-table section-mt-sm">
          <thead>
            <tr>
              <th>{t('admin.cols.uid')}</th><th>{t('common.user')}</th><th>{t('admin.referralL1')}</th>
              <th>{t('admin.totalEarned')}</th><th>{t('admin.rewardBalance')}</th>
            </tr>
          </thead>
          <tbody>
            {(referralOverview.leaderboard || []).map((row: any) => (
              <tr key={row.user_id}>
                <td>{row.uid}</td>
                <td>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => loadUserDetail(row.user_id)}>
                    {row.display_name}
                  </button>
                </td>
                <td>{row.l1_count}</td>
                <td>${row.total_earned?.toFixed(2)}</td>
                <td>${row.reward_balance?.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-0 table-wrap">
        <div className="table-toolbar"><h3 className="card-heading">{t('admin.referralRewards')}</h3></div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('admin.cols.id')}</th><th>{t('admin.cols.level')}</th><th>{t('admin.cols.owner')}</th>
              <th>{t('common.user')}</th><th>{t('admin.cols.amount')}</th><th>{t('common.status')}</th><th>{t('admin.cols.settlement')}</th>
            </tr>
          </thead>
          <tbody>
            {(referralOverview.rewards || []).map((r: any) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>L{r.level}</td>
                <td>{r.referrer_display_name} ({r.referrer_uid})</td>
                <td>{r.source_display_name} ({r.source_uid})</td>
                <td>${r.reward_amount?.toFixed(2)}</td>
                <td>{r.status}</td>
                <td>#{r.settlement_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  )
}
