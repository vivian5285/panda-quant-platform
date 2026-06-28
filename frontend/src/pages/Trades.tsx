import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'

export default function Trades() {
  const [trades, setTrades] = useState<any[]>([])

  useEffect(() => { userApi.trades().then(setTrades) }, [])

  return (
    <Layout>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>交易记录</h1>
      <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
        <table className="data-table">
          <thead>
            <tr>
              <th>时间</th><th>方向</th><th>数量</th><th>入场价</th><th>出场价</th><th>盈亏</th><th>档位</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr><td colSpan={8} className="text-muted" style={{ textAlign: 'center', padding: 40 }}>暂无交易记录</td></tr>
            ) : trades.map(t => (
              <tr key={t.id}>
                <td>{new Date(t.created_at).toLocaleString('zh-CN')}</td>
                <td><span className={`badge ${t.side === 'LONG' ? 'badge-green' : 'badge-red'}`}>{t.side}</span></td>
                <td>{t.quantity}</td>
                <td>${t.entry_price?.toFixed(2)}</td>
                <td>{t.exit_price ? `$${t.exit_price.toFixed(2)}` : '—'}</td>
                <td className={t.realized_pnl >= 0 ? 'text-green' : 'text-red'}>
                  {t.realized_pnl ? `${t.realized_pnl >= 0 ? '+' : ''}$${t.realized_pnl.toFixed(2)}` : '—'}
                </td>
                <td><span className="badge badge-gray">{t.regime}档</span></td>
                <td><span className={`badge ${t.status === 'open' ? 'badge-green' : 'badge-gray'}`}>{t.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </Layout>
  )
}
