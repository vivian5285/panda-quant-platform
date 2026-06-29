import { Link } from 'react-router-dom'
import { Wallet } from 'lucide-react'
import GlassCard from './GlassCard'
import { useI18n } from '../i18n'

export type PendingSettlement = {
  id: number
  user_payable: number
  payment_status: string
  period_start?: string
  period_end?: string
}

type Props = {
  blocked?: boolean
  settlement?: PendingSettlement | null
}

export default function SettlementGateBanner({ blocked, settlement }: Props) {
  const { t } = useI18n()
  if (!blocked) return null

  const amount = settlement?.user_payable?.toFixed(2) ?? '—'
  const statusKey = settlement?.payment_status
  const statusHint = statusKey === 'paid'
    ? t('settlementGate.awaitingConfirm')
    : t('settlementGate.awaitingPayment')

  return (
    <GlassCard className="p-4 settlement-gate-banner">
      <Wallet size={20} />
      <div className="settlement-gate-body">
        <strong>{t('settlementGate.title')}</strong>
        <p className="text-muted text-sm">
          {t('settlementGate.body', { amount })}
          {' '}
          {statusHint}
        </p>
        <Link to="/settlements" className="settlement-gate-link">
          {t('settlementGate.cta')}
        </Link>
      </div>
    </GlassCard>
  )
}
