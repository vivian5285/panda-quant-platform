import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Link2, ArrowRight } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import WithdrawCta from '../components/WithdrawCta'
import TabBar from '../components/TabBar'
import { referralApi, walletApi } from '../api'
import { useI18n, localeDate } from '../i18n'
import ReferralTree from '../components/ReferralTree'
import ReferralBlockDetailList from '../components/ReferralBlockDetailList'
import DownlineLogsModal from '../components/DownlineLogsModal'

type TabKey = 'overview' | 'l1' | 'l2' | 'commissions'

function referralBlockCopy(t: (k: string) => string, reason?: string | null) {
  if (reason === 'downline_credit_default') {
    return { title: t('referrals.downlineCreditDefaultBannerTitle'), body: t('referrals.downlineCreditDefaultBannerBody') }
  }
  return { title: t('referrals.creditDefaultBannerTitle'), body: t('referrals.creditDefaultBannerBody') }
}

function settlementCell(u: any, t: (k: string) => string) {
  const fee = u.pending_perf_fee ?? 0
  if (fee > 0) {
    const label = u.settlement_status === 'paid'
      ? t('referrals.settlementPendingConfirm')
      : t('referrals.settlementPendingPay')
    return (
      <div>
        <span className="badge badge-red badge-spaced">{label}</span>
        <div className="text-red text-xs mt-xs">${fee.toFixed(2)}</div>
        {u.settlement_period && (
          <div className="text-muted text-xs">{u.settlement_period}</div>
        )}
      </div>
    )
  }
  if (!u.settlement_status || u.settlement_status === 'none') {
    return <span className="text-muted">{t('referrals.settlementClear')}</span>
  }
  return <span className="badge badge-gray">{u.settlement_status}</span>
}

function UnpaidFeeBanner({
  count,
  totalFee,
  totalReward,
  t,
}: {
  count: number
  totalFee: number
  totalReward: number
  t: (k: string, p?: Record<string, string | number>) => string
}) {
  if (!count) return null
  return (
    <GlassCard className="p-4 section-mb-sm referral-unpaid-banner">
      <p className="text-sm-strong text-red section-mb-xs">{t('referrals.unpaidBannerTitle')}</p>
      <p className="text-sm text-muted">{t('referrals.unpaidBannerBody')}</p>
      <div className="stat-grid stat-grid-flush section-mt-sm">
        <div className="stat-tile">
          <p className="text-muted text-xs">{t('referrals.unpaidCount')}</p>
          <p className="text-md-strong text-red">{count}</p>
        </div>
        <div className="stat-tile">
          <p className="text-muted text-xs">{t('referrals.totalUnpaidFee')}</p>
          <p className="text-md-strong text-red">${totalFee.toFixed(2)}</p>
        </div>
        <div className="stat-tile">
          <p className="text-muted text-xs">{t('referrals.totalExpectedReward')}</p>
          <p className="text-md-strong text-green">${totalReward.toFixed(2)}</p>
        </div>
      </div>
    </GlassCard>
  )
}

function DownlineTable({
  users,
  emptyText,
  l1Rate,
  l2Rate,
  level,
  onViewLogs,
  t,
}: {
  users: any[]
  emptyText: string
  l1Rate: number
  l2Rate: number
  level: 1 | 2
  onViewLogs: (id: number, name?: string) => void
  t: (k: string, p?: Record<string, string | number>) => string
}) {
  const rate = level === 1 ? l1Rate : l2Rate
  const title = level === 1 ? t('referrals.l1Count') : t('referrals.l2Count')
  return (
    <GlassCard className="p-0 table-wrap">
      <div className="panel-header">
        <h3 className="panel-title-sm">
          {title} <span className="text-green">{rate}%</span>
        </h3>
      </div>
      <table className="data-table data-table-sm">
        <thead><tr>
          <th>{t('referrals.user')}</th>
          <th>{t('api.exchangeLabel')}</th>
          <th>{t('referrals.principal')}</th>
          <th>{t('referrals.balance')}</th>
          <th>{t('referrals.available')}</th>
          <th>{t('referrals.cyclePnl')}</th>
          <th>{t('referrals.totalPnl')}</th>
          <th>{t('referrals.unrealized')}</th>
          <th>{t('referrals.position')}</th>
          <th>{t('referrals.apiStatus')}</th>
          <th>{t('referrals.pendingPerfFee')}</th>
          <th>{t('referrals.settlementStatus')}</th>
          <th>{t('referrals.expectedReward')}</th>
          <th>{t('referrals.myReward')}</th>
          <th />
        </tr></thead>
        <tbody>
          {users.length === 0 ? (
            <tr><td colSpan={15} className="empty-cell">{emptyText}</td></tr>
          ) : users.map(u => (
            <tr key={u.id} className={(u.pending_perf_fee ?? 0) > 0 ? 'row-highlight' : undefined}>
              <td className="cell-ellipsis" title={u.display_name || u.email}>
                <div>{u.display_name || u.email}</div>
                <div className="text-muted text-xs">{u.uid}</div>
              </td>
              <td>{u.exchange || '—'}</td>
              <td>${(u.initial_principal ?? 0).toFixed(2)}</td>
              <td>${(u.live_equity ?? 0).toFixed(2)}</td>
              <td>${(u.available_balance ?? 0).toFixed(2)}</td>
              <td className={(u.cycle_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'}>${(u.cycle_pnl ?? 0).toFixed(2)}</td>
              <td className={(u.total_pnl ?? u.week_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'}>${(u.total_pnl ?? u.week_pnl ?? 0).toFixed(2)}</td>
              <td className={(u.unrealized_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'}>${(u.unrealized_pnl ?? 0).toFixed(2)}</td>
              <td>{u.has_open_position ? (u.position_side ? `${u.position_side} ${Number(u.position_qty || 0).toFixed(4)}` : t('referrals.hasPosition')) : '—'}</td>
              <td><span className="badge badge-gray">{u.api_status || '—'}</span></td>
              <td className={(u.pending_perf_fee ?? 0) > 0 ? 'text-red text-md-strong' : 'text-muted'}>
                {(u.pending_perf_fee ?? 0) > 0 ? `$${u.pending_perf_fee.toFixed(2)}` : '—'}
              </td>
              <td>{settlementCell(u, t)}</td>
              <td className={(u.expected_reward ?? 0) > 0 ? 'text-green' : 'text-muted'}>
                {(u.expected_reward ?? 0) > 0 ? `$${u.expected_reward.toFixed(2)}` : '—'}
              </td>
              <td className="text-green">${u.total_reward?.toFixed(2)}</td>
              <td>
                <button type="button" className="btn btn-ghost btn-xs" onClick={() => onViewLogs(u.id, u.display_name || u.email)}>
                  {t('referrals.viewLogs')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </GlassCard>
  )
}

export default function Referrals() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [data, setData] = useState<any>(null)
  const [ledger, setLedger] = useState<any[]>([])
  const [tab, setTab] = useState<TabKey>('overview')
  const [logsUser, setLogsUser] = useState<{ id: number; name?: string } | null>(null)

  useEffect(() => {
    const load = () => {
      referralApi.summary().then(setData)
      walletApi.rewardLedger().then(setLedger).catch(() => setLedger([]))
    }
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  const l1Rate = Math.round((data?.commission?.l1_rate ?? 0.1) * 100)
  const l2Rate = Math.round((data?.commission?.l2_rate ?? 0.05) * 100)
  const platformFeeRate = Math.round((data?.commission?.platform_fee_rate ?? 0.25) * 100)

  const tabs = [
    { key: 'overview', label: t('referrals.tabOverview') },
    { key: 'l1', label: t('referrals.tabL1') },
    { key: 'l2', label: t('referrals.tabL2') },
    { key: 'commissions', label: t('referrals.tabCommissions') },
  ]

  return (
    <Layout>
      <PageHeader title={t('referrals.title')} subtitle={t('referrals.subtitlePromo')} />

      {data?.referral_blocked && !data?.referral_invite_override && (() => {
        const copy = referralBlockCopy(t, data.referral_block_reason)
        return (
          <GlassCard className="p-4 section-mb-md referral-unpaid-banner">
            <p className="text-sm-strong text-red section-mb-xs">{copy.title}</p>
            <p className="text-sm text-muted">{copy.body}</p>
            <ReferralBlockDetailList
              details={data.referral_block_details || []}
              reason={data.referral_block_reason}
              t={t}
            />
          </GlassCard>
        )
      })()}

      <GlassCard className="p-4 section-mb-md invite-promo-banner">
        <div className="invite-promo-banner-inner">
          <div className="flex-gap-sm">
            <Link2 size={20} className="text-muted" />
            <div>
              <p className="text-sm font-medium">{t('inviteLink.bannerTitle')}</p>
              <p className="text-muted text-xs">{t('inviteLink.bannerHint')}</p>
            </div>
          </div>
          <Link to="/invite" className="btn btn-primary btn-sm">
            {t('nav.inviteLink')} <ArrowRight size={14} />
          </Link>
        </div>
      </GlassCard>

      <TabBar tabs={tabs} active={tab} onChange={k => setTab(k as TabKey)} />

      {tab === 'overview' && (
        <>
          <div className="stat-grid section-mt-sm">
            <StatCard label={t('referrals.l1Count')} value={String(data?.l1_count || 0)} />
            <StatCard label={t('referrals.l2Count')} value={String(data?.l2_count || 0)} />
            <StatCard label={t('referrals.l1Rewards')} value={`$${(data?.l1_total_rewards || 0).toFixed(2)}`} />
            <StatCard label={t('referrals.l2Rewards')} value={`$${(data?.l2_total_rewards || 0).toFixed(2)}`} />
            <StatCard label={t('referrals.rewardBalance')} value={`$${(data?.reward_balance || 0).toFixed(2)}`} />
            <StatCard label={t('referrals.pendingRewards')} value={`$${(data?.pending_rewards || 0).toFixed(2)}`} />
            <StatCard label={t('referrals.unpaidCount')} value={String(data?.unpaid_fee_count || 0)} />
            <StatCard label={t('referrals.totalUnpaidFee')} value={`$${(data?.total_unpaid_perf_fee || 0).toFixed(2)}`} />
            <StatCard label={t('referrals.totalExpectedReward')} value={`$${(data?.total_expected_reward || 0).toFixed(2)}`} />
          </div>

          <UnpaidFeeBanner
            count={data?.unpaid_fee_count || 0}
            totalFee={data?.total_unpaid_perf_fee || 0}
            totalReward={data?.total_expected_reward || 0}
            t={t}
          />

          <WithdrawCta>
            <p className="earnings-total">
              {t('referrals.totalEarnings')}{' '}
              <span className="text-green earnings-amount">${(data?.total_rewards || 0).toFixed(2)}</span>
            </p>
          </WithdrawCta>

          <GlassCard className="p-6 section-mb-lg section-mt-md">
            <h3 className="card-heading">{t('referrals.commissionSummary')}</h3>
            <div className="commission-grid">
              <div className="stat-tile stat-tile-highlight">
                <p className="stat-value-lg text-green">{l1Rate}%</p>
                <p className="stat-label-md">{t('referrals.l1Title')}</p>
              </div>
              <div className="stat-tile">
                <p className="stat-value-lg">{l2Rate}%</p>
                <p className="stat-label-md">{t('referrals.l2Title')}</p>
              </div>
              <div className="stat-tile">
                <p className="stat-value-lg">{platformFeeRate}%</p>
                <p className="stat-label-md">{t('referrals.baseTitle')}</p>
              </div>
            </div>
          </GlassCard>

          <ReferralTree />
        </>
      )}

      {tab === 'l1' && (
        <div className="section-mt-sm">
          <UnpaidFeeBanner
            count={(data?.l1_users || []).filter((u: any) => (u.pending_perf_fee ?? 0) > 0).length}
            totalFee={(data?.l1_users || []).reduce((s: number, u: any) => s + (u.pending_perf_fee || 0), 0)}
            totalReward={(data?.l1_users || []).reduce((s: number, u: any) => s + (u.expected_reward || 0), 0)}
            t={t}
          />
          <DownlineTable
            users={data?.l1_users || []}
            emptyText={t('referrals.inviteEmpty')}
            l1Rate={l1Rate}
            l2Rate={l2Rate}
            level={1}
            onViewLogs={(id, name) => setLogsUser({ id, name })}
            t={t}
          />
        </div>
      )}

      {tab === 'l2' && (
        <div className="section-mt-sm">
          <UnpaidFeeBanner
            count={(data?.l2_users || []).filter((u: any) => (u.pending_perf_fee ?? 0) > 0).length}
            totalFee={(data?.l2_users || []).reduce((s: number, u: any) => s + (u.pending_perf_fee || 0), 0)}
            totalReward={(data?.l2_users || []).reduce((s: number, u: any) => s + (u.expected_reward || 0), 0)}
            t={t}
          />
          <DownlineTable
            users={data?.l2_users || []}
            emptyText={t('referrals.l2Empty')}
            l1Rate={l1Rate}
            l2Rate={l2Rate}
            level={2}
            onViewLogs={(id, name) => setLogsUser({ id, name })}
            t={t}
          />
        </div>
      )}

      {tab === 'commissions' && (
        <>
          <GlassCard className="p-6 section-mb-lg section-mt-sm">
            <h3 className="panel-title-sm section-mb-sm">{t('referrals.commissionGuideTitle')}</h3>
            <p className="text-muted text-sm section-mb-md">{t('referrals.commissionGuideIntro')}</p>
            <ol className="text-sm text-muted commission-guide-list">
              <li>{t('referrals.commissionGuideStep1')}</li>
              <li>{t('referrals.commissionGuideStep2')}</li>
              <li>{t('referrals.commissionGuideStep3')}</li>
              <li>{t('referrals.commissionGuideStep4')}</li>
            </ol>
            <div className="commission-grid section-mt-md">
              <div className="stat-tile stat-tile-highlight">
                <p className="stat-value-lg text-green">{l1Rate}%</p>
                <p className="stat-label-md">{t('referrals.l1Title')}</p>
              </div>
              <div className="stat-tile">
                <p className="stat-value-lg">{l2Rate}%</p>
                <p className="stat-label-md">{t('referrals.l2Title')}</p>
              </div>
              <div className="stat-tile">
                <p className="stat-value-lg">{platformFeeRate}%</p>
                <p className="stat-label-md">{t('referrals.baseTitle')}</p>
              </div>
            </div>
          </GlassCard>
          <GlassCard className="p-0 table-wrap">
          <div className="panel-header">
            <h3 className="panel-title-sm">{t('referrals.commissionLedger')}</h3>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('common.time')}</th>
                <th>{t('referrals.ledgerType')}</th>
                <th>{t('admin.cols.amount')}</th>
                <th>{t('referrals.ledgerBalance')}</th>
                <th>{t('common.note')}</th>
              </tr>
            </thead>
            <tbody>
              {ledger.length === 0 ? (
                <tr><td colSpan={5} className="empty-cell">{t('referrals.ledgerEmpty')}</td></tr>
              ) : ledger.map(row => (
                <tr key={row.id}>
                  <td>{localeDate(row.created_at, locale)}</td>
                  <td><span className="badge badge-gray">{row.entry_type}</span></td>
                  <td className={row.amount >= 0 ? 'text-green' : 'text-red'}>${Number(row.amount).toFixed(2)}</td>
                  <td>${Number(row.balance_after).toFixed(2)}</td>
                  <td className="text-sm text-muted">{row.note || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
        </>
      )}

      {logsUser && (
        <DownlineLogsModal
          userId={logsUser.id}
          displayName={logsUser.name}
          onClose={() => setLogsUser(null)}
        />
      )}
    </Layout>
  )
}
