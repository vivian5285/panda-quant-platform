import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import GlassCard from './GlassCard'
import TradeLogDetailPanel from './TradeLogDetailPanel'
import TabBar from './TabBar'
import { referralApi } from '../api'
import { useI18n, localeDate } from '../i18n'

type Props = {
  userId: number | null
  displayName?: string
  onClose: () => void
}

type TabKey = 'logs' | 'trades'

function pnlClass(v: number) {
  return v >= 0 ? 'text-green' : 'text-red'
}

export default function DownlineLogsModal({ userId, displayName, onClose }: Props) {
  const { t, locale } = useI18n()
  const [account, setAccount] = useState<any>(null)
  const [logs, setLogs] = useState<any[]>([])
  const [trades, setTrades] = useState<any[]>([])
  const [tab, setTab] = useState<TabKey>('logs')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!userId) return
    setLoading(true)
    setTab('logs')
    setExpanded(null)
    Promise.all([
      referralApi.downlineAccount(userId),
      referralApi.downlineLogs(userId, { limit: 100 }),
      referralApi.downlineTrades(userId, { limit: 100 }),
    ])
      .then(([acc, lg, tr]) => {
        setAccount(acc)
        setLogs(lg || [])
        setTrades(tr || [])
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
              <h3 className="card-heading">{t('referrals.downlineDetailTitle')}</h3>
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
                <GlassCard className="p-3 section-mb-sm downline-account-summary">
                  <div className="stat-grid stat-grid-flush section-mb-sm">
                    <div className="stat-tile">
                      <p className="text-muted text-xs">{t('referrals.balance')}</p>
                      <p className="text-md-strong">${(acc.live_equity ?? 0).toFixed(2)}</p>
                    </div>
                    <div className="stat-tile">
                      <p className="text-muted text-xs">{t('referrals.cyclePnl')}</p>
                      <p className={`text-md-strong ${pnlClass(acc.cycle_pnl ?? 0)}`}>
                        ${(acc.cycle_pnl ?? 0).toFixed(2)}
                      </p>
                    </div>
                    <div className="stat-tile">
                      <p className="text-muted text-xs">{t('referrals.unrealized')}</p>
                      <p className={`text-md-strong ${pnlClass(acc.unrealized_pnl ?? 0)}`}>
                        ${(acc.unrealized_pnl ?? 0).toFixed(2)}
                      </p>
                    </div>
                    <div className="stat-tile">
                      <p className="text-muted text-xs">{t('referrals.totalPnl')}</p>
                      <p className={`text-md-strong ${pnlClass(acc.total_pnl ?? 0)}`}>
                        ${(acc.total_pnl ?? 0).toFixed(2)}
                      </p>
                    </div>
                  </div>

                  {acc.has_open_position ? (
                    <div className="admin-live-position-banner">
                      <span className={`badge ${acc.position_side === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                        {acc.position_side}
                      </span>
                      <span>{Number(acc.position_qty || 0).toFixed(4)} ETH</span>
                      <span className="text-muted">
                        {t('referrals.positionEntry')} ${Number(acc.position_entry || 0).toFixed(2)}
                      </span>
                      {(acc.position_mark ?? 0) > 0 && (
                        <span className="text-muted">
                          {t('referrals.positionMark')} ${Number(acc.position_mark).toFixed(2)}
                        </span>
                      )}
                    </div>
                  ) : (
                    <p className="text-muted text-sm">{t('admin.accountsFlat')}</p>
                  )}

                  <div className="trades-detail-grid section-mt-sm">
                    <span>{t('api.exchangeLabel')}: {acc.exchange || '—'}</span>
                    <span>{t('referrals.principal')}: ${(acc.initial_principal ?? 0).toFixed(2)}</span>
                    <span>{t('referrals.available')}: ${(acc.available_balance ?? 0).toFixed(2)}</span>
                    <span>{t('referrals.apiStatus')}: {acc.api_status || '—'}</span>
                    <span>{t('referrals.pendingPerfFee')}: {(acc.pending_perf_fee ?? 0) > 0 ? `$${acc.pending_perf_fee.toFixed(2)}` : '—'}</span>
                    <span>{t('referrals.expectedReward')}: {(acc.expected_reward ?? 0) > 0 ? `$${acc.expected_reward.toFixed(2)}` : '—'}</span>
                    <span>{t('referrals.settlementStatus')}: {acc.settlement_status || 'none'}{acc.settlement_period ? ` (${acc.settlement_period})` : ''}</span>
                    <span>{t('referrals.openTrades')}: {account.open_trades ?? 0}</span>
                    <span>{t('referrals.closedTrades')}: {account.closed_trades ?? 0}</span>
                  </div>
                </GlassCard>
              )}

              <div className="section-mb-sm">
                <TabBar
                  tabs={[
                    { key: 'logs', label: t('referrals.downlineTabLogs') },
                    { key: 'trades', label: t('referrals.downlineTabTrades') },
                  ]}
                  active={tab}
                  onChange={k => setTab(k as TabKey)}
                />
              </div>

              {tab === 'logs' && (
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
              )}

              {tab === 'trades' && (
                <div className="table-wrap downline-logs-list">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>{t('common.time')}</th>
                        <th>{t('trades.side')}</th>
                        <th>{t('trades.qty')}</th>
                        <th>{t('trades.entry')}</th>
                        <th>{t('trades.exit')}</th>
                        <th>{t('trades.pnl')}</th>
                        <th>{t('common.status')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map(tr => (
                        <tr key={tr.id}>
                          <td>{localeDate(tr.closed_at || tr.created_at, locale)}</td>
                          <td>{tr.side}</td>
                          <td>{tr.quantity}</td>
                          <td>{tr.entry_price}</td>
                          <td>{tr.exit_price ?? '—'}</td>
                          <td className={pnlClass(tr.realized_pnl ?? 0)}>
                            {tr.realized_pnl != null ? tr.realized_pnl.toFixed(2) : '—'}
                          </td>
                          <td>{tr.status}</td>
                        </tr>
                      ))}
                      {!trades.length && (
                        <tr><td colSpan={7} className="text-muted">{t('common.noData')}</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </GlassCard>
      </div>
    </div>
  )
}
