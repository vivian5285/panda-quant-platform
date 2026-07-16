import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChevronDown, ChevronUp, Download, RefreshCw } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import RippleButton from '../components/ui/RippleButton'
import TabBar from '../components/TabBar'
import TradeLogDetailPanel, { resolveDetail } from '../components/TradeLogDetailPanel'
import { userApi, type LogQueryParams, type TradeQueryParams } from '../api'
import { useI18n, localeDate } from '../i18n'
import { downloadCsv } from '../utils/exportCsv'
import { toast } from '../store/toast'
import { isExchangeFillEvent, qtyUnitForSymbol, shortSymbol } from '../utils/symbolDisplay'
import SymbolPnlStrip from '../components/SymbolPnlStrip'

type TradeRow = {
  id: number
  symbol: string
  side?: string
  action?: string
  quantity: number
  entry_price: number
  exit_price?: number
  realized_pnl?: number
  regime: number
  status: string
  display_status?: string
  created_at: string
  closed_at?: string
  slippage?: number | null
  funding_fee?: number | null
}

type LogRow = {
  id: number
  event_type?: string
  message?: string
  detail_json?: string
  detail?: Record<string, unknown>
  trade_id?: number
  created_at: string
}

const TIME_RANGES = ['since', 'all', '7d', '30d', '90d', 'custom'] as const
type TimeRange = (typeof TIME_RANGES)[number]

function parseDetail(raw?: string): Record<string, unknown> {
  if (!raw) return {}
  try { return JSON.parse(raw) } catch { return {} }
}

function resolveRange(
  timeFilter: TimeRange,
  dateFrom: string,
  dateTo: string,
  tradingSince?: string | null,
): TradeQueryParams {
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  const today = new Date()
  if (timeFilter === 'custom') {
    if (!dateFrom) return { limit: 300 }
    return { start: dateFrom, end: dateTo || dateFrom, limit: 300 }
  }
  if (timeFilter === 'since') {
    const start = tradingSince ? String(tradingSince).slice(0, 10) : undefined
    return start ? { start, end: fmt(today), limit: 500 } : { limit: 500 }
  }
  if (timeFilter === 'all') return { limit: 500 }
  const days = timeFilter === '7d' ? 7 : timeFilter === '30d' ? 30 : 90
  const start = new Date(today)
  start.setDate(start.getDate() - days)
  return { start: fmt(start), end: fmt(today), limit: 300 }
}

function tradeStatus(tr: TradeRow, logs: LogRow[]) {
  if (tr.display_status) return tr.display_status
  if (tr.status === 'open') return 'open'
  const related = logs.filter(l => l.trade_id === tr.id)
  const fatalError = related.some(l => {
    if (l.event_type !== 'ERROR') return false
    const msg = l.message || ''
    return !msg.includes('档位纠偏中止') && !msg.includes('档位额度超标但减仓失败')
  })
  if (fatalError) return 'error'
  if (related.some(l => l.event_type === 'ADJUST' || l.message?.includes('风控'))) return 'risk'
  if (tr.status === 'open') return 'open'
  return 'closed'
}

export default function Trades() {
  const { t, locale } = useI18n()
  const [searchParams] = useSearchParams()
  const initialTab = searchParams.get('tab') === 'logs' ? 'logs' : 'executions'
  const [view, setView] = useState<'executions' | 'logs'>(initialTab)
  const [trades, setTrades] = useState<TradeRow[]>([])
  const [logs, setLogs] = useState<LogRow[]>([])
  const [tradingSince, setTradingSince] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('all')
  const [timeFilter, setTimeFilter] = useState<TimeRange>('since')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [regimeFilter, setRegimeFilter] = useState('all')
  const [symbolFilter, setSymbolFilter] = useState('all')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [expandedLog, setExpandedLog] = useState<number | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 30

  useEffect(() => {
    if (searchParams.get('tab') === 'logs') setView('logs')
  }, [searchParams])

  useEffect(() => {
    userApi.dashboard().then((d: any) => {
      const since = d?.initial_principal_at || d?.trading_since || null
      if (since) setTradingSince(String(since))
    }).catch(() => {})
  }, [])

  const queryParams = useMemo(
    () => ({
      ...resolveRange(timeFilter, dateFrom, dateTo, tradingSince),
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [timeFilter, dateFrom, dateTo, page, tradingSince],
  )

  const load = useCallback((syncExchange = false) => {
    const logParams: LogQueryParams = { ...queryParams, sync_exchange: syncExchange }
    return Promise.all([
      userApi.trades(queryParams).then(setTrades),
      userApi.logs(logParams).then(setLogs),
    ])
  }, [queryParams])

  useEffect(() => {
    setPage(0)
  }, [timeFilter, dateFrom, dateTo, statusFilter, regimeFilter, symbolFilter])

  useEffect(() => {
    load()
    const timer = setInterval(() => load(), 60000)
    return () => clearInterval(timer)
  }, [load])

  const syncBinance = async () => {
    setSyncing(true)
    try {
      const res = await userApi.syncExchangeLogs(90)
      if (res?.error) {
        toast.error(t('trades.syncFail'))
      } else {
        toast.success(t('trades.syncOk', { n: res?.synced ?? 0 }))
        await load(true)
      }
    } catch {
      toast.error(t('trades.syncFail'))
    } finally {
      setSyncing(false)
    }
  }

  const logByTrade = useMemo(() => {
    const map = new Map<number, LogRow[]>()
    logs.forEach(l => {
      if (!l.trade_id) return
      const arr = map.get(l.trade_id) || []
      arr.push(l)
      map.set(l.trade_id, arr)
    })
    return map
  }, [logs])

  const regimes = useMemo(() => {
    const set = new Set(trades.map(tr => tr.regime).filter(r => r != null))
    return Array.from(set).sort((a, b) => a - b)
  }, [trades])

  const symbols = useMemo(() => {
    const set = new Set(trades.map(tr => shortSymbol(tr.symbol)))
    return Array.from(set).sort()
  }, [trades])

  const rows = useMemo(() => {
    return trades.filter(tr => {
      if (statusFilter !== 'all' && tradeStatus(tr, logs) !== statusFilter) return false
      if (regimeFilter !== 'all' && String(tr.regime) !== regimeFilter) return false
      if (symbolFilter !== 'all' && shortSymbol(tr.symbol) !== symbolFilter) return false
      return true
    })
  }, [trades, logs, statusFilter, regimeFilter, symbolFilter])

  const platformLogs = useMemo(
    () => logs.filter(l => !isExchangeFillEvent(l.event_type)),
    [logs],
  )
  const exchangeLogs = useMemo(
    () => logs.filter(l => isExchangeFillEvent(l.event_type)),
    [logs],
  )
  const displayLogs = view === 'logs' ? logs : platformLogs

  const periodStats = useMemo(() => {
    const closed = rows.filter(tr => tr.status === 'closed' || (tr.realized_pnl != null && tr.exit_price != null))
    const pnl = closed.reduce((s, tr) => s + Number(tr.realized_pnl || 0), 0)
    const bySym: Record<string, { pnl: number; trades: number; wins: number }> = {}
    closed.forEach(tr => {
      const s = shortSymbol(tr.symbol)
      if (!bySym[s]) bySym[s] = { pnl: 0, trades: 0, wins: 0 }
      const p = Number(tr.realized_pnl || 0)
      bySym[s].pnl += p
      bySym[s].trades += 1
      if (p > 0) bySym[s].wins += 1
    })
    const symbolRows = Object.entries(bySym).map(([symbol, v]) => ({
      symbol,
      pnl: v.pnl,
      trades: v.trades,
      win_rate: v.trades ? Math.round((v.wins / v.trades) * 1000) / 10 : 0,
    }))
    return {
      count: rows.length,
      closed: closed.length,
      pnl,
      bySym: Object.fromEntries(Object.entries(bySym).map(([k, v]) => [k, v.pnl])),
      symbolRows,
    }
  }, [rows])

  const getSlippage = (tr: TradeRow) => {
    if (typeof tr.slippage === 'number') return tr.slippage
    const openLog = (logByTrade.get(tr.id) || []).find(l => l.event_type === 'OPEN')
    const detail = parseDetail(openLog?.detail_json)
    return typeof detail.slippage === 'number' ? detail.slippage : null
  }

  const getFunding = (tr: TradeRow) => {
    if (typeof tr.funding_fee === 'number') return tr.funding_fee
    return null
  }

  const getFilled = (tr: TradeRow) => {
    const openLog = (logByTrade.get(tr.id) || []).find(l => l.event_type === 'OPEN')
    const detail = parseDetail(openLog?.detail_json)
    return typeof detail.qty === 'number' ? detail.qty : tr.quantity
  }

  const statusLabel = (key: string) => {
    const map: Record<string, string> = {
      open: t('trades.statusOpen'),
      closed: t('trades.statusClosed'),
      error: t('trades.statusError'),
      risk: t('trades.statusRisk'),
    }
    return map[key] || key
  }

  const statusBadge = (key: string) => {
    if (key === 'error' || key === 'risk') return 'badge-red'
    if (key === 'open') return 'badge-green'
    return 'badge-gray'
  }

  const exportRows = () => {
    downloadCsv('executions', rows.map(tr => {
      const st = tradeStatus(tr, logs)
      const slip = getSlippage(tr)
      const funding = getFunding(tr)
      return {
        time: localeDate(tr.created_at, locale),
        symbol: shortSymbol(tr.symbol),
        signal: tr.action || tr.side,
        side: tr.side,
        requested: tr.quantity,
        filled: getFilled(tr),
        unit: qtyUnitForSymbol(tr.symbol),
        slippage: slip ?? '',
        funding: funding ?? '',
        entry: tr.entry_price,
        exit: tr.exit_price ?? '',
        pnl: tr.realized_pnl ?? '',
        status: statusLabel(st),
      }
    }))
  }

  const exportLogs = () => {
    downloadCsv('execution-logs', displayLogs.map(l => {
      const d = parseDetail(l.detail_json)
      return {
        time: localeDate(l.created_at, locale),
        type: l.event_type,
        message: l.message,
        symbol: shortSymbol(String(d.symbol || d.canonical_symbol || '')),
        side: d.side ?? '',
        qty: d.qty ?? '',
        price: d.price ?? '',
        pnl: d.realized_pnl ?? '',
      }
    }))
  }

  return (
    <Layout>
      <PageHeader title={t('trades.title')} subtitle={t('trades.subtitle')} />

      <TabBar
        tabs={[
          { key: 'executions', label: t('trades.tabExecutions') },
          { key: 'logs', label: t('trades.tabLogs') },
        ]}
        active={view}
        onChange={k => setView(k as 'executions' | 'logs')}
      />

      <div className="trades-toolbar">
        <div className="trades-filters">
          <label className="trades-filter">
            <span className="text-muted">{t('trades.filterTime')}</span>
            <select value={timeFilter} onChange={e => setTimeFilter(e.target.value as TimeRange)}>
              <option value="since">{t('trades.filterSinceActivation')}</option>
              <option value="all">{t('trades.filterAll')}</option>
              <option value="7d">{t('trades.filterTime7d')}</option>
              <option value="30d">{t('trades.filterTime30d')}</option>
              <option value="90d">{t('trades.filterTime90d')}</option>
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
          {view === 'executions' && (
            <>
              <label className="trades-filter">
                <span className="text-muted">{t('trades.filterSymbol')}</span>
                <select value={symbolFilter} onChange={e => setSymbolFilter(e.target.value)}>
                  <option value="all">{t('trades.filterAll')}</option>
                  {symbols.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label className="trades-filter">
                <span className="text-muted">{t('trades.filterStatus')}</span>
                <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                  <option value="all">{t('trades.filterAll')}</option>
                  <option value="open">{t('trades.statusOpen')}</option>
                  <option value="closed">{t('trades.statusClosed')}</option>
                  <option value="risk">{t('trades.statusRisk')}</option>
                  <option value="error">{t('trades.statusError')}</option>
                </select>
              </label>
              {regimes.length > 0 && (
                <label className="trades-filter">
                  <span className="text-muted">{t('trades.filterRegime')}</span>
                  <select value={regimeFilter} onChange={e => setRegimeFilter(e.target.value)}>
                    <option value="all">{t('trades.filterRegimeAll')}</option>
                    {regimes.map(r => (
                      <option key={r} value={String(r)}>
                        {t('trades.filterRegimeLabel', { regime: r })}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}
        </div>
        <div className="flex-gap-sm">
          <RippleButton className="btn btn-ghost btn-sm" disabled={syncing} onClick={syncBinance}>
            <RefreshCw size={14} className={syncing ? 'spin-icon' : undefined} />
            {t('trades.syncBinance')}
          </RippleButton>
          <RippleButton
            className="btn btn-ghost btn-sm"
            disabled={view === 'executions' ? !rows.length : !displayLogs.length}
            onClick={view === 'executions' ? exportRows : exportLogs}
          >
            <Download size={14} /> {t('trades.exportCsv')}
          </RippleButton>
        </div>
      </div>

      {view === 'logs' && (
        <p className="text-muted text-sm section-mb-sm">
          {t('trades.logsHint', { platform: platformLogs.length, exchange: exchangeLogs.length })}
        </p>
      )}

      {view === 'executions' && (
        <div className="section-mb-sm">
          <p className="text-muted text-sm">
            {t('trades.periodStats', {
              count: periodStats.count,
              closed: periodStats.closed,
              pnl: periodStats.pnl.toFixed(2),
              eth: (periodStats.bySym.ETHUSDT ?? 0).toFixed(2),
              xau: (periodStats.bySym.XAUUSDT ?? 0).toFixed(2),
            })}
            {timeFilter === 'since' && tradingSince
              ? ` · ${t('trades.sinceLabel', { date: String(tradingSince).slice(0, 10) })}`
              : ''}
          </p>
          {periodStats.symbolRows.length > 0 && (
            <GlassCard className="p-3 section-mt-xs">
              <SymbolPnlStrip
                title={t('analytics.pnlBySymbol')}
                hint={t('dashboard.dualSymbolHint')}
                rows={periodStats.symbolRows}
              />
            </GlassCard>
          )}
        </div>
      )}

      {view === 'executions' ? (
        <GlassCard className="p-0 table-wrap">
          <table className="data-table trades-table">
            <thead>
              <tr>
                <th>{t('common.time')}</th>
                <th>{t('trades.symbol')}</th>
                <th>{t('trades.signal')}</th>
                <th>{t('trades.side')}</th>
                <th>{t('trades.qty')}</th>
                <th>{t('trades.filled')}</th>
                <th>{t('trades.slippage')}</th>
                <th>{t('trades.funding')}</th>
                <th>{t('common.status')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={10} className="empty-cell">{t('trades.empty')}</td></tr>
              ) : rows.map(tr => {
                const st = tradeStatus(tr, logs)
                const slip = getSlippage(tr)
                const funding = getFunding(tr)
                const isOpen = expanded === tr.id
                const related = logByTrade.get(tr.id) || []
                const sym = shortSymbol(tr.symbol)
                return (
                  <Fragment key={tr.id}>
                    <tr className="trades-row" onClick={() => setExpanded(isOpen ? null : tr.id)}>
                      <td>{localeDate(tr.created_at, locale)}</td>
                      <td><span className="badge badge-gray">{sym}</span></td>
                      <td><span className="badge badge-gray">{tr.action || '—'}</span></td>
                      <td><span className={`badge ${tr.side === 'LONG' ? 'badge-green' : 'badge-red'}`}>{tr.side}</span></td>
                      <td>{tr.quantity} <span className="text-muted text-xs">{qtyUnitForSymbol(sym)}</span></td>
                      <td>{getFilled(tr)}</td>
                      <td className={slip != null && slip <= 0 ? 'text-green' : slip != null ? 'text-red' : ''}>
                        {slip != null ? `${slip >= 0 ? '+' : ''}${slip.toFixed(2)}` : t('common.none')}
                      </td>
                      <td className={funding != null && funding <= 0 ? 'text-green' : funding != null ? 'text-red' : 'text-muted'}>
                        {funding != null ? `${funding >= 0 ? '+' : ''}${funding.toFixed(4)}` : t('common.none')}
                      </td>
                      <td><span className={`badge ${statusBadge(st)}`}>{statusLabel(st)}</span></td>
                      <td className="trades-expand-icon">{isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</td>
                    </tr>
                    {isOpen && (
                      <tr className="trades-detail-row">
                        <td colSpan={9}>
                          <div className="trades-detail-panel">
                            <p><strong>{t('trades.detailTitle')}</strong></p>
                            <div className="trades-detail-grid">
                              <span>{t('trades.orderId')}: #{tr.id}</span>
                              <span>{t('trades.symbol')}: {tr.symbol}</span>
                              <span>{t('trades.avgPrice')}: ${tr.entry_price?.toFixed(2)}</span>
                              <span>{t('trades.pnl')}: {tr.realized_pnl != null ? `$${tr.realized_pnl.toFixed(2)}` : t('common.none')}</span>
                              <span>{t('trades.closedAt')}: {tr.closed_at ? localeDate(tr.closed_at, locale) : t('common.none')}</span>
                              <span>{t('trades.regime')}: {tr.regime}</span>
                              <span>{t('trades.funding')}: {funding != null ? `$${funding.toFixed(4)}` : t('common.none')}</span>
                            </div>
                            {related.length > 0 && (
                              <div className="trades-log-list">
                                {related.map(l => (
                                  <div key={l.id} className="trades-log-item">
                                    <span className="badge badge-gray">{l.event_type}</span>
                                    <span>{l.message}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
          {view === 'executions' && (
            <div className="table-toolbar flex-gap-sm p-4">
              <button className="btn btn-ghost btn-sm" type="button" disabled={page === 0} onClick={() => setPage(p => p - 1)}>{t('common.prev')}</button>
              <span className="text-muted text-sm">{t('common.page')} {page + 1}</span>
              <button className="btn btn-ghost btn-sm" type="button" disabled={rows.length < PAGE_SIZE} onClick={() => setPage(p => p + 1)}>{t('common.next')}</button>
            </div>
          )}
        </GlassCard>
      ) : (
        <GlassCard className="p-0 table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('common.time')}</th>
                <th>{t('trades.logType')}</th>
                <th>{t('trades.logMessage')}</th>
                <th>{t('trades.side')}</th>
                <th>{t('trades.qty')}</th>
                <th>{t('trades.avgPrice')}</th>
                <th>{t('trades.pnl')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {displayLogs.length === 0 ? (
                <tr><td colSpan={8} className="empty-cell">{t('trades.logsEmpty')}</td></tr>
              ) : displayLogs.map(l => {
                const d = resolveDetail(l)
                const isOpen = expandedLog === l.id
                const verified = d.live_verified === true
                return (
                  <Fragment key={l.id}>
                    <tr className="trades-row" onClick={() => setExpandedLog(isOpen ? null : l.id)}>
                      <td>{localeDate(l.created_at, locale)}</td>
                      <td>
                        <span className={`badge ${l.event_type === 'BINANCE_FILL' ? 'badge-green' : verified ? 'badge-green' : 'badge-gray'}`}>
                          {l.event_type}
                        </span>
                      </td>
                      <td className="trades-log-msg">{l.message}</td>
                      <td>{String(d.side ?? '—')}</td>
                      <td>{d.qty != null ? String(d.qty) : '—'}</td>
                      <td>{d.price != null || d.entry != null ? `$${Number(d.price ?? d.entry).toFixed(2)}` : '—'}</td>
                      <td>{d.realized_pnl != null || d.pnl != null ? `$${Number(d.realized_pnl ?? d.pnl).toFixed(4)}` : '—'}</td>
                      <td className="trades-expand-icon">{isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</td>
                    </tr>
                    {isOpen && (
                      <tr className="trades-detail-row">
                        <td colSpan={8}>
                          <div className="trades-detail-panel">
                            <p><strong>{t('tradeLog.logDetail')}</strong></p>
                            <TradeLogDetailPanel log={l} />
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </GlassCard>
      )}
    </Layout>
  )
}
