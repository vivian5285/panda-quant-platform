import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import { adminApi } from '../api'

const payStatus: Record<string, string> = {
  pending: '待支付', paid: '待确认', confirmed: '已确认', rejected: '已驳回',
}
const wStatus: Record<string, string> = {
  pending: '待审核', auto_approved: '自动通过', approved: '已批准', rejected: '已驳回', completed: '已完成',
}

export default function Admin() {
  const [overview, setOverview] = useState<any>(null)
  const [users, setUsers] = useState<any[]>([])
  const [settlements, setSettlements] = useState<any[]>([])
  const [depositAddrs, setDepositAddrs] = useState<any[]>([])
  const [withdrawals, setWithdrawals] = useState<any[]>([])
  const [alerts, setAlerts] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const [tab, setTab] = useState<'users' | 'settlements' | 'addresses' | 'withdrawals' | 'alerts'>('users')
  const [newAddr, setNewAddr] = useState({ chain: 'TRC20', address: '', label: '' })
  const [completeTx, setCompleteTx] = useState<Record<number, string>>({})

  const load = () => {
    adminApi.overview().then(setOverview)
    adminApi.users().then(setUsers)
    adminApi.settlements().then(setSettlements)
    adminApi.depositAddresses().then(setDepositAddrs)
    adminApi.withdrawals().then(setWithdrawals)
    adminApi.alerts().then(setAlerts)
  }

  useEffect(() => { load() }, [])

  const runSettlement = async () => {
    const res = await adminApi.runSettlement()
    setMsg(`已生成 ${res.created} 条结算单（7/10天智能周期）`)
    load()
  }

  const confirm = async (id: number) => {
    await adminApi.confirmSettlement(id)
    setMsg(`结算 #${id} 已确认，推荐奖励已入账`)
    load()
  }

  const addAddr = async (e: React.FormEvent) => {
    e.preventDefault()
    await adminApi.addDepositAddress(newAddr)
    setNewAddr({ chain: 'TRC20', address: '', label: '' })
    setMsg('收款地址已添加')
    load()
  }

  const completeWd = async (id: number) => {
    const tx = completeTx[id]
    if (!tx) return
    await adminApi.completeWithdrawal(id, tx)
    setMsg(`提现 #${id} 已完成`)
    load()
  }

  const tabs = [
    { key: 'users' as const, label: '用户' },
    { key: 'alerts' as const, label: `交易告警${overview?.unread_alerts ? ` (${overview.unread_alerts})` : ''}` },
    { key: 'settlements' as const, label: '结算' },
    { key: 'addresses' as const, label: '收款地址' },
    { key: 'withdrawals' as const, label: '提现审核' },
  ]

  return (
    <Layout>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>管理后台</h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 16, marginBottom: 24 }}>
        <StatCard label="总用户" value={String(overview?.total_users || 0)} />
        <StatCard label="活跃 API" value={String(overview?.active_api_users || 0)} />
        <StatCard label="待支付" value={String(overview?.pending_settlements || 0)} />
        <StatCard label="待确认付款" value={String(overview?.pending_payments || 0)} />
        <StatCard label="待处理提现" value={String(overview?.pending_withdrawals || 0)} />
        <StatCard label="未读告警" value={String(overview?.unread_alerts || 0)} />
      </div>

      {msg && <p className="text-green" style={{ marginBottom: 16 }}>{msg}</p>}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {tabs.map(t => (
          <button key={t.key} className={`btn ${tab === t.key ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
        <button className="btn btn-primary" style={{ marginLeft: 'auto' }} onClick={runSettlement}>执行结算扫描</button>
      </div>

      {tab === 'users' && (
        <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
          <table className="data-table">
            <thead><tr><th>UID</th><th>邮箱/手机</th><th>昵称</th><th>角色</th><th>API</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td><span className="badge badge-gray">{u.uid}</span></td>
                  <td>{u.email || u.phone || '—'}</td>
                  <td>{u.nickname || '—'}</td>
                  <td><span className="badge badge-gray">{u.role}</span></td>
                  <td><span className={`badge ${u.api_status === 'active' ? 'badge-green' : 'badge-gray'}`}>{u.api_status}</span></td>
                  <td>{u.is_active ? '✅' : '❌'}</td>
                  <td>
                    <button className="btn btn-ghost" style={{ padding: '4px 12px', fontSize: 12 }}
                      onClick={() => adminApi.toggleUser(u.id).then(load)}>
                      {u.is_active ? '禁用' : '启用'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      {tab === 'settlements' && (
        <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>用户</th><th>周期</th><th>净盈利</th><th>应付</th><th>付款</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              {settlements.map(s => (
                <tr key={s.id}>
                  <td>{s.id}</td><td>#{s.user_id}</td>
                  <td>{s.cycle_days}天</td>
                  <td className="text-green">${s.net_profit?.toFixed(2)}</td>
                  <td>${s.user_payable?.toFixed(2)}</td>
                  <td style={{ fontSize: 11 }}>
                    {s.payment_chain && `${s.payment_chain} $${s.payment_amount}`}
                    {s.payment_tx_hash && <div className="text-muted">{s.payment_tx_hash.slice(0, 16)}...</div>}
                  </td>
                  <td><span className="badge badge-gray">{payStatus[s.payment_status] || s.payment_status}</span></td>
                  <td style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {(s.payment_status === 'paid' || s.payment_status === 'pending') && (
                      <button className="btn btn-ghost" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => confirm(s.id)}>确认</button>
                    )}
                    {s.payment_status === 'paid' && (
                      <button className="btn btn-ghost" style={{ padding: '4px 8px', fontSize: 11 }}
                        onClick={() => adminApi.rejectSettlement(s.id).then(load)}>驳回</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      {tab === 'addresses' && (
        <div>
          <GlassCard green className="p-6" style={{ marginBottom: 24, maxWidth: 520 }}>
            <h3 style={{ fontSize: 15, marginBottom: 16 }}>添加 USDT 收款地址</h3>
            <form onSubmit={addAddr}>
              <select className="input" value={newAddr.chain} onChange={e => setNewAddr({ ...newAddr, chain: e.target.value })} style={{ marginBottom: 8 }}>
                {['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL'].map(c => <option key={c}>{c}</option>)}
              </select>
              <input className="input" placeholder="标签（如：主收款-TRC20）" value={newAddr.label}
                onChange={e => setNewAddr({ ...newAddr, label: e.target.value })} style={{ marginBottom: 8 }} />
              <input className="input" placeholder="USDT 地址" value={newAddr.address}
                onChange={e => setNewAddr({ ...newAddr, address: e.target.value })} required style={{ marginBottom: 12 }} />
              <button className="btn btn-primary" type="submit">添加</button>
            </form>
          </GlassCard>
          <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
            <table className="data-table">
              <thead><tr><th>公链</th><th>标签</th><th>地址</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                {depositAddrs.map(a => (
                  <tr key={a.id}>
                    <td><span className="badge badge-green">{a.chain}</span></td>
                    <td>{a.label || '—'}</td>
                    <td style={{ fontSize: 11, fontFamily: 'monospace', wordBreak: 'break-all' }}>{a.address}</td>
                    <td>{a.is_active ? '✅' : '❌'}</td>
                    <td style={{ display: 'flex', gap: 4 }}>
                      <button className="btn btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }}
                        onClick={() => adminApi.toggleDepositAddress(a.id).then(load)}>切换</button>
                      <button className="btn btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }}
                        onClick={() => adminApi.deleteDepositAddress(a.id).then(load)}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GlassCard>
        </div>
      )}

      {tab === 'alerts' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button className="btn btn-ghost" style={{ fontSize: 12 }}
              onClick={() => adminApi.readAllAlerts().then(() => { setMsg('已全部标记已读'); load() })}>
              全部已读
            </button>
          </div>
          <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
            <table className="data-table">
              <thead>
                <tr><th>时间</th><th>UID</th><th>级别</th><th>类型</th><th>标题</th><th>详情</th><th>操作</th></tr>
              </thead>
              <tbody>
                {alerts.length === 0 && (
                  <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32 }} className="text-muted">暂无告警</td></tr>
                )}
                {alerts.map(a => (
                  <tr key={a.id} style={{ opacity: a.is_read ? 0.6 : 1 }}>
                    <td style={{ fontSize: 11 }}>{new Date(a.created_at).toLocaleString()}</td>
                    <td><span className="badge badge-gray">{a.uid || a.user_id}</span></td>
                    <td>
                      <span className={`badge ${a.severity === 'critical' ? 'badge-red' : a.severity === 'warning' ? 'badge-gray' : 'badge-green'}`}>
                        {a.severity}
                      </span>
                    </td>
                    <td style={{ fontSize: 11 }}>{a.alert_type}</td>
                    <td>{a.title}</td>
                    <td style={{ fontSize: 12, maxWidth: 280 }}>{a.message}</td>
                    <td>
                      {!a.is_read && (
                        <button className="btn btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }}
                          onClick={() => adminApi.readAlert(a.id).then(load)}>已读</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GlassCard>
        </div>
      )}

      {tab === 'withdrawals' && (
        <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
          <table className="data-table">
            <thead><tr><th>ID</th><th>用户</th><th>公链</th><th>扣除</th><th>手续费</th><th>到账</th><th>地址</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {withdrawals.map(w => (
                <tr key={w.id}>
                  <td>{w.id}</td><td>#{w.user_id}</td>
                  <td><span className="badge badge-gray">{w.chain}</span></td>
                  <td>${w.amount?.toFixed(2)}</td>
                  <td className="text-muted">${(w.network_fee ?? 0).toFixed(2)}</td>
                  <td className="text-green">${(w.amount_net ?? w.amount)?.toFixed(2)}</td>
                  <td style={{ fontSize: 10, fontFamily: 'monospace' }}>{w.address.slice(0, 12)}...</td>
                  <td><span className={`badge ${w.status === 'completed' ? 'badge-green' : 'badge-gray'}`}>{wStatus[w.status]}</span></td>
                  <td>
                    {w.status !== 'completed' && w.status !== 'rejected' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <input className="input" placeholder="TxHash" style={{ fontSize: 11, padding: '4px 8px' }}
                          value={completeTx[w.id] || ''} onChange={e => setCompleteTx({ ...completeTx, [w.id]: e.target.value })} />
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button className="btn btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }}
                            onClick={() => adminApi.approveWithdrawal(w.id).then(load)}>批准</button>
                          <button className="btn btn-primary" style={{ fontSize: 11, padding: '4px 8px' }}
                            onClick={() => completeWd(w.id)}>打款完成</button>
                          <button className="btn btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }}
                            onClick={() => adminApi.rejectWithdrawal(w.id, '审核未通过').then(load)}>驳回</button>
                        </div>
                      </div>
                    )}
                    {w.tx_hash && <span className="text-muted" style={{ fontSize: 10 }}>{w.tx_hash.slice(0, 12)}...</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}
    </Layout>
  )
}
