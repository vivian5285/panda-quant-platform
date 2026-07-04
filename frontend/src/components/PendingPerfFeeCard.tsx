import { Link } from 'react-router-dom'
import { Wallet, ArrowRight, AlertCircle } from 'lucide-react'
import GlassCard from './GlassCard'
import { useI18n } from '../i18n'
import { formatSettlementCycle } from '../utils/settlementCycle'

export type PendingSettlementBill = {
  id: number
  user_payable: number
  net_profit?: number
  platform_fee?: number
  payment_status: string
  period_start?: string
  period_end?: string
  cycle_days?: number
}

type Props = {
  settlement: PendingSettlementBill
  deferred?: boolean
  variant?: 'dashboard' | 'compact'
  showPayButton?: boolean
}

export default function PendingPerfFeeCard({
  settlement,
  deferred = false,
  variant = 'dashboard',
  showPayButton = true,
}: Props) {
  const { t } = useI18n()
  const amount = settlement.user_payable?.toFixed(2) ?? '—'
  const isPaid = settlement.payment_status === 'paid'
  const period =
    settlement.period_start && settlement.period_end
      ? `${settlement.period_start} ~ ${settlement.period_end}`
      : null

  return (
    <GlassCard
      className={`pending-perf-fee-card${deferred ? ' pending-perf-fee-card--deferred' : ''}${variant === 'compact' ? ' pending-perf-fee-card--compact' : ''}`}
    >
      <div className="pending-perf-fee-head">
        <div className="pending-perf-fee-icon">
          <Wallet size={22} />
        </div>
        <div className="pending-perf-fee-titles">
          <h3 className="panel-title-sm">
            {deferred ? t('pendingBill.deferredTitle') : t('pendingBill.title')}
          </h3>
          <p className="text-muted text-sm">
            {isPaid ? t('pendingBill.statusPaid') : t('pendingBill.statusPending')}
          </p>
        </div>
        <div className="pending-perf-fee-amount">
          <span className="pending-perf-fee-amount-label">{t('pendingBill.payable')}</span>
          <span className="pending-perf-fee-amount-value">${amount}</span>
          <span className="text-muted text-xs">USDT</span>
        </div>
      </div>

      <div className="pending-perf-fee-meta">
        {period && (
          <div className="pending-perf-fee-meta-item">
            <span className="text-muted text-xs">{t('pendingBill.period')}</span>
            <span className="text-sm">{period}</span>
          </div>
        )}
        {settlement.net_profit != null && (
          <div className="pending-perf-fee-meta-item">
            <span className="text-muted text-xs">{t('pendingBill.netProfit')}</span>
            <span className="text-sm text-green">+${settlement.net_profit.toFixed(2)}</span>
          </div>
        )}
        {settlement.cycle_days != null && (
          <div className="pending-perf-fee-meta-item">
            <span className="text-muted text-xs">{t('pendingBill.cycle')}</span>
            <span className="text-sm">{formatSettlementCycle(settlement.cycle_days, t)}</span>
          </div>
        )}
      </div>

      <div className="pending-perf-fee-tips">
        <AlertCircle size={14} className="text-muted" />
        <p className="text-muted text-sm">
          {deferred ? t('pendingBill.deferredTip', { amount }) : t('pendingBill.tip')}
        </p>
      </div>

      {showPayButton && (
        <div className="pending-perf-fee-actions">
          <Link to="/settlements?pay=1" className="btn btn-primary">
            {t('pendingBill.payNow')}
            <ArrowRight size={16} />
          </Link>
          <Link to="/settlements" className="btn btn-ghost btn-sm">
            {t('pendingBill.viewDetail')}
          </Link>
        </div>
      )}
    </GlassCard>
  )
}
