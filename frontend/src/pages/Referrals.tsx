import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import WithdrawCta from '../components/WithdrawCta'
import InviteSharePanel from '../components/InviteSharePanel'
import { referralApi } from '../api'
import { useI18n } from '../i18n'
import { generateInvitePoster, downloadPoster } from '../utils/invitePoster'
import ReferralTree from '../components/ReferralTree'
import DualPathIntro from '../components/DualPathIntro'

export default function Referrals() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [data, setData] = useState<any>(null)
  const [copied, setCopied] = useState('')
  const [posterUrl, setPosterUrl] = useState('')
  const [posterLoading, setPosterLoading] = useState(false)
  const [showPoster, setShowPoster] = useState(false)

  useEffect(() => {
    referralApi.summary().then(setData)
    const timer = setInterval(() => referralApi.summary().then(setData), 30000)
    return () => clearInterval(timer)
  }, [])

  const copyText = (text: string, key: string) => {
    if (!text) return
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const l1Rate = Math.round((data?.commission?.l1_rate ?? 0.1) * 100)
  const l2Rate = Math.round((data?.commission?.l2_rate ?? 0.05) * 100)
  const platformFeeRate = Math.round((data?.commission?.platform_fee_rate ?? 0.25) * 100)

  const posterLabels = () => ({
    headline: t('referrals.posterHeadline'),
    advantagesTitle: t('referrals.posterAdvantagesTitle'),
    advantages: [
      { title: t('referrals.posterAdv1Title'), desc: t('referrals.posterAdv1Desc') },
      { title: t('referrals.posterAdv2Title'), desc: t('referrals.posterAdv2Desc') },
      { title: t('referrals.posterAdv3Title'), desc: t('referrals.posterAdv3Desc') },
    ] as [{ title: string; desc: string }, { title: string; desc: string }, { title: string; desc: string }],
    scanHint: t('referrals.scanToRegister'),
    inviterLine: t('referrals.posterInviterLine'),
    inviterUidLabel: t('referrals.posterInviterUid', { uid: data?.uid ?? '—' }),
    disclaimer: t('referrals.posterDisclaimer'),
  })

  const generatePoster = async () => {
    if (!data) return
    setPosterLoading(true)
    try {
      const url = await generateInvitePoster({
        inviteUrl: data.invite_url,
        referralCode: data.referral_code,
        displayName: data.display_name || t('referrals.defaultName'),
        uid: data.uid,
        brandName: t('brand.name'),
        brandTagline: t('brand.tagline'),
        posterTagline: t('referrals.posterTagline'),
        labels: posterLabels(),
      })
      setPosterUrl(url)
      setShowPoster(true)
    } finally {
      setPosterLoading(false)
    }
  }

  const shareLink = async () => {
    if (!data?.invite_url) return
    if (navigator.share) {
      try {
        await navigator.share({
          title: t('referrals.shareTitle'),
          text: t('referrals.shareText'),
          url: data.invite_url,
        })
      } catch { /* cancelled */ }
    } else {
      copyText(data.invite_url, 'share')
    }
  }

  return (
    <Layout>
      <PageHeader title={t('referrals.title')} subtitle={t('referrals.subtitle')} />

      <DualPathIntro />

      <InviteSharePanel
        data={data}
        copied={copied}
        onCopy={copyText}
        onShare={shareLink}
        onGeneratePoster={generatePoster}
        posterLoading={posterLoading}
        posterUrl={posterUrl}
        showPoster={showPoster}
        onDownloadPoster={() => downloadPoster(posterUrl, t('referrals.posterFilename', { code: data?.referral_code || 'invite' }))}
        onClosePoster={() => setShowPoster(false)}
      />

      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('referrals.rulesTitle')}</h3>
        <div className="commission-grid">
          <div className="stat-tile stat-tile-highlight">
            <p className="stat-value-lg text-green">{l1Rate}%</p>
            <p className="stat-label-md">{t('referrals.l1Title')}</p>
            <p className="text-muted stat-desc-sm">{t('referrals.l1Desc')}</p>
          </div>
          <div className="stat-tile">
            <p className="stat-value-lg">{l2Rate}%</p>
            <p className="stat-label-md">{t('referrals.l2Title')}</p>
            <p className="text-muted stat-desc-sm">{t('referrals.l2Desc')}</p>
          </div>
          <div className="stat-tile">
            <p className="stat-value-lg">{platformFeeRate}%</p>
            <p className="stat-label-md">{t('referrals.baseTitle')}</p>
            <p className="text-muted stat-desc-sm">{t('referrals.baseDesc')}</p>
          </div>
        </div>
        <p className="text-muted text-xs section-mt-md">✓ {t('referrals.autoCredit')}</p>
        <p className="text-muted text-xs section-mt-xs">{t('perfFee.rewardPool')}</p>
      </GlassCard>

      <ReferralTree />

      <div className="stat-grid">
        <StatCard label={t('referrals.l1Count')} value={String(data?.l1_count || 0)} />
        <StatCard label={t('referrals.l2Count')} value={String(data?.l2_count || 0)} />
        <StatCard label={t('referrals.l1Rewards')} value={`$${(data?.l1_total_rewards || 0).toFixed(2)}`} />
        <StatCard label={t('referrals.l2Rewards')} value={`$${(data?.l2_total_rewards || 0).toFixed(2)}`} />
        <StatCard label={t('referrals.rewardBalance')} value={`$${(data?.reward_balance || 0).toFixed(2)}`} />
        <StatCard label={t('referrals.pendingRewards')} value={`$${(data?.pending_rewards || 0).toFixed(2)}`} />
      </div>

      <WithdrawCta>
        <p className="earnings-total">
          {t('referrals.totalEarnings')}{' '}
          <span className="text-green earnings-amount">${(data?.total_rewards || 0).toFixed(2)}</span>
        </p>
      </WithdrawCta>

      <div key={locale} className="grid-2-col">
        <GlassCard className="p-0 table-wrap">
          <div className="panel-header">
            <h3 className="panel-title-sm">
              {t('referrals.l1Count')} <span className="text-green">{l1Rate}%</span>
            </h3>
          </div>
          <table className="data-table data-table-sm">
            <thead><tr>
              <th>{t('referrals.user')}</th>
              <th>{t('referrals.principal')}</th>
              <th>{t('referrals.balance')}</th>
              <th>{t('referrals.cyclePnl')}</th>
              <th>{t('referrals.totalPnl')}</th>
              <th>{t('referrals.position')}</th>
              <th>{t('referrals.settlementStatus')}</th>
              <th>{t('referrals.myReward')}</th>
            </tr></thead>
            <tbody>
              {(data?.l1_users || []).length === 0 ? (
                <tr><td colSpan={8} className="empty-cell">{t('referrals.inviteEmpty')}</td></tr>
              ) : data.l1_users.map((u: any) => (
                <tr key={u.id}>
                  <td className="cell-ellipsis" title={u.display_name || u.email}>
                    <div>{u.display_name || u.email}</div>
                    <div className="text-muted text-xs">{u.uid}</div>
                  </td>
                  <td>${(u.initial_principal ?? 0).toFixed(2)}</td>
                  <td>${(u.live_equity ?? 0).toFixed(2)}</td>
                  <td className={(u.cycle_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'}>${(u.cycle_pnl ?? 0).toFixed(2)}</td>
                  <td className={(u.total_pnl ?? u.week_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'}>${(u.total_pnl ?? u.week_pnl ?? 0).toFixed(2)}</td>
                  <td>{u.has_open_position ? (u.position_side ? `${u.position_side} ${u.position_qty}` : t('referrals.hasPosition')) : '—'}</td>
                  <td><span className="badge badge-gray">{u.settlement_status || 'none'}</span></td>
                  <td className="text-green">${u.total_reward?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>

        <GlassCard className="p-0 table-wrap">
          <div className="panel-header">
            <h3 className="panel-title-sm">
              {t('referrals.l2Count')} <span className="text-green">{l2Rate}%</span>
            </h3>
          </div>
          <table className="data-table data-table-sm">
            <thead><tr>
              <th>{t('referrals.user')}</th>
              <th>{t('referrals.principal')}</th>
              <th>{t('referrals.balance')}</th>
              <th>{t('referrals.cyclePnl')}</th>
              <th>{t('referrals.totalPnl')}</th>
              <th>{t('referrals.position')}</th>
              <th>{t('referrals.settlementStatus')}</th>
              <th>{t('referrals.myReward')}</th>
            </tr></thead>
            <tbody>
              {(data?.l2_users || []).length === 0 ? (
                <tr><td colSpan={8} className="empty-cell">{t('referrals.l2Empty')}</td></tr>
              ) : data.l2_users.map((u: any) => (
                <tr key={u.id}>
                  <td className="cell-ellipsis" title={u.display_name || u.email}>
                    <div>{u.display_name || u.email}</div>
                    <div className="text-muted text-xs">{u.uid}</div>
                  </td>
                  <td>${(u.initial_principal ?? 0).toFixed(2)}</td>
                  <td>${(u.live_equity ?? 0).toFixed(2)}</td>
                  <td className={(u.cycle_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'}>${(u.cycle_pnl ?? 0).toFixed(2)}</td>
                  <td className={(u.total_pnl ?? u.week_pnl ?? 0) >= 0 ? 'text-green' : 'text-red'}>${(u.total_pnl ?? u.week_pnl ?? 0).toFixed(2)}</td>
                  <td>{u.has_open_position ? (u.position_side ? `${u.position_side} ${u.position_qty}` : t('referrals.hasPosition')) : '—'}</td>
                  <td><span className="badge badge-gray">{u.settlement_status || 'none'}</span></td>
                  <td className="text-green">${u.total_reward?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      </div>
    </Layout>
  )
}
