import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, BookOpen } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import InviteSharePanel from '../components/InviteSharePanel'
import { referralApi } from '../api'
import { useI18n } from '../i18n'
import { generateInvitePoster, downloadPoster, type PosterTheme } from '../utils/invitePoster'
import { displayReferralCode } from '../utils/referralCode'

export default function InviteLink() {
  const t = useI18n(s => s.t)
  const [data, setData] = useState<any>(null)
  const [copied, setCopied] = useState('')
  const [posterUrl, setPosterUrl] = useState('')
  const [posterLoading, setPosterLoading] = useState(false)
  const [showPoster, setShowPoster] = useState(false)
  const [posterTheme, setPosterTheme] = useState<PosterTheme>('dark')

  useEffect(() => {
    referralApi.summary().then(setData)
  }, [])

  const copyText = (text: string, key: string) => {
    if (!text) return
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const l1Rate = Math.round((data?.commission?.l1_rate ?? 0.1) * 100)
  const l2Rate = Math.round((data?.commission?.l2_rate ?? 0.05) * 100)

  const posterLabels = (theme: PosterTheme) => {
    if (theme === 'light') {
      return {
        headline: t('referrals.posterLightHeadline'),
        advantagesTitle: t('referrals.posterLightAdvantagesTitle'),
        advantages: [
          { title: t('referrals.posterLightAdv1Title'), desc: t('referrals.posterLightAdv1Desc') },
          { title: t('referrals.posterLightAdv2Title'), desc: t('referrals.posterLightAdv2Desc') },
          { title: t('referrals.posterLightAdv3Title'), desc: t('referrals.posterLightAdv3Desc') },
        ] as [{ title: string; desc: string }, { title: string; desc: string }, { title: string; desc: string }],
        scanHint: t('referrals.posterLightScanHint'),
        inviterLine: t('referrals.posterInviterLine'),
        inviterUidLabel: t('referrals.posterInviterUid', { uid: data?.uid ?? '—' }),
        disclaimer: t('referrals.posterLightDisclaimer'),
      }
    }
    return {
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
    }
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
        brandName: t('brand.name'),
        brandTagline: t('brand.tagline'),
        posterTagline: posterTheme === 'light' ? t('referrals.posterLightTagline') : t('referrals.posterTagline'),
        labels: posterLabels(posterTheme),
        theme: posterTheme,
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
      <PageHeader title={t('inviteLink.title')} subtitle={t('inviteLink.subtitle')} />

      <GlassCard className="p-5 section-mb-lg invite-guide-banner">
        <div className="invite-guide-banner-inner">
          <BookOpen size={22} className="invite-guide-icon" />
          <div className="invite-guide-text">
            <h3 className="card-heading">{t('inviteLink.guideBannerTitle')}</h3>
            <p className="text-muted text-sm">{t('inviteLink.guideBannerDesc')}</p>
          </div>
          <Link to="/guide" className="btn btn-ghost btn-sm inline-flex-gap invite-guide-cta">
            {t('inviteLink.guideBannerCta')} <ArrowRight size={14} />
          </Link>
        </div>
      </GlassCard>

      <InviteSharePanel
        data={data}
        copied={copied}
        onCopy={copyText}
        onShare={shareLink}
        posterTheme={posterTheme}
        onPosterThemeChange={setPosterTheme}
        onGeneratePoster={generatePoster}
        posterLoading={posterLoading}
        posterUrl={posterUrl}
        showPoster={showPoster}
        onDownloadPoster={() => downloadPoster(
          posterUrl,
          t('referrals.posterFilename', { code: displayReferralCode(data?.referral_code) || 'invite' }),
        )}
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
        </div>
        <p className="text-muted text-xs section-mt-md">✓ {t('referrals.autoCredit')}</p>
        <Link to="/referrals" className="btn btn-ghost btn-sm section-mt-sm inline-flex-gap">
          {t('inviteLink.viewPromoCenter')} <ArrowRight size={14} />
        </Link>
      </GlassCard>
    </Layout>
  )
}
