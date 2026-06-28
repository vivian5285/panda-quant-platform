import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import TabBar from '../components/TabBar'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import { adminApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n, localeDate } from '../i18n'

export default function Admin() {
  const token = useAuth(s => s.token)
  const { t, locale } = useI18n()
  const [overview, setOverview] = useState<any>(null)
  const [users, setUsers] = useState<any[]>([])
  const [settlements, setSettlements] = useState<any[]>([])
  const [depositAddrs, setDepositAddrs] = useState<any[]>([])
  const [withdrawals, setWithdrawals] = useState<any[]>([])
  const [alerts, setAlerts] = useState<any[]>([])
  const [msg, setMsg] = useState('')
  const [tab, setTab] = useState<'users' | 'settlements' | 'addresses' | 'withdrawals' | 'alerts' | 'system'>('users')
  const [monitor, setMonitor] = useState<any>(null)
  const [auditLogs, setAuditLogs] = useState<any[]>([])
  const [orders, setOrders] = useState<any[]>([])
  const [online, setOnline] = useState<any>(null)
  const [newAddr, setNewAddr] = useState({ chain: 'TRC20', address: '', label: '' })
  const [completeTx, setCompleteTx] = useState<Record<number, string>>({})
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
  const [userDetail, setUserDetail] = useState<any>(null)
  const [userTrades, setUserTrades] = useState<any[]>([])
  const [userLogs, setUserLogs] = useState<any[]>([])
  const [userDetailTab, setUserDetailTab] = useState<'overview' | 'trades' | 'logs'>('overview')

  const loadUserDetail = (id: number) => {
    setSelectedUserId(id)
    setUserDetailTab('overview')
    adminApi.userDetail(id).then(setUserDetail)
    adminApi.userTrades(id).then(setUserTrades)
    adminApi.userLogs(id).then(setUserLogs)
  }

  const closeUserDetail = () => {
    setSelectedUserId(null)
    setUserDetail(null)
    setUserTrades([])
    setUserLogs([])
  }

  const load = () => {
    adminApi.overview().then(setOverview)
    adminApi.users().then(setUsers)
    adminApi.settlements().then(setSettlements)
    adminApi.depositAddresses().then(setDepositAddrs)
    adminApi.withdrawals().then(setWithdrawals)
    adminApi.alerts().then(setAlerts)
    adminApi.systemMonitor().then(setMonitor).catch(() => {})
    adminApi.auditLogs().then(setAuditLogs).catch(() => {})
    adminApi.allOrders().then(setOrders).catch(() => {})
    adminApi.onlineStats().then(setOnline).catch(() => {})
  }

  useEffect(() => {
    if (!token) return
    load()
  }, [token])

  const runSettlement = async () => {
    const res = await adminApi.runSettlement()
    setMsg(t('admin.settlementCreated', { n: res.created }))
    load()
  }

  const confirm = async (id: number) => {
    await adminApi.confirmSettlement(id)
    setMsg(t('admin.settlementConfirmed', { id }))
    load()
  }

  const addAddr = async (e: React.FormEvent) => {
    e.preventDefault()
    await adminApi.addDepositAddress(newAddr)
    setNewAddr({ chain: 'TRC20', address: '', label: '' })
    setMsg(t('admin.addrAdded'))
    load()
  }

  const completeWd = async (id: number) => {
    const tx = completeTx[id]
    if (!tx) return
    await adminApi.completeWithdrawal(id, tx)
    setMsg(t('admin.withdrawCompleted', { id }))
    load()
  }

  const tabs = [
    { key: 'users', label: t('admin.tabUsers') },
    { key: 'alerts', label: `${t('admin.tabAlerts')}${overview?.unread_alerts ? ` (${overview.unread_alerts})` : ''}` },
    { key: 'settlements', label: t('admin.tabSettlements') },
    { key: 'addresses', label: t('admin.tabAddresses') },
    { key: 'withdrawals', label: t('admin.tabWithdrawals') },
    { key: 'system', label: t('admin.tabSystem') },
  ]

  const payStatus = (s: string) => t(`admin.payStatus.${s}`) || s
  const wStatus = (s: string) => t(`admin.wStatus.${s}`) || s

  return (
    <Layout>
      <PageHeader title={t('admin.title')} />

      <div className="stat-grid">
        <StatCard label={t('admin.totalUsers')} value={String(overview?.total_users || 0)} />
        <StatCard label={t('admin.activeApi')} value={String(overview?.active_api_users || 0)} />
        <StatCard label={t('admin.pendingPay')} value={String(overview?.pending_settlements || 0)} />
        <StatCard label={t('admin.pendingConfirm')} value={String(overview?.pending_payments || 0)} />
        <StatCard label={t('admin.pendingWithdraw')} value={String(overview?.pending_withdrawals || 0)} />
        <StatCard label={t('admin.unreadAlerts')} value={String(overview?.unread_alerts || 0)} />
      </div>

      {msg && <div className="flash-msg">{msg}</div>}

      <TabBar
        tabs={tabs}
        active={tab}
        onChange={k => setTab(k as typeof tab)}
        trailing={
          <button className="btn btn-primary btn-sm" onClick={runSettlement}>{t('admin.runSettlement')}</button>
        }
      />

      {tab === 'users' && !selectedUserId && (
        <GlassCard className="p-0 table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('admin.cols.uid')}</th><th>{t('admin.emailPhone')}</th><th>{t('common.nickname')}</th>
                <th>{t('common.role')}</th><th>API</th><th>{t('common.status')}</th><th>{t('common.action')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td><span className="badge badge-gray">{u.uid}</span></td>
                  <td>{u.email || u.phone || t('common.none')}</td>
                  <td>{u.nickname || t('common.none')}</td>
                  <td><span className="badge badge-gray">{u.role}</span></td>
                  <td><span className={`badge ${u.api_status === 'active' ? 'badge-green' : 'badge-gray'}`}>{u.api_status}</span></td>
                  <td>{u.is_active ? '✅' : '❌'}</td>
                  <td style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    <button className="btn btn-primary btn-xs" onClick={() => loadUserDetail(u.id)}>{t('admin.viewUser')}</button>
                    <button className="btn btn-ghost btn-xs" onClick={() => adminApi.toggleUser(u.id).then(load)}>
                      {u.is_active ? t('common.disable') : t('common.enable')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      {tab === 'users' && selectedUserId && userDetail && (
        <div>
          <button className="btn btn-ghost btn-sm" style={{ marginBottom: 16 }} onClick={closeUserDetail}>{t('admin.backToList')}</button>
          <GlassCard className="p-6" style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>{t('admin.userDetail')} · {userDetail.profile?.uid}</h3>
            <div className="stat-grid" style={{ marginBottom: 16 }}>
              <StatCard label={t('dashboard.balance')} value={`$${userDetail.dashboard?.balance?.toFixed(2) ?? '0'}`} />
              <StatCard label={t('dashboard.cyclePnl')} value={`$${userDetail.dashboard?.cycle_pnl?.toFixed(2) ?? '0'}`} />
              <StatCard label={t('admin.tradeCount')} value={String(userDetail.trade_count ?? 0)} />
              <StatCard label={t('admin.logCount')} value={String(userDetail.log_count ?? 0)} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, fontSize: 13 }}>
              <div><span className="text-muted">{t('common.email')}:</span> {userDetail.profile?.email || t('common.none')}</div>
              <div><span className="text-muted">{t('common.phone')}:</span> {userDetail.profile?.phone || t('common.none')}</div>
              <div><span className="text-muted">API:</span> {userDetail.profile?.api_status}</div>
              <div><span className="text-muted">{t('admin.supervisorActive')}:</span> {userDetail.supervisor_active ? '✅' : '—'}</div>
              <div><span className="text-muted">{t('dashboard.principal')}:</span> ${userDetail.profile?.initial_principal?.toFixed(2) ?? '0'}</div>
            </div>
          </GlassCard>
          <TabBar
            tabs={[
              { key: 'overview', label: t('dashboard.title') },
              { key: 'trades', label: t('admin.userTrades') },
              { key: 'logs', label: t('admin.userLogs') },
            ]}
            active={userDetailTab}
            onChange={k => setUserDetailTab(k as typeof userDetailTab)}
          />
          {userDetailTab === 'overview' && userDetail.dashboard?.open_position && (
            <GlassCard className="p-4" style={{ marginTop: 16 }}>
              <p style={{ fontWeight: 600, marginBottom: 8 }}>{t('dashboard.currentPosition')}</p>
              <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{JSON.stringify(userDetail.dashboard.open_position, null, 2)}</pre>
            </GlassCard>
          )}
          {userDetailTab === 'trades' && (
            <GlassCard className="p-0 table-wrap" style={{ marginTop: 16 }}>
              <table className="data-table">
                <thead><tr><th>ID</th><th>{t('trades.side')}</th><th>{t('trades.qty')}</th><th>{t('trades.entry')}</th><th>{t('trades.pnl')}</th><th>{t('common.status')}</th></tr></thead>
                <tbody>
                  {userTrades.map(tr => (
                    <tr key={tr.id}>
                      <td>{tr.id}</td><td>{tr.side}</td><td>{tr.quantity}</td><td>{tr.entry_price}</td>
                      <td className={tr.realized_pnl >= 0 ? 'text-green' : ''}>{tr.realized_pnl?.toFixed(2)}</td><td>{tr.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </GlassCard>
          )}
          {userDetailTab === 'logs' && (
            <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {userLogs.map(log => (
                <GlassCard key={log.id} className="p-4">
                  <span className={`badge badge-gray`} style={{ marginRight: 8 }}>{log.event_type}</span>
                  <span style={{ fontSize: 14 }}>{log.message}</span>
                  <p className="text-muted" style={{ fontSize: 11, marginTop: 6 }}>{localeDate(log.created_at, locale)}</p>
                </GlassCard>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'users' && selectedUserId && !userDetail && (
        <GlassCard className="p-8"><p className="text-muted">{t('common.loading')}</p></GlassCard>
      )}

      {tab === 'settlements' && (
        <GlassCard className="p-0 table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>{t('common.user')}</th><th>{t('admin.cols.cycle')}</th>
                <th>{t('admin.cols.netProfit')}</th><th>{t('admin.cols.payable')}</th><th>{t('admin.cols.payment')}</th>
                <th>{t('common.status')}</th><th>{t('common.action')}</th>
              </tr>
            </thead>
            <tbody>
              {settlements.map(s => (
                <tr key={s.id}>
                  <td>{s.id}</td><td>#{s.user_id}</td>
                  <td>{s.cycle_days}{t('common.days')}</td>
                  <td className="text-green">${s.net_profit?.toFixed(2)}</td>
                  <td>${s.user_payable?.toFixed(2)}</td>
                  <td style={{ fontSize: 11 }}>
                    {s.payment_chain && `${s.payment_chain} $${s.payment_amount}`}
                    {s.payment_tx_hash && <div className="text-muted">{s.payment_tx_hash.slice(0, 16)}...</div>}
                  </td>
                  <td><span className="badge badge-gray">{payStatus(s.payment_status)}</span></td>
                  <td style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {(s.payment_status === 'paid' || s.payment_status === 'pending') && (
                      <button className="btn btn-ghost btn-xs" onClick={() => confirm(s.id)}>{t('common.confirm')}</button>
                    )}
                    {s.payment_status === 'paid' && (
                      <button className="btn btn-ghost btn-xs" onClick={() => adminApi.rejectSettlement(s.id).then(load)}>{t('common.reject')}</button>
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
          <p className="text-muted" style={{ fontSize: 13, marginBottom: 16 }}>{t('admin.addrHint')}</p>
          <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 520 }}>
            <h3 style={{ fontSize: 15, marginBottom: 16, fontWeight: 600 }}>{t('admin.addUsdtAddr')}</h3>
            <form onSubmit={addAddr}>
              <select className="input" value={newAddr.chain} onChange={e => setNewAddr({ ...newAddr, chain: e.target.value })} style={{ marginBottom: 8 }}>
                {['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL'].map(c => <option key={c}>{c}</option>)}
              </select>
              <input className="input" placeholder={t('admin.addrLabelPh')} value={newAddr.label}
                onChange={e => setNewAddr({ ...newAddr, label: e.target.value })} style={{ marginBottom: 8 }} />
              <input className="input" placeholder={t('admin.usdtAddrPh')} value={newAddr.address}
                onChange={e => setNewAddr({ ...newAddr, address: e.target.value })} required style={{ marginBottom: 12 }} />
              <button className="btn btn-primary" type="submit">{t('common.add')}</button>
            </form>
          </GlassCard>
          <GlassCard className="p-0 table-wrap">
            <table className="data-table">
              <thead><tr><th>{t('common.chain')}</th><th>{t('common.label')}</th><th>{t('common.address')}</th><th>{t('common.status')}</th><th>{t('common.action')}</th></tr></thead>
              <tbody>
                {depositAddrs.map(a => (
                  <tr key={a.id}>
                    <td><span className="badge badge-green">{a.chain}</span></td>
                    <td>{a.label || t('common.none')}</td>
                    <td style={{ fontSize: 11, fontFamily: 'monospace', wordBreak: 'break-all' }}>{a.address}</td>
                    <td>{a.is_active ? '✅' : '❌'}</td>
                    <td style={{ display: 'flex', gap: 4 }}>
                      <button className="btn btn-ghost btn-xs" onClick={() => adminApi.toggleDepositAddress(a.id).then(load)}>{t('common.toggle')}</button>
                      <button className="btn btn-ghost btn-xs" onClick={() => adminApi.deleteDepositAddress(a.id).then(load)}>{t('common.delete')}</button>
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
          <p className="text-muted" style={{ fontSize: 13, marginBottom: 12 }}>{t('admin.dingtalkHint')}</p>
          <div style={{ marginBottom: 16 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => adminApi.readAllAlerts().then(() => { setMsg(t('admin.allRead')); load() })}>
              {t('common.markAllRead')}
            </button>
          </div>
          <GlassCard className="p-0 table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>{t('common.time')}</th><th>{t('admin.cols.level')}</th><th>{t('admin.cols.type')}</th><th>{t('admin.cols.detail')}</th><th>{t('common.action')}</th></tr>
              </thead>
              <tbody>
                {alerts.length === 0 && (
                  <tr><td colSpan={5} className="empty-cell">{t('admin.noAlerts')}</td></tr>
                )}
                {alerts.map(a => (
                  <tr key={a.id} style={{ opacity: a.is_read ? 0.6 : 1 }}>
                    <td style={{ fontSize: 11 }}>{localeDate(a.created_at, locale)}</td>
                    <td>
                      <span className={`badge ${a.severity === 'critical' ? 'badge-red' : a.severity === 'warning' ? 'badge-gray' : 'badge-green'}`}>
                        {a.severity}
                      </span>
                    </td>
                    <td style={{ fontSize: 11 }}>{a.alert_type}</td>
                    <td style={{ fontSize: 12, maxWidth: 320 }}>{a.title} — {a.message}</td>
                    <td>
                      {!a.is_read && (
                        <button className="btn btn-ghost btn-xs" onClick={() => adminApi.readAlert(a.id).then(load)}>{t('common.markRead')}</button>
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
        <GlassCard className="p-0 table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>{t('common.user')}</th><th>{t('common.chain')}</th><th>{t('common.amount')}</th>
                <th>{t('admin.cols.fee')}</th><th>{t('admin.cols.received')}</th><th>{t('common.address')}</th>
                <th>{t('common.status')}</th><th>{t('common.action')}</th>
              </tr>
            </thead>
            <tbody>
              {withdrawals.map(w => (
                <tr key={w.id}>
                  <td>{w.id}</td><td>#{w.user_id}</td>
                  <td><span className="badge badge-gray">{w.chain}</span></td>
                  <td>${w.amount?.toFixed(2)}</td>
                  <td className="text-muted">${(w.network_fee ?? 0).toFixed(2)}</td>
                  <td className="text-green">${(w.amount_net ?? w.amount)?.toFixed(2)}</td>
                  <td style={{ fontSize: 10, fontFamily: 'monospace' }}>{w.address.slice(0, 12)}...</td>
                  <td><span className={`badge ${w.status === 'completed' ? 'badge-green' : 'badge-gray'}`}>{wStatus(w.status)}</span></td>
                  <td>
                    {w.status !== 'completed' && w.status !== 'rejected' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <input className="input" placeholder={t('admin.txHashPh')} style={{ fontSize: 11, padding: '4px 8px' }}
                          value={completeTx[w.id] || ''} onChange={e => setCompleteTx({ ...completeTx, [w.id]: e.target.value })} />
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          <button className="btn btn-ghost btn-xs" onClick={() => adminApi.approveWithdrawal(w.id).then(load)}>{t('common.approve')}</button>
                          <button className="btn btn-primary btn-xs" onClick={() => completeWd(w.id)}>{t('admin.completePayout')}</button>
                          <button className="btn btn-ghost btn-xs" onClick={() => adminApi.rejectWithdrawal(w.id).then(load)}>{t('common.reject')}</button>
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

      {tab === 'system' && (
        <>
          <div className="stat-grid">
            <StatCard label={t('admin.onlineUsers')} value={String(online?.recent_logins_15m || 0)} />
            <StatCard label={t('admin.activeSupervisors')} value={String(monitor?.active_supervisors || 0)} />
            <StatCard label="Redis" value={monitor?.redis_connected ? 'OK' : '—'} />
            <StatCard label={t('admin.apiLatency')} value={`${monitor?.api_latency_ms || 0}ms`} />
          </div>
          <GlassCard className="p-6" style={{ marginBottom: 24 }}>
            <h3 className="card-heading">{t('admin.auditLogs')}</h3>
            <div className="table-wrap"><table className="data-table"><thead><tr><th>{t('common.action')}</th><th>User</th><th>IP</th><th>{t('common.time')}</th></tr></thead>
              <tbody>{auditLogs.slice(0, 30).map(l => <tr key={l.id}><td>{l.action}</td><td>{l.user_id}</td><td>{l.ip_address}</td><td>{localeDate(l.created_at, locale)}</td></tr>)}</tbody></table></div>
          </GlassCard>
          <GlassCard className="p-0 table-wrap">
            <h3 className="card-heading p-6" style={{ marginBottom: 0 }}>{t('admin.allOrders')}</h3>
            <table className="data-table"><thead><tr><th>ID</th><th>User</th><th>{t('trades.side')}</th><th>{t('trades.pnl')}</th><th>{t('common.status')}</th></tr></thead>
              <tbody>{orders.slice(0, 50).map(o => <tr key={o.id}><td>{o.id}</td><td>{o.user_id}</td><td>{o.side}</td><td>{o.realized_pnl}</td><td>{o.status}</td></tr>)}</tbody></table>
          </GlassCard>
        </>
      )}
    </Layout>
  )
}
