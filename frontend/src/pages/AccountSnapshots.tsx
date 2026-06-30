import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'
import { useI18n, localeDate } from '../i18n'

export default function AccountSnapshots() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [rows, setRows] = useState<any[]>([])

  useEffect(() => {
    userApi.principalHistory().then(setRows).catch(() => setRows([]))
  }, [])

  const typeLabel = (type: string) => t(`snapshots.snapshotTypes.${type}`) || type

  return (
    <Layout>
      <PageHeader title={t('snapshots.title')} subtitle={t('snapshots.subtitle')} />

      <GlassCard className="p-4 section-mb-lg">
        <p className="text-sm">{t('snapshots.dualNote')}</p>
      </GlassCard>

      <GlassCard className="p-0 table-wrap card-overflow-hidden">
        <table className="data-table data-table-sm">
          <thead>
            <tr>
              <th>{t('common.time')}</th>
              <th>{t('snapshots.equity')}</th>
              <th>{t('snapshots.tradePnlCycle')}</th>
              <th>{t('snapshots.equityDelta')}</th>
              <th>{t('snapshots.binanceFillPnl')}</th>
              <th>{t('snapshots.typeCol')}</th>
              <th>{t('snapshots.note')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={7} className="empty-cell">{t('snapshots.empty')}</td></tr>
            ) : rows.map(r => {
              const equity = r.live_equity ?? r.amount
              const tradeCycle = r.trade_pnl_cycle
              const equityDelta = r.equity_delta
              const diverge = tradeCycle != null && equityDelta != null
                ? Math.abs(equityDelta - tradeCycle) >= 50
                : false
              return (
                <tr key={r.id} className={diverge ? 'settlement-pending-row' : undefined}>
                  <td>{localeDate(r.created_at, locale)}</td>
                  <td>${(equity ?? 0).toFixed(2)}</td>
                  <td className={(tradeCycle ?? 0) >= 0 ? 'text-green' : 'text-red'}>
                    {tradeCycle != null ? `$${tradeCycle.toFixed(2)}` : '—'}
                  </td>
                  <td className={(equityDelta ?? 0) >= 0 ? 'text-green' : 'text-red'}>
                    {equityDelta != null ? `$${equityDelta.toFixed(2)}` : '—'}
                  </td>
                  <td className="text-muted">
                    {r.binance_fill_pnl_cycle != null ? `$${r.binance_fill_pnl_cycle.toFixed(4)}` : '—'}
                  </td>
                  <td><span className="badge badge-gray">{typeLabel(r.snapshot_type)}</span></td>
                  <td className="cell-ellipsis text-muted text-xs" title={r.note}>{r.note || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </GlassCard>
    </Layout>
  )
}
