import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw, ChevronDown, ChevronUp, AlertTriangle, Activity, PauseCircle } from 'lucide-react'
import GlassCard from '../../../components/GlassCard'
import StatCard from '../../../components/StatCard'
import TradeLogDetailPanel from '../../../components/TradeLogDetailPanel'
import { adminApi } from '../../../api'
import type { LogQueryParams, TradeQueryParams } from '../../../api'
import { useI18n, localeDate } from '../../../i18n'
import { toast } from '../../../store/toast'

type ManagedAccount = {
  user_id: number
  uid?: string
  email?: string
  exchange?: string
  balance?: number
  unrealized_pnl?: number
  cycle_pnl?: number
  cumulative_trade_pnl?: number
  has_position?: boolean
  position_side?: string
  position_qty?: number
  position_entry?: number
  position_mark?: number
  position_unrealized?: number
  trade_count?: number
  closed_trade_count?: number
  supervisor_active?: boolean
  trading_paused?: boolean
  snapshot_error?: string | null
}

type TradeStats = {
  trade_count: number
  win_count: number
  loss_count: number
  win_rate: number
  realized_pnl: number
  funding_fee: number
  avg_pnl: number
}

function fmtDate(d: Date) {
  return d.toISOString().slice(0, 10)
}

function resolveRange(filter: string, from: string, to: string): TradeQueryParams {
  if (filter === 'custom') {
    if (!from) return { limit: 300 }
    return { start: from, end: to || from, limit: 300 }
  }
  const days = filter === '7d' ? 7 : filter === '30d' ? 30 : filter === '90d' ? 90 : 0
  if (days === 0) return { limit: 300 }
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - days)
  return { start: fmtDate(start), end: fmtDate(end), limit: 300 }
}

function pnlClass(v: number) {
  return v >= 0 ? 'text-green' : 'text-red'
}

export default function AdminAccountsTab() {
  const t = useI18n(s => s.t)
  const locale = useI18n(s => s.locale)
  const [loading, setLoading] = useState(true)
  const [accounts, setAccounts] = useState<ManagedAccount[]>([])
  const [summary, setSummary] = useState<any>(null)
  const [positionFilter, setPositionFilter] = useState<'all' | 'open' | 'flat'>('all')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [timeFilter, setTimeFilter] = useState('30d')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [detailTrades, setDetailTrades] = useState<any[]>([])
  const [detailLogs, setDetailLogs] = useState<any[]>([])
  const [detailStats, setDetailStats] = useState<TradeStats | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [confirmAll, setConfirmAll] = useState(false)
  const [onlyWithPosition, setOnlyWithPosition] = useState(false)
  const [closing, setClosing] = useState(false)

  const queryParams = useMemo(
    () => resolveRange(timeFilter, dateFrom, dateTo),
    [timeFilter, dateFrom, dateTo],
  )

  const loadAccounts = useCallback(async () => {
    setLoading(true)
    try {
      const hasPosition = positionFilter === 'open' ? true : positionFilter === 'flat' ? false : undefined
      const res = await adminApi.managedAccounts(hasPosition !== undefined ? { has_position: hasPosition } : undefined)
      setAccounts(res.accounts || [])
      setSummary(res.summary || null)
    } catch {
      toast.error(t('admin.accountsLoadFail'))
    } finally {
      setLoading(false)
    }
  }, [positionFilter, t])

  const loadDetail = useCallback(async (userId: number) => {
    setDetailLoading(true)
    try {
      const [trades, logs, stats] = await Promise.all([
        adminApi.userTrades(userId, queryParams),
        adminApi.userLogs(userId, queryParams as LogQueryParams),
        adminApi.userTradeStats(userId, { start: queryParams.start, end: queryParams.end }),
      ])
      setDetailTrades(trades || [])
      setDetailLogs(logs || [])
      setDetailStats(stats)
    } catch {
      toast.error(t('admin.accountsDetailFail'))
    } finally {
      setDetailLoading(false)
    }
  }, [queryParams, t])

  useEffect(() => { loadAccounts() }, [loadAccounts])

  useEffect(() => {
    if (expandedId) loadDetail(expandedId)
  }, [expandedId, loadDetail])

  const toggleExpand = (id: number) => {
    setExpandedId(prev => (prev === id ? null : id))
  }

  const forceCloseOne = async (userId: number) => {
    if (!window.confirm(t('admin.forceCloseConfirm'))) return
    try {
      await adminApi.forceCloseUser(userId)
      toast.success(t('admin.forceCloseDone'))
      loadAccounts()
      if (expandedId === userId) loadDetail(userId)
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('admin.accountsCloseFail'))
    }
  }

  const forceCloseAll = async () => {
    setClosing(true)
    try {
      const res = await adminApi.forceCloseAll({ only_with_position: onlyWithPosition })
      toast.success(t('admin.forceCloseAllDone', { n: res.initiated ?? 0 }))
      setConfirmAll(false)
      loadAccounts()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('admin.accountsCloseFail'))
    } finally {
      setClosing(false)
    }
  }

  const snapshotErrors = summary?.snapshot_errors ?? 0

  return (
    <div>
      <div className="table-toolbar table-toolbar-between section-mb-sm">
        <div>
          <h2 className="text-md-strong">{t('admin.tabAccounts')}</h2>
          <p className="text-muted text-sm">{t('admin.accountsSubtitle')}</p>
        </div>
        <div className="flex-gap-sm">
          <button type="button" className="btn btn-ghost btn-sm" disabled={loading} onClick={loadAccounts}>
            <RefreshCw size={14} />
            {loading ? t('common.loading') : t('admin.accountsRefresh')}
          </button>
          <button type="button" className="btn btn-danger btn-sm" onClick={() => setConfirmAll(true)}>
            {t('admin.forceCloseAll')}
          </button>
        </div>
      </div>

      {snapshotErrors > 0 && (
        <GlassCard className="p-3 section-mb-sm admin-snapshot-warn">
          <div className="flex-gap-sm">
            <AlertTriangle size={16} className="text-amber" />
            <p className="text-sm text-muted">{t('admin.accountsSnapshotErrorHint', { n: snapshotErrors })}</p>
          </div>
        </GlassCard>
      )}

      {summary && (
        <div className="stat-grid section-mb-sm">
          <StatCard label={t('admin.accountsTotal')} value={String(summary.account_count ?? 0)} />
          <StatCard label={t('admin.accountsWithPosition')} value={String(summary.with_position ?? 0)} />
          <StatCard label={t('admin.accountsTotalBalance')} value={`$${(summary.total_balance ?? 0).toFixed(2)}`} />
          <StatCard label={t('admin.accountsTotalUnrealized')} value={`$${(summary.total_unrealized ?? 0).toFixed(2)}`} />
          <StatCard label={t('admin.cols.cumulativePnl')} value={`$${(summary.total_cumulative_pnl ?? 0).toFixed(2)}`} />
          {snapshotErrors > 0 && (
            <StatCard label={t('admin.accountsSnapshotErrors')} value={String(snapshotErrors)} />
          )}
        </div>
      )}

      <GlassCard className="p-4 section-mb-sm">
        <div className="flex-gap-sm trades-filter-wrap">
          <label className="trades-filter">
            <span className="text-muted">{t('admin.accountsPositionFilter')}</span>
            <select className="input input-sm" value={positionFilter} onChange={e => setPositionFilter(e.target.value as typeof positionFilter)}>
              <option value="all">{t('admin.accountsFilterAll')}</option>
              <option value="open">{t('admin.accountsFilterOpen')}</option>
              <option value="flat">{t('admin.accountsFilterFlat')}</option>
            </select>
          </label>
        </div>
      </GlassCard>

      <GlassCard className="p-0 table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th />
              <th>{t('common.uid')}</th>
              <th>{t('api.exchangeLabel')}</th>
              <th>{t('dashboard.balance')}</th>
              <th>{t('dashboard.floatingPnl')}</th>
              <th>{t('dashboard.cyclePnl')}</th>
              <th>{t('admin.cols.cumulativePnl')}</th>
              <th>{t('dashboard.currentPosition')}</th>
              <th>{t('admin.tradeCount')}</th>
              <th>{t('common.status')}</th>
              <th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map(row => (
              <Fragment key={row.user_id}>
                <tr className={row.has_position ? 'row-highlight' : row.snapshot_error ? 'row-warn' : undefined}>
                  <td>
                    <button type="button" className="btn btn-ghost btn-xs" onClick={() => toggleExpand(row.user_id)}>
                      {expandedId === row.user_id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                  </td>
                  <td>
                    <div className="admin-account-uid">{row.uid}</div>
                    {row.email && <div className="text-muted text-xs">{row.email}</div>}
                  </td>
                  <td><span className="badge badge-gray">{row.exchange}</span></td>
                  <td>${(row.balance ?? 0).toFixed(2)}</td>
                  <td className={pnlClass(row.unrealized_pnl ?? 0)}>
                    ${(row.unrealized_pnl ?? 0).toFixed(2)}
                  </td>
                  <td className={pnlClass(row.cycle_pnl ?? 0)}>
                    ${(row.cycle_pnl ?? 0).toFixed(2)}
                  </td>
                  <td className={pnlClass(row.cumulative_trade_pnl ?? 0)}>
                    ${(row.cumulative_trade_pnl ?? 0).toFixed(2)}
                  </td>
                  <td>
                    {row.has_position ? (
                      <div className="admin-position-cell">
                        <span className={`badge ${row.position_side === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                          {row.position_side}
                        </span>
                        <span className="text-sm">{Number(row.position_qty ?? 0).toFixed(4)}</span>
                        <span className="text-muted text-xs">
                          @ ${Number(row.position_entry ?? 0).toFixed(2)}
                          {(row.position_mark ?? 0) > 0 && (
                            <> · {t('admin.accountsMarkPrice')} ${Number(row.position_mark).toFixed(2)}</>
                          )}
                        </span>
                      </div>
                    ) : (
                      <span className="text-muted">{t('admin.accountsFlat')}</span>
                    )}
                  </td>
                  <td>{row.closed_trade_count ?? 0}/{row.trade_count ?? 0}</td>
                  <td>
                    <div className="admin-status-badges">
                      {row.supervisor_active ? (
                        <span className="badge badge-green badge-spaced">
                          <Activity size={10} /> {t('admin.accountsSupervisorActive')}
                        </span>
                      ) : (
                        <span className="badge badge-gray badge-spaced">{t('admin.accountsSupervisorOff')}</span>
                      )}
                      {row.trading_paused && (
                        <span className="badge badge-amber badge-spaced">
                          <PauseCircle size={10} /> {t('admin.accountsTradingPaused')}
                        </span>
                      )}
                      {row.snapshot_error && (
                        <span className="badge badge-amber badge-spaced" title={row.snapshot_error}>
                          {t('admin.accountsSnapshotRowError')}
                        </span>
                      )}
                    </div>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-danger btn-xs"
                      disabled={!row.has_position}
                      onClick={() => forceCloseOne(row.user_id)}
                    >
                      {t('admin.forceClose')}
                    </button>
                  </td>
                </tr>
                {expandedId === row.user_id && (
                  <tr>
                    <td colSpan={11} className="admin-account-detail-cell">
                      <GlassCard className="p-4 section-mt-sm">
                        {row.has_position && (
                          <div className="admin-live-position-banner section-mb-sm">
                            <span className={`badge ${row.position_side === 'LONG' ? 'badge-green' : 'badge-red'}`}>
                              {row.position_side}
                            </span>
                            <span>{Number(row.position_qty ?? 0).toFixed(4)} ETH</span>
                            <span className="text-muted">
                              {t('referrals.positionEntry')} ${Number(row.position_entry ?? 0).toFixed(2)}
                            </span>
                            {(row.position_mark ?? 0) > 0 && (
                              <span className="text-muted">
                                {t('referrals.positionMark')} ${Number(row.position_mark).toFixed(2)}
                              </span>
                            )}
                            <span className={pnlClass(row.position_unrealized ?? row.unrealized_pnl ?? 0)}>
                              {t('dashboard.floatingPnl')} ${Number(row.position_unrealized ?? row.unrealized_pnl ?? 0).toFixed(2)}
                            </span>
                          </div>
                        )}

                        <div className="flex-gap-sm trades-filter-wrap section-mb-sm">
                          <label className="trades-filter">
                            <span className="text-muted">{t('trades.filterTime')}</span>
                            <select className="input input-sm" value={timeFilter} onChange={e => setTimeFilter(e.target.value)}>
                              <option value="7d">{t('trades.filterTime7d')}</option>
                              <option value="30d">{t('trades.filterTime30d')}</option>
                              <option value="90d">{t('trades.filterTime90d')}</option>
                              <option value="all">{t('trades.filterAll')}</option>
                              <option value="custom">{t('trades.filterTimeCustom')}</option>
                            </select>
                          </label>
                          {timeFilter === 'custom' && (
                            <>
                              <label className="trades-filter">
                                <span className="text-muted">{t('trades.dateFrom')}</span>
                                <input type="date" className="input input-sm" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
                              </label>
                              <label className="trades-filter">
                                <span className="text-muted">{t('trades.dateTo')}</span>
                                <input type="date" className="input input-sm" value={dateTo} onChange={e => setDateTo(e.target.value)} />
                              </label>
                            </>
                          )}
                        </div>

                        {detailLoading ? (
                          <p className="text-muted">{t('common.loading')}</p>
                        ) : (
                          <>
                            {detailStats && (
                              <div className="stat-grid section-mb-sm">
                                <StatCard label={t('admin.accountsPeriodTrades')} value={String(detailStats.trade_count)} />
                                <StatCard label={t('admin.accountsWinRate')} value={`${detailStats.win_rate}%`} />
                                <StatCard label={t('admin.accountsPeriodPnl')} value={`$${detailStats.realized_pnl.toFixed(2)}`} />
                                <StatCard label={t('admin.accountsAvgPnl')} value={`$${detailStats.avg_pnl.toFixed(2)}`} />
                              </div>
                            )}

                            <h4 className="text-sm-strong section-mb-sm">{t('admin.userTrades')}</h4>
                            <div className="table-wrap section-mb-md">
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
                                  {detailTrades.map(tr => (
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
                                  {!detailTrades.length && (
                                    <tr><td colSpan={7} className="text-muted">{t('common.noData')}</td></tr>
                                  )}
                                </tbody>
                              </table>
                            </div>

                            <h4 className="text-sm-strong section-mb-sm">{t('admin.userLogs')}</h4>
                            <div className="log-list-stack">
                              {detailLogs.map(log => (
                                <GlassCard key={log.id} className="p-4 trade-log-card">
                                  <div className="trade-log-card-head-static">
                                    <span className="badge badge-gray badge-spaced">{log.event_type}</span>
                                    <span className="text-sm">{log.message}</span>
                                    <p className="text-muted text-xs mt-xs">{localeDate(log.created_at, locale)}</p>
                                  </div>
                                  <TradeLogDetailPanel log={log} compact />
                                </GlassCard>
                              ))}
                              {!detailLogs.length && <p className="text-muted">{t('common.noData')}</p>}
                            </div>
                          </>
                        )}
                      </GlassCard>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {!loading && !accounts.length && (
              <tr><td colSpan={11} className="text-muted p-4">{t('common.noData')}</td></tr>
            )}
          </tbody>
        </table>
      </GlassCard>

      {confirmAll && (
        <div className="confirm-modal-overlay" role="dialog">
          <GlassCard className="p-6 modal-card">
            <div className="flex-gap-sm section-mb-sm">
              <AlertTriangle className="text-red" size={20} />
              <h3 className="text-md-strong">{t('admin.forceCloseAll')}</h3>
            </div>
            <p className="text-muted section-mb-sm">{t('admin.forceCloseAllConfirm')}</p>
            <label className="form-field section-mb-sm">
              <input type="checkbox" checked={onlyWithPosition} onChange={e => setOnlyWithPosition(e.target.checked)} />
              <span className="ml-sm">{t('admin.forceCloseAllOnlyOpen')}</span>
            </label>
            <div className="flex-gap-sm">
              <button type="button" className="btn btn-ghost" onClick={() => setConfirmAll(false)}>{t('common.cancel')}</button>
              <button type="button" className="btn btn-danger" disabled={closing} onClick={forceCloseAll}>
                {closing ? t('common.loading') : t('admin.forceCloseAll')}
              </button>
            </div>
          </GlassCard>
        </div>
      )}
    </div>
  )
}
