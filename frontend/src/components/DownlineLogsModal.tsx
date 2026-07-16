import { useEffect, useMemo, useState } from 'react'
import { X } from 'lucide-react'
import GlassCard from './GlassCard'
import TradeLogDetailPanel from './TradeLogDetailPanel'
import TabBar from './TabBar'
import { referralApi } from '../api'
import { useI18n, localeDate } from '../i18n'
import { qtyUnitForSymbol, shortSymbol } from '../utils/symbolDisplay'
import SymbolPnlStrip from './SymbolPnlStrip'

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
      referralApi.downlineLogs(userId, { limit: 100, sync_exchange: true }),
      referralApi.downlineTrades(userId, { limit: 100 }),
    ])
      .then(([acc, lg, tr]) => {
        setAccount(acc)
        setLogs(lg || [])
        setTrades(tr || [])
      })
      .finally(() => setLoading(false))
  }, [userId])

  const symbolPnlRows = useMemo(() => {
    const map: Record<string, { pnl: number; trades: number; wins: number }> = {}
    for (const tr of trades) {
      if (tr.realized_pnl == null) continue
      const s = shortSymbol(tr.symbol)
      if (!map[s]) map[s] = { pnl: 0, trades: 0, wins: 0 }
      const p = Number(tr.realized_pnl || 0)
      map[s].pnl += p
      map[s].trades += 1
      if (p > 0) map[s].wins += 1
    }
    return Object.entries(map).map(([symbol, v]) => ({
      symbol,
      pnl: v.pnl,
      trades: v.trades,
      win_rate: v.trades ? Math.round((v.wins / v.trades) * 1000) / 10 : 0,
    }))
  }, [trades])

  if (!userId) return null

  const acc = account?.account
  const positions: any[] = acc?.all_positions?.length
    ? acc.all_positions
    : (acc?.has_open_position
      ? [{
          symbol: acc.position_symbol,
          side: acc.position_side,
          qty: acc.position_qty,
          entry_price: acc.position_entry,
          mark_price: acc.position_mark,
          unrealized_pnl: acc.unrealized_pnl,
        }]
      : [])

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

                  {positions.length > 0 ? (
                    positions.map((pos, idx) => {
                      const sym = shortSymbol(pos.symbol)
                      return (
                        <div key={`${sym}-${idx}`} className="admin-live-position-banner section-mb-sm">
                          <span className="badge badge-gray">{sym}</span>
                          <span className={`badge ${pos.side === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                            {pos.side}
                          </span>
                          <span>
                            {Number(pos.qty || 0).toFixed(4)} {qtyUnitForSymbol(sym)}
                          </span>
                          <span className="text-muted">
                            {t('referrals.positionEntry')} ${Number(pos.entry_price || 0).toFixed(2)}
                          </span>
                          {(pos.mark_price ?? 0) > 0 && (
                            <span className="text-muted">
                              {t('referrals.positionMark')} ${Number(pos.mark_price).toFixed(2)}
                            </span>
                          )}
                        </div>
                      )
                    })
                  ) : (
                    <p className="text-muted text-sm">{t('admin.accountsFlat')}</p>
                  )}

                  <div className="trades-detail-grid section-mt-sm">
                    <span>{t('api.exchangeLabel')}: {acc.exchange || '—'}</span>
                    <span>{t('referrals.principal')}: ${(acc.initial_principal ?? 0).toFixed(2)}</span>
                    <span>{t('referrals.available')}: ${(acc.available_balance ?? 0).toFixed(2)}</span>
                    <span>{t('referrals.apiStatus')}: {acc.api_status || '—'}</span>
                    <span>
                      {t('referrals.tradingSince')}:{' '}
                      {acc.trading_since ? String(acc.trading_since).slice(0, 10) : '—'}
                    </span>
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

              {symbolPnlRows.length > 0 && (
                <GlassCard className="p-3 section-mb-sm">
                  <SymbolPnlStrip
                    title={t('analytics.pnlBySymbol')}
                    hint={t('dashboard.dualSymbolHint')}
                    rows={symbolPnlRows}
                  />
                </GlassCard>
              )}

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
                        <th>{t('trades.symbol')}</th>
                        <th>{t('trades.side')}</th>
                        <th>{t('trades.qty')}</th>
                        <th>{t('trades.entry')}</th>
                        <th>{t('trades.exit')}</th>
                        <th>{t('trades.pnl')}</th>
                        <th>{t('common.status')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map(tr => {
                        const sym = shortSymbol(tr.symbol)
                        return (
                          <tr key={tr.id}>
                            <td>{localeDate(tr.closed_at || tr.created_at, locale)}</td>
                            <td><span className="badge badge-gray">{sym}</span></td>
                            <td>{tr.side}</td>
                            <td>{tr.quantity} <span className="text-muted text-xs">{qtyUnitForSymbol(sym)}</span></td>
                            <td>{tr.entry_price}</td>
                            <td>{tr.exit_price ?? '—'}</td>
                            <td className={pnlClass(tr.realized_pnl ?? 0)}>
                              {tr.realized_pnl != null ? tr.realized_pnl.toFixed(2) : '—'}
                            </td>
                            <td>{tr.status}</td>
                          </tr>
                        )
                      })}
                      {!trades.length && (
                        <tr><td colSpan={8} className="text-muted">{t('common.noData')}</td></tr>
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
