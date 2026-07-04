import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { Copy, Check, Link2, Image, Download, Share2, QrCode, Moon, Sun } from 'lucide-react'
import { useTranslation } from '../i18n'
import GlassCard from './GlassCard'
import { displayReferralCode } from '../utils/referralCode'
import type { PosterTheme } from '../utils/invitePoster'

type InviteData = {
  invite_url?: string
  referral_code?: string
  uid?: string
  display_name?: string
}

type Props = {
  data: InviteData | null
  copied: string
  onCopy: (text: string, key: string) => void
  onShare: () => void
  posterTheme: PosterTheme
  onPosterThemeChange: (theme: PosterTheme) => void
  onGeneratePoster: () => void
  posterLoading: boolean
  posterUrl?: string
  showPoster?: boolean
  onDownloadPoster?: () => void
  onClosePoster?: () => void
  referralBlocked?: boolean
}

export default function InviteSharePanel({
  data,
  copied,
  onCopy,
  onShare,
  posterTheme,
  onPosterThemeChange,
  onGeneratePoster,
  posterLoading,
  posterUrl,
  showPoster,
  onDownloadPoster,
  onClosePoster,
  referralBlocked = false,
}: Props) {
  const { t } = useTranslation()
  const [qrUrl, setQrUrl] = useState('')
  const displayCode = displayReferralCode(data?.referral_code)

  useEffect(() => {
    if (!data?.invite_url) {
      setQrUrl('')
      return
    }
    QRCode.toDataURL(data.invite_url, {
      width: 280,
      margin: 2,
      color: { dark: '#0f172a', light: '#ffffff' },
    }).then(setQrUrl).catch(() => setQrUrl(''))
  }, [data?.invite_url])

  return (
    <>
      <GlassCard className="p-0 section-mb-lg invite-share-card card-overflow-hidden">
        <div className="invite-share-hero">
          <p className="invite-share-kicker">{t('referrals.inviteKicker')}</p>
          <h2 className="invite-share-title">{t('referrals.inviteHeroTitle')}</h2>
          <p className="invite-share-sub">{t('referrals.inviteHeroSub')}</p>
        </div>
        <div className="invite-share-body">
          {referralBlocked && (
            <div className="p-4 section-mb-sm referral-unpaid-banner">
              <p className="text-sm-strong text-red section-mb-xs">{t('referrals.creditDefaultBannerTitle')}</p>
              <p className="text-sm text-muted">{t('referrals.creditDefaultBannerBody')}</p>
            </div>
          )}
          <div className="invite-share-main">
            <p className="text-muted invite-share-label">{t('referrals.myLink')}</p>
            <div className="invite-link-box">
              <code>{data?.invite_url || t('common.loading')}</code>
            </div>
            <div className="invite-meta-chips">
              <span className="invite-chip">
                {t('referrals.referralCode')}{' '}
                <strong>{displayCode}</strong>
              </span>
              <span className="invite-chip">
                {t('referrals.uidLine', { uid: data?.uid ?? '—' })}
              </span>
              {data?.display_name && (
                <span className="invite-chip">{data.display_name}</span>
              )}
            </div>
            <div className="invite-action-grid">
              <button type="button" className="btn btn-primary" disabled={referralBlocked} onClick={() => onCopy(data?.invite_url || '', 'link')}>
                {copied === 'link' ? <Check size={16} /> : <Link2 size={16} />}
                {copied === 'link' ? t('referrals.copyLinkDone') : t('referrals.copyLink')}
              </button>
              <button type="button" className="btn btn-ghost" disabled={referralBlocked} onClick={() => onCopy(displayCode, 'code')}>
                {copied === 'code' ? <Check size={16} /> : <Copy size={16} />}
                {copied === 'code' ? t('common.copied') : t('referrals.copyCode')}
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => onCopy(String(data?.uid || ''), 'uid')}>
                {copied === 'uid' ? <Check size={16} /> : <Copy size={16} />}
                {copied === 'uid' ? t('common.copied') : t('referrals.copyUid')}
              </button>
              <button type="button" className="btn btn-ghost" disabled={referralBlocked} onClick={onShare}>
                <Share2 size={16} /> {t('referrals.share')}
              </button>
            </div>
            <div className="poster-theme-picker section-mt-sm">
              <p className="text-muted invite-share-label">{t('referrals.posterThemeLabel')}</p>
              <div className="poster-theme-grid">
                <button
                  type="button"
                  className={`poster-theme-card ${posterTheme === 'dark' ? 'poster-theme-card-active' : ''}`}
                  onClick={() => onPosterThemeChange('dark')}
                >
                  <span className="poster-theme-swatch poster-theme-swatch-dark"><Moon size={18} /></span>
                  <span className="poster-theme-name">{t('referrals.posterThemeDark')}</span>
                  <span className="poster-theme-desc">{t('referrals.posterThemeDarkDesc')}</span>
                </button>
                <button
                  type="button"
                  className={`poster-theme-card ${posterTheme === 'light' ? 'poster-theme-card-active' : ''}`}
                  onClick={() => onPosterThemeChange('light')}
                >
                  <span className="poster-theme-swatch poster-theme-swatch-light"><Sun size={18} /></span>
                  <span className="poster-theme-name">{t('referrals.posterThemeLight')}</span>
                  <span className="poster-theme-desc">{t('referrals.posterThemeLightDesc')}</span>
                </button>
              </div>
              <button type="button" className="btn btn-ghost invite-poster-btn section-mt-sm" onClick={onGeneratePoster} disabled={posterLoading || referralBlocked}>
                <Image size={16} /> {posterLoading ? t('referrals.genPosterLoading') : t('referrals.genPoster')}
              </button>
            </div>
          </div>
          <div className="invite-qr-panel">
            <div className="invite-qr-frame">
              {qrUrl ? (
                <img src={qrUrl} alt={t('referrals.scanToRegister')} className="invite-qr-img" />
              ) : (
                <div className="invite-qr-placeholder"><QrCode size={48} /></div>
              )}
            </div>
            <p className="invite-qr-caption">{t('referrals.scanToRegister')}</p>
            <p className="invite-qr-bind text-muted">{t('referrals.qrBindHint', { uid: data?.uid ?? '—' })}</p>
          </div>
        </div>
      </GlassCard>

      {showPoster && posterUrl && (
        <GlassCard className="p-6 section-mb-lg poster-preview-card">
          <h3 className="card-heading">{t('referrals.posterPreview')}</h3>
          <p className="text-muted text-sm section-mb-sm">{t('referrals.posterPreviewHint')}</p>
          <img src={posterUrl} alt={t('referrals.posterAlt')} className="poster-img" />
          <div className="flex-center-gap section-mt-md">
            <button type="button" className="btn btn-primary" onClick={onDownloadPoster}>
              <Download size={16} /> {t('referrals.downloadPoster')}
            </button>
            <button type="button" className="btn btn-ghost" onClick={onClosePoster}>{t('referrals.closePreview')}</button>
          </div>
        </GlassCard>
      )}
    </>
  )
}
