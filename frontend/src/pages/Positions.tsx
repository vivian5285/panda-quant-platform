import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import SettlementGateBanner from '../components/SettlementGateBanner'
import { userApi } from '../api'
import { useDashboardWebSocket } from '../hooks/useDashboardWebSocket'
import { useI18n, localeDate } from '../i18n'

function PositionBlock({ pos, t }: { pos: any; t: (k: string) => string }) {
  if (!pos?.has_position) return null
  return (
    <div className="stat-grid stat-grid-flush">
      <StatCard label={t('common.symbol')} value={pos.symbol || '—'} />
      <StatCard label={t('trades.side')} value={pos.side?.toUpperCase() || '—'} />
      <StatCard label={t('trades.qty')} value={String(pos.qty ?? pos.quantity ?? '—')} />
      <StatCard label={t('positions.entry')} value={pos.entry_price ? `$${Number(pos.entry_price).toFixed(2)}` : '—'} />
      <StatCard label={t('positions.mark')} value={pos.mark_price ? `$${Number(pos.mark_price).toFixed(2)}` : '—'} />
      <StatCard label={t('dashboard.unrealized')} countUp={{ end: pos.unrealized_pnl ?? 0, pnl: true, decimals: 2 }} />
      <StatCard label={t('positions.leverage')} value={pos.leverage ? `${pos.leverage}x` : '—'} />
    </div>
  )
}

export default function Positions() {
  const { t, locale } = useI18n()
  const [data, setData] = useState<any>(null)
  const [dash, setDash] = useState<any>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  const load = useCallback(() => {
    userApi.positions().then(res => {
      setData(res)
      setLastUpdate(new Date())
    }).catch(() => {})
    userApi.dashboard().then(setDash).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [load])

  useDashboardWebSocket(useCallback((msg: any) => {
    if (msg?.type === 'dashboard' || msg?.open_position) {
      load()
    }
  }, [load]))

  const list: any[] =
    data?.open_positions?.length
      ? data.open_positions
      : (data?.open_position?.has_position || dash?.open_position?.has_position)
        ? [data?.open_position || dash?.open_position]
        : []
  const symbols = data?.trading_symbols || ['ETHUSDT', 'XAUUSDT']

  return (
    <Layout>
      <PageHeader
        title={t('positions.title')}
        subtitle={t('positions.subtitle')}
        action={
          <button type="button" className="btn btn-ghost btn-sm" onClick={load}>
            <RefreshCw size={14} /> {t('common.refresh')}
          </button>
        }
      />
      <SettlementGateBanner
        blocked={dash?.settlement_blocked}
        deferred={dash?.settlement_fee_deferred}
        settlement={dash?.pending_settlement}
      />

      <div className="stat-grid section-mb-lg">
        <StatCard label={t('dashboard.balance')} countUp={{ end: data?.balance ?? dash?.balance ?? 0, prefix: '$', decimals: 2 }} />
        <StatCard label={t('dashboard.unrealized')} countUp={{ end: data?.unrealized_pnl ?? dash?.unrealized_pnl ?? 0, pnl: true, decimals: 2 }} />
        <StatCard label={t('common.symbol')} value={symbols.join(' · ')} />
        <StatCard label={t('positions.lastUpdate')} value={lastUpdate ? localeDate(lastUpdate.toISOString(), locale) : '—'} />
      </div>

      {list.length === 0 ? (
        <GlassCard className="p-6">
          <h3 className="card-heading">{t('positions.current')}</h3>
          <p className="text-muted empty-state">{t('positions.flat')}</p>
          <p className="text-muted text-xs section-mt-sm">{t('positions.realtimeHint')}</p>
        </GlassCard>
      ) : (
        list.map((pos, idx) => (
          <GlassCard key={`${pos.symbol || 'pos'}-${idx}`} className="p-6 section-mb-md">
            <h3 className="card-heading">
              {t('positions.current')}
              {pos.symbol ? ` · ${pos.symbol}` : ''}
            </h3>
            <PositionBlock pos={pos} t={t} />
            <p className="text-muted text-xs section-mt-sm">{t('positions.realtimeHint')}</p>
          </GlassCard>
        ))
      )}
    </Layout>
  )
}
