import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import GlassCard from './GlassCard'
import TradeLogDetailPanel from './TradeLogDetailPanel'
import { referralApi } from '../api'
import { useI18n, localeDate } from '../i18n'

type Props = {
  userId: number | null
  displayName?: string
  onClose: () => void
}

export default function DownlineLogsModal({ userId, displayName, onClose }: Props) {
  const { t, locale } = useI18n()
  const [account, setAccount] = useState<any>(null)
  const [logs, setLogs] = useState<any[]>([])
  const [expanded, setExpanded] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!userId) return
    setLoading(true)
    Promise.all([
      referralApi.downlineAccount(userId),
      referralApi.downlineLogs(userId, { limit: 100 }),
    ])
      .then(([acc, lg]) => {
        setAccount(acc)
        setLogs(lg || [])
      })
      .finally(() => setLoading(false))
  }, [userId])

  if (!userId) return null

  const acc = account?.account

  return (
    <div className="confirm-modal-overlay" onClick={onClose} role="presentation">
      <div className="downline-logs-modal-wrap" onClick={e => e.stopPropagation()}>
        <GlassCard className="downline-logs-modal p-4">
          <div className="downline-logs-modal-head">
            <div>
              <h3 className="card-heading">{t('referrals.downlineLogsTitle')}</h3>
              <p className="text-muted text-sm">
                {displayName || acc?.display_name || acc?.email} · {acc?.uid}
                {account?.level != null && ` · L${account.level}`}
              </p>
            </div>
            <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} aria-label={t('referrals.closePreview')}>
              <X size={18} />
            </button>
          </div>

          {loading ? (
            <p className="text-muted text-sm">{t('common.loading')}</p>
          ) : (
            <>
              {acc && (
                <div className="trades-detail-grid section-mb-sm">
                  <span>{t('api.exchangeLabel')}: {acc.exchange || '—'}</span>
                  <span>{t('referrals.principal')}: ${(acc.initial_principal ?? 0).toFixed(2)}</span>
                  <span>{t('referrals.balance')}: ${(acc.live_equity ?? 0).toFixed(2)}</span>
                  <span>{t('referrals.available')}: ${(acc.available_balance ?? 0).toFixed(2)}</span>
                  <span>{t('referrals.cyclePnl')}: ${(acc.cycle_pnl ?? 0).toFixed(2)}</span>
                  <span>{t('referrals.totalPnl')}: ${(acc.total_pnl ?? 0).toFixed(2)}</span>
                  <span>{t('referrals.unrealized')}: ${(acc.unrealized_pnl ?? 0).toFixed(2)}</span>
                  <span>{t('referrals.position')}: {acc.has_open_position ? `${acc.position_side || ''} ${Number(acc.position_qty || 0).toFixed(4)}` : '—'}</span>
                  <span>{t('referrals.apiStatus')}: {acc.api_status || '—'}</span>
                  <span>{t('referrals.pendingPerfFee')}: {(acc.pending_perf_fee ?? 0) > 0 ? `$${acc.pending_perf_fee.toFixed(2)}` : '—'}</span>
                  <span>{t('referrals.expectedReward')}: {(acc.expected_reward ?? 0) > 0 ? `$${acc.expected_reward.toFixed(2)}` : '—'}</span>
                  <span>{t('referrals.settlementStatus')}: {acc.settlement_status || 'none'}{acc.settlement_period ? ` (${acc.settlement_period})` : ''}</span>
                  <span>{t('referrals.openTrades')}: {account.open_trades ?? 0}</span>
                  <span>{t('referrals.closedTrades')}: {account.closed_trades ?? 0}</span>
                </div>
              )}

              <div className="log-list-stack downline-logs-list">
                {logs.length === 0 ? (
                  <p className="text-muted text-sm">{t('trades.logsEmpty')}</p>
                ) : logs.map(log => {
                  const open = expanded === log.id
                  return (
                    <GlassCard key={log.id} className="p-3 trade-log-card">
                      <button
                        type="button"
                        className="trade-log-card-head"
                        onClick={() => setExpanded(open ? null : log.id)}
                      >
                        <span className="badge badge-gray">{log.event_type}</span>
                        <span className="text-sm flex-1 text-left">{log.message}</span>
                        <span className="text-muted text-xs">{localeDate(log.created_at, locale)}</span>
                      </button>
                      {open && <TradeLogDetailPanel log={log} compact />}
                    </GlassCard>
                  )
                })}
              </div>
            </>
          )}
        </GlassCard>
      </div>
    </div>
  )
}
