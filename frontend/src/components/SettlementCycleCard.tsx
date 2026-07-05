import { CalendarClock, TrendingUp, Wallet, AlertTriangle, Sparkles } from 'lucide-react'
import GlassCard from './GlassCard'
import StatCard from './StatCard'
import { useI18n } from '../i18n'

export type SettlementCycleStatus = {
  cycle_start: string
  cycle_end_scheduled: string
  target_days: number
  days_elapsed: number
  days_remaining: number
  progress_pct: number
  rollover_count: number
  phase: string
  has_open_position: boolean
  initial_principal: number
  high_water_mark: number
  cycle_trade_pnl: number
  cycle_equity_delta: number
  cycle_net_profit: number
  estimated_fee: number
  is_profitable: boolean
  requires_flat: boolean
  pending_settlement_id?: number | null
  pending_payable: number
  historical_settled_cycles: number
  settlement_awaiting_flat: boolean
}

type Props = {
  status: SettlementCycleStatus
  onPayClick?: () => void
}

export default function SettlementCycleCard({ status, onPayClick }: Props) {
  const { t } = useI18n()
  const phaseKey = `settlements.cyclePhase.${status.phase}`
  const phaseLabel = t(phaseKey) || status.phase
  const pnlPositive = status.cycle_trade_pnl >= 0

  return (
    <GlassCard className="p-5 settlement-cycle-card">
      <div className="settlement-cycle-head">
        <div className="settlement-cycle-icon">
          <CalendarClock size={22} />
        </div>
        <div>
          <h3 className="panel-title-sm">{t('settlements.cycleLiveTitle')}</h3>
          <p className="text-muted text-sm">
            {status.cycle_start} → {status.cycle_end_scheduled}
            {status.rollover_count > 0 && (
              <span className="badge badge-gray label-inline">
                {t('settlements.cycleRollover', { n: String(status.rollover_count) })}
              </span>
            )}
          </p>
        </div>
        <span className={`badge ${status.phase === 'pending_payment' ? 'badge-red' : status.is_profitable ? 'badge-green' : 'badge-gray'}`}>
          {phaseLabel}
        </span>
      </div>

      <div className="settlement-cycle-progress section-mt-md">
        <div className="flex-between-wrap gap-sm section-mb-xs">
          <span className="text-muted text-xs">
            {t('settlements.cycleProgress', {
              elapsed: String(status.days_elapsed),
              total: String(status.target_days),
            })}
          </span>
          <span className="text-muted text-xs">
            {status.days_remaining > 0
              ? t('settlements.cycleRemaining', { n: String(status.days_remaining) })
              : t('settlements.cycleDue')}
          </span>
        </div>
        <div className="settlement-cycle-progress-track">
          <div
            className="settlement-cycle-progress-fill"
            style={{ width: `${Math.min(100, status.progress_pct)}%` }}
          />
        </div>
      </div>

      <div className="stat-grid stat-grid-flush section-mt-md">
        <StatCard
          label={t('settlements.cycleTradePnl')}
          countUp={{ end: status.cycle_trade_pnl, pnl: true, decimals: 2, prefix: status.cycle_trade_pnl >= 0 ? '+$' : '-$' }}
          positive={pnlPositive}
        />
        <StatCard
          label={t('settlements.cycleNetProfit')}
          countUp={{ end: status.cycle_net_profit, pnl: true, decimals: 2, prefix: '+$' }}
          positive={status.cycle_net_profit > 0}
        />
        <StatCard
          label={t('settlements.cycleEstFee')}
          countUp={{ end: status.estimated_fee, prefix: '$', decimals: 2 }}
        />
        <StatCard
          label={t('dashboard.principal')}
          countUp={{ end: status.initial_principal, prefix: '$', decimals: 2 }}
        />
      </div>

      {status.has_open_position && status.phase !== 'awaiting_flat' && (
        <div className="settlement-cycle-alert section-mt-md">
          <AlertTriangle size={16} />
          <p className="text-sm">{t('settlements.cycleFlatRequired')}</p>
        </div>
      )}

      {status.phase === 'awaiting_flat' && (
        <div className="settlement-cycle-alert section-mt-md">
          <AlertTriangle size={16} />
          <p className="text-sm">{t('settlements.cycleAwaitingFlat')}</p>
        </div>
      )}

      {!status.has_open_position && status.requires_flat && status.is_profitable && !status.pending_settlement_id && (
        <div className="settlement-cycle-alert settlement-cycle-alert--info section-mt-md">
          <Sparkles size={16} />
          <p className="text-sm">{t('settlements.cycleReadyBill')}</p>
        </div>
      )}

      {!status.is_profitable && status.days_remaining === 0 && !status.has_open_position && (
        <div className="settlement-cycle-alert settlement-cycle-alert--info section-mt-md">
          <TrendingUp size={16} />
          <p className="text-sm">{t('settlements.cycleLossRollover')}</p>
        </div>
      )}

      {status.pending_settlement_id && onPayClick && (
        <div className="settlement-cycle-pay section-mt-md">
          <div>
            <p className="text-sm-strong">{t('settlements.oneClickPayTitle')}</p>
            <p className="text-muted text-sm">{t('settlements.oneClickPayHint')}</p>
          </div>
          <button type="button" className="btn btn-primary" onClick={onPayClick}>
            <Wallet size={16} />
            {t('settlements.oneClickPayCta', { amount: status.pending_payable.toFixed(2) })}
          </button>
        </div>
      )}
    </GlassCard>
  )
}
