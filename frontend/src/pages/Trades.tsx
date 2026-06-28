import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'
import { useI18n, localeDate } from '../i18n'

export default function Trades() {
  const { t, locale } = useI18n()
  const [trades, setTrades] = useState<any[]>([])

  useEffect(() => { userApi.trades().then(setTrades) }, [])

  return (
    <Layout>
      <PageHeader title={t('trades.title')} />
      <GlassCard className="p-0 table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('common.time')}</th><th>{t('trades.side')}</th><th>{t('trades.qty')}</th>
              <th>{t('trades.entry')}</th><th>{t('trades.exit')}</th><th>{t('trades.pnl')}</th>
              <th>{t('trades.regime')}</th><th>{t('common.status')}</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr><td colSpan={8} className="empty-cell">{t('trades.empty')}</td></tr>
            ) : trades.map(tr => (
              <tr key={tr.id}>
                <td>{localeDate(tr.created_at, locale)}</td>
                <td><span className={`badge ${tr.side === 'LONG' ? 'badge-green' : 'badge-red'}`}>{tr.side}</span></td>
                <td>{tr.quantity}</td>
                <td>${tr.entry_price?.toFixed(2)}</td>
                <td>{tr.exit_price ? `$${tr.exit_price.toFixed(2)}` : t('common.none')}</td>
                <td className={tr.realized_pnl >= 0 ? 'text-green' : 'text-red'}>
                  {tr.realized_pnl ? `${tr.realized_pnl >= 0 ? '+' : ''}$${tr.realized_pnl.toFixed(2)}` : t('common.none')}
                </td>
                <td><span className="badge badge-gray">{tr.regime}</span></td>
                <td><span className={`badge ${tr.status === 'open' ? 'badge-green' : 'badge-gray'}`}>{tr.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </Layout>
  )
}
