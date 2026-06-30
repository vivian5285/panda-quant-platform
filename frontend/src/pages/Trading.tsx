import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import TradingViewWidget from '../components/landing/TradingViewWidget'
import SettlementGateBanner from '../components/SettlementGateBanner'
import { userApi } from '../api'
import { useI18n, localeDate } from '../i18n'
import { useTheme } from '../store/theme'

function fmt(n: number) {
  const prefix = n >= 0 ? '+$' : '-$'
  return prefix + Math.abs(n).toFixed(2)
}

export default function Trading() {
  const { t, locale } = useI18n()
  const { theme } = useTheme()
  const [dash, setDash] = useState<any>(null)
  const [apiMeta, setApiMeta] = useState<any>(null)
  const [trades, setTrades] = useState<any[]>([])

  const load = () => {
    userApi.dashboard().then(setDash)
    userApi.apiStatus().then(setApiMeta).catch(() => {})
    userApi.trades().then((rows: any[]) => setTrades(rows.slice(0, 8))).catch(() => {})
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 15000)
    return () => clearInterval(timer)
  }, [])

  const pos = dash?.open_position
  const leverage = apiMeta?.leverage ? `${apiMeta.leverage}x` : '—'

  return (
    <Layout>
      <PageHeader title={t('nav.trading')} subtitle={t('trading.subtitle')} />
      <SettlementGateBanner
        blocked={dash?.settlement_blocked}
        deferred={dash?.settlement_fee_deferred}
        settlement={dash?.pending_settlement}
      />
      <div className="stat-grid">
        <StatCard label={t('dashboard.balance')} countUp={{ end: dash?.balance || 0, prefix: '$', decimals: 2 }} />
        <StatCard label={t('dashboard.unrealized')} countUp={{ end: dash?.unrealized_pnl || 0, pnl: true, decimals: 2 }} />
        <StatCard label={t('trading.leverage')} value={leverage} />
        <StatCard label={t('dashboard.cyclePnl')} countUp={{ end: dash?.cycle_pnl || 0, pnl: true, decimals: 2 }} />
      </div>

      <GlassCard className="p-4 trading-chart-card section-mb-lg">
        <h3 className="card-heading">{t('dashboard.marketChart')}</h3>
        <TradingViewWidget
          scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
          className="trading-chart-h"
          config={{
            autosize: true,
            symbol: 'BINANCE:ETHUSDT',
            interval: '15',
            timezone: 'Etc/UTC',
            theme: theme === 'dark' ? 'dark' : 'light',
            style: '1',
            locale: locale === 'zh' ? 'zh_CN' : 'en',
            enable_publishing: false,
            hide_top_toolbar: false,
            hide_legend: false,
            allow_symbol_change: true,
            backgroundColor: 'transparent',
          }}
        />
      </GlassCard>

      {pos?.has_position && (
        <GlassCard className="p-6 section-mb-lg">
          <h3 className="card-heading">{t('dashboard.currentPosition')}</h3>
          <div className="stat-grid stat-grid-flush">
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.direction')}</p>
              <p className={`stat-value-xl ${pos.side === 'LONG' ? 'text-green' : 'text-red'}`}>{pos.side}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.qty')}</p>
              <p className="stat-value-xl">{pos.qty} {t('admin.ethUnit')}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.entry')}</p>
              <p className="stat-value-xl">${pos.entry_price?.toFixed(2)}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('dashboard.floatingPnl')}</p>
              <p className={`stat-value-xl ${(pos.unrealized_pnl || 0) >= 0 ? 'text-green' : 'text-red'}`}>{fmt(pos.unrealized_pnl || 0)}</p>
            </div>
          </div>
        </GlassCard>
      )}

      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="panel-header">
          <h3 className="panel-title-sm">{t('dashboard.recentOrders')}</h3>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('trades.signal')}</th>
              <th>{t('trades.side')}</th>
              <th>{t('common.time')}</th>
              <th>{t('trades.pnl')}</th>
              <th>{t('common.status')}</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr><td colSpan={5} className="empty-cell">{t('trades.empty')}</td></tr>
            ) : trades.map(tr => (
              <tr key={tr.id}>
                <td><span className="badge badge-gray">{tr.action || tr.side}</span></td>
                <td>{tr.side}</td>
                <td className="text-muted text-sm">{tr.closed_at ? localeDate(tr.closed_at, locale) : localeDate(tr.created_at, locale)}</td>
                <td className={(tr.realized_pnl || 0) >= 0 ? 'text-green' : 'text-red'}>{fmt(tr.realized_pnl || 0)}</td>
                <td>{tr.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      <GlassCard className="p-6">
        <h3 className="card-heading">{t('nav.trades')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('trades.subtitle')}</p>
        <Link to="/trades" className="btn btn-primary btn-link">
          {t('nav.trades')} <ArrowRight size={16} />
        </Link>
      </GlassCard>
    </Layout>
  )
}
