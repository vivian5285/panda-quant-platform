import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import WithdrawCta from '../components/WithdrawCta'
import { referralApi } from '../api'
import { useI18n } from '../i18n'
import { generateInvitePoster, downloadPoster } from '../utils/invitePoster'
import { Copy, Check, Link2, Image, Download, Share2 } from 'lucide-react'
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
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const l1Rate = Math.round((data?.commission?.l1_rate ?? 0.1) * 100)
  const l2Rate = Math.round((data?.commission?.l2_rate ?? 0.05) * 100)
  const platformFeeRate = Math.round((data?.commission?.platform_fee_rate ?? 0.25) * 100)

  const generatePoster = async () => {
    if (!data) return
    setPosterLoading(true)
    try {
      const url = await generateInvitePoster({
        inviteUrl: data.invite_url,
        referralCode: data.referral_code,
        displayName: data.display_name || t('referrals.defaultName'),
        uid: data.uid,
        l1Rate: data.commission?.l1_rate ?? 0.1,
        l2Rate: data.commission?.l2_rate ?? 0.05,
        brandName: t('brand.name'),
        brandTagline: t('brand.tagline'),
        posterTagline: t('referrals.posterTagline'),
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

      <GlassCard className="p-6 section-mb-lg">
        <div className="referral-link-row">
          <div className="referral-link-main">
            <p className="text-muted referral-link-label">{t('referrals.myLink')}</p>
            <p className="link-box link-box-lg">
              {data?.invite_url || t('common.loading')}
            </p>
            <p className="text-muted referral-code-meta">
              {t('referrals.referralCode')}{' '}
              <span className="text-green text-semibold">{data?.referral_code}</span>
              {' · '}{t('referrals.uidLine', { uid: data?.uid ?? '—' })}
            </p>
          </div>
          <div className="referral-actions">
            <button className="btn btn-primary" onClick={() => copyText(data?.invite_url, 'link')}>
              {copied === 'link' ? <Check size={16} /> : <Link2 size={16} />}
              {copied === 'link' ? t('referrals.copyLinkDone') : t('referrals.copyLink')}
            </button>
            <button className="btn btn-ghost" onClick={() => copyText(data?.referral_code, 'code')}>
              {copied === 'code' ? <Check size={16} /> : <Copy size={16} />}
              {copied === 'code' ? t('common.copied') : t('referrals.copyCode')}
            </button>
            <button className="btn btn-ghost" onClick={shareLink}>
              <Share2 size={16} /> {t('referrals.share')}
            </button>
            <button className="btn btn-ghost" onClick={generatePoster} disabled={posterLoading}>
              <Image size={16} /> {posterLoading ? t('referrals.genPosterLoading') : t('referrals.genPoster')}
            </button>
          </div>
        </div>
      </GlassCard>

      {showPoster && posterUrl && (
        <GlassCard className="p-6 section-mb-lg poster-preview-card">
          <h3 className="card-heading">{t('referrals.posterPreview')}</h3>
          <img src={posterUrl} alt={t('referrals.posterAlt')} className="poster-img" />
          <div className="flex-center-gap section-mt-md">
            <button
              className="btn btn-primary"
              onClick={() => downloadPoster(posterUrl, t('referrals.posterFilename', { code: data?.referral_code || 'invite' }))}
            >
              <Download size={16} /> {t('referrals.downloadPoster')}
            </button>
            <button className="btn btn-ghost" onClick={() => setShowPoster(false)}>{t('referrals.closePreview')}</button>
          </div>
        </GlassCard>
      )}

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
          <table className="data-table">
            <thead><tr><th>{t('referrals.user')}</th><th>{t('referrals.totalPnl')}</th><th>{t('referrals.myReward')}</th></tr></thead>
            <tbody>
              {(data?.l1_users || []).length === 0 ? (
                <tr><td colSpan={3} className="empty-cell">{t('referrals.inviteEmpty')}</td></tr>
              ) : data.l1_users.map((u: any) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td className={u.week_pnl >= 0 ? 'text-green' : 'text-red'}>${u.week_pnl?.toFixed(2)}</td>
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
          <table className="data-table">
            <thead><tr><th>{t('referrals.user')}</th><th>{t('referrals.totalPnl')}</th><th>{t('referrals.myReward')}</th></tr></thead>
            <tbody>
              {(data?.l2_users || []).length === 0 ? (
                <tr><td colSpan={3} className="empty-cell">{t('referrals.l2Empty')}</td></tr>
              ) : data.l2_users.map((u: any) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td className={u.week_pnl >= 0 ? 'text-green' : 'text-red'}>${u.week_pnl?.toFixed(2)}</td>
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
