import { AlertTriangle } from 'lucide-react'

export type ReferralBlockDetail = {
  user_id: number
  platform_uid: string
  display_name: string
  level: number
  scope: string
  pending_perf_fee: number
  settlement_status?: string | null
  exchange?: string | null
}

type Props = {
  details: ReferralBlockDetail[]
  reason?: string | null
  t: (k: string, p?: Record<string, string | number>) => string
}

function levelLabel(t: Props['t'], level: number, scope: string) {
  if (scope === 'own' || level === 0) return t('referrals.blockDetailOwn')
  if (level === 1) return t('referrals.blockDetailLevelL1')
  if (level === 2) return t('referrals.blockDetailLevelL2')
  return t('referrals.blockDetailLevelN', { level })
}

export default function ReferralBlockDetailList({ details, reason, t }: Props) {
  if (!details?.length) return null

  return (
    <div className="referral-block-details section-mt-sm">
      <div className="flex-gap-sm section-mb-xs">
        <AlertTriangle size={16} className="text-red" />
        <p className="text-sm-strong text-red">{t('referrals.blockDetailTitle')}</p>
      </div>
      {reason && (
        <p className="text-xs text-muted section-mb-sm">
          {t(`referrals.blockReason.${reason}` as any) || reason}
        </p>
      )}
      <ul className="referral-block-detail-list">
        {details.map(d => (
          <li key={`${d.user_id}-${d.level}`} className="referral-block-detail-item">
            <div className="referral-block-detail-head">
              <span className="badge badge-red badge-spaced">
                {levelLabel(t, d.level, d.scope)}
              </span>
              <span className="text-sm-strong">{d.display_name || d.platform_uid}</span>
            </div>
            <div className="referral-block-detail-meta text-xs text-muted">
              <span>{t('referrals.blockDetailUid')}: {d.platform_uid}</span>
              {d.exchange && (
                <span> · {t('api.exchangeLabel')}: {d.exchange}</span>
              )}
              <span className="text-red">
                {' · '}{t('referrals.blockDetailFee')}: ${d.pending_perf_fee.toFixed(2)}
              </span>
              {d.settlement_status && d.settlement_status !== 'none' && (
                <span> · {t('referrals.settlementStatus')}: {d.settlement_status}</span>
              )}
            </div>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted section-mt-sm">{t('referrals.blockDetailAction')}</p>
    </div>
  )
}
