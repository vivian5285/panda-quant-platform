import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import { referralApi } from '../api'
import { useI18n } from '../i18n'
import { generateInvitePoster, downloadPoster } from '../utils/invitePoster'
import { Copy, Check, Link2, Image, Download, Share2 } from 'lucide-react'

export default function Referrals() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [data, setData] = useState<any>(null)
  const [copied, setCopied] = useState('')
  const [posterUrl, setPosterUrl] = useState('')
  const [posterLoading, setPosterLoading] = useState(false)
  const [showPoster, setShowPoster] = useState(false)

  useEffect(() => { referralApi.summary().then(setData) }, [])

  const copyText = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

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

      <GlassCard green className="p-6" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <p className="text-muted" style={{ fontSize: 13, marginBottom: 8 }}>{t('referrals.myLink')}</p>
            <p className="link-box" style={{ fontSize: 14, lineHeight: 1.6 }}>
              {data?.invite_url || '...'}
            </p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8 }}>
              {t('referrals.referralCode')} <span className="text-green" style={{ fontWeight: 600 }}>{data?.referral_code}</span>
              {' · '}UID {data?.uid}
            </p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 140 }}>
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
        <GlassCard className="p-6" style={{ marginBottom: 24, textAlign: 'center' }}>
          <h3 className="card-heading">{t('referrals.posterPreview')}</h3>
          <img src={posterUrl} alt="邀请海报" style={{
            maxWidth: '100%', width: 375, borderRadius: 16,
            boxShadow: 'var(--glass-shadow-lg)',
          }} />
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 20, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={() => downloadPoster(posterUrl, `panda-invite-${data?.referral_code}.png`)}>
              <Download size={16} /> {t('referrals.downloadPoster')}
            </button>
            <button className="btn btn-ghost" onClick={() => setShowPoster(false)}>{t('referrals.closePreview')}</button>
          </div>
        </GlassCard>
      )}

      <GlassCard className="p-6" style={{ marginBottom: 24 }}>
        <h3 className="card-heading">{t('referrals.rulesTitle')}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
          <div className="stat-tile stat-tile-highlight">
            <p style={{ fontSize: 28, fontWeight: 700, color: 'var(--accent-success)' }}>{Math.round((data?.commission?.l1_rate ?? 0.1) * 100)}%</p>
            <p style={{ fontSize: 14, fontWeight: 500, marginTop: 4 }}>{t('referrals.l1Title')}</p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>{t('referrals.l1Desc')}</p>
          </div>
          <div className="stat-tile">
            <p style={{ fontSize: 28, fontWeight: 700 }}>{Math.round((data?.commission?.l2_rate ?? 0.05) * 100)}%</p>
            <p style={{ fontSize: 14, fontWeight: 500, marginTop: 4 }}>{t('referrals.l2Title')}</p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>{t('referrals.l2Desc')}</p>
          </div>
          <div className="stat-tile">
            <p style={{ fontSize: 28, fontWeight: 700 }}>25%</p>
            <p style={{ fontSize: 14, fontWeight: 500, marginTop: 4 }}>{t('referrals.baseTitle')}</p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>{t('referrals.baseDesc')}</p>
          </div>
        </div>
        <p className="text-muted" style={{ fontSize: 12, marginTop: 16 }}>✓ {t('referrals.autoCredit')}</p>
      </GlassCard>

      <div className="stat-grid">
        <StatCard label={t('referrals.l1Count')} value={String(data?.l1_count || 0)} />
        <StatCard label={t('referrals.l2Count')} value={String(data?.l2_count || 0)} />
        <StatCard label={t('referrals.l1Rewards')} value={`$${(data?.l1_total_rewards || 0).toFixed(2)}`} />
        <StatCard label={t('referrals.l2Rewards')} value={`$${(data?.l2_total_rewards || 0).toFixed(2)}`} />
        <StatCard label={t('referrals.rewardBalance')} value={`$${(data?.reward_balance || 0).toFixed(2)}`} />
        <StatCard label={t('referrals.pendingRewards')} value={`$${(data?.pending_rewards || 0).toFixed(2)}`} />
      </div>

      <GlassCard className="p-4" style={{ marginBottom: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <p style={{ fontSize: 14 }}>{t('referrals.totalEarnings')} <span className="text-green" style={{ fontSize: 20, fontWeight: 600 }}>${(data?.total_rewards || 0).toFixed(2)}</span></p>
        <Link to="/withdraw" className="btn btn-primary" style={{ textDecoration: 'none' }}>{t('referrals.withdrawLink')}</Link>
      </GlassCard>

      <div key={locale} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <GlassCard className="p-0 table-wrap">
          <div className="panel-header">
            <h3 style={{ fontSize: 15 }}>{t('referrals.l1Count')} <span className="text-green">{Math.round((data?.commission?.l1_rate ?? 0.1) * 100)}%</span></h3>
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
            <h3 style={{ fontSize: 15 }}>{t('referrals.l2Count')} <span className="text-green">{Math.round((data?.commission?.l2_rate ?? 0.05) * 100)}%</span></h3>
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

      <style>{`@media (max-width: 768px) { div[style*="grid-template-columns: 1fr 1fr"] { grid-template-columns: 1fr !important; } }`}</style>
    </Layout>
  )
}
