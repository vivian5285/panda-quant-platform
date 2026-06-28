import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import TradingViewWidget from '../components/landing/TradingViewWidget'
import { userApi } from '../api'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'
import { localeDate } from '../i18n'

function fmt(n: number) {
  const prefix = n >= 0 ? '+$' : '-$'
  return prefix + Math.abs(n).toFixed(2)
}

export default function Trading() {
  const { t, locale } = useI18n()
  const { theme } = useTheme()
  const [dash, setDash] = useState<any>(null)
  const [trades, setTrades] = useState<any[]>([])

  useEffect(() => {
    userApi.dashboard().then(setDash)
    userApi.trades().then(setTrades)
    const timer = setInterval(() => {
      userApi.dashboard().then(setDash)
      userApi.trades().then(setTrades)
    }, 15000)
    return () => clearInterval(timer)
  }, [])

  const pos = dash?.open_position

  return (
    <Layout>
      <PageHeader title={t('nav.trading')} subtitle={t('trading.subtitle')} />
      <div className="stat-grid">
        <GlassCard className="stat-tile p-4"><p className="text-muted">{t('dashboard.balance')}</p><strong>${(dash?.balance || 0).toFixed(2)}</strong></GlassCard>
        <GlassCard className="stat-tile p-4"><p className="text-muted">{t('dashboard.unrealized')}</p><strong className={(dash?.unrealized_pnl || 0) >= 0 ? 'text-green' : 'text-red'}>{fmt(dash?.unrealized_pnl || 0)}</strong></GlassCard>
        <GlassCard className="stat-tile p-4"><p className="text-muted">{t('trading.leverage')}</p><strong>20x</strong></GlassCard>
        <GlassCard className="stat-tile p-4"><p className="text-muted">{t('dashboard.cyclePnl')}</p><strong>{fmt(dash?.cycle_pnl || 0)}</strong></GlassCard>
      </div>

      <GlassCard className="p-4" style={{ marginBottom: 24 }}>
        <TradingViewWidget
          scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
          style={{ height: 420 }}
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
        <GlassCard green className="p-6" style={{ marginBottom: 24 }}>
          <h3 className="card-heading">{t('dashboard.currentPosition')}</h3>
          <p>{pos.side} · {pos.qty} ETH · ${pos.entry_price?.toFixed(2)} · {fmt(pos.unrealized_pnl)}</p>
        </GlassCard>
      )}

      <GlassCard className="p-6">
        <h3 className="card-heading">{t('nav.trades')}</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>{t('trades.side')}</th><th>{t('common.time')}</th><th>{t('trades.pnl')}</th><th>{t('trades.regime')}</th><th>{t('common.status')}</th></tr></thead>
            <tbody>
              {trades.map(tr => (
                <tr key={tr.id}>
                  <td>{tr.side}</td>
                  <td>{localeDate(tr.closed_at || tr.created_at, locale)}</td>
                  <td className={(tr.realized_pnl || 0) >= 0 ? 'text-green' : 'text-red'}>{fmt(tr.realized_pnl || 0)}</td>
                  <td>R{tr.regime}</td>
                  <td>{tr.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </Layout>
  )
}
