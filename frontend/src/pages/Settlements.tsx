import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { referralApi, walletApi } from '../api'
import { useI18n } from '../i18n'
import { Copy, Check } from 'lucide-react'

export default function Settlements() {
  const { t } = useI18n()
  const [items, setItems] = useState<any[]>([])
  const [addresses, setAddresses] = useState<any[]>([])
  const [payingId, setPayingId] = useState<number | null>(null)
  const [chain, setChain] = useState('TRC20')
  const [txHash, setTxHash] = useState('')
  const [amount, setAmount] = useState('')
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState('')

  const load = () => {
    referralApi.settlements().then(setItems)
    walletApi.depositAddresses().then(setAddresses)
  }

  useEffect(() => { load() }, [])

  const copyAddr = (addr: string, key: string) => {
    navigator.clipboard.writeText(addr)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const submitPay = async (id: number, payable: number) => {
    setError('')
    setMsg('')
    try {
      await walletApi.paySettlement(id, chain, txHash, parseFloat(amount) || payable)
      setMsg('支付凭证已提交，等待平台确认')
      setPayingId(null)
      setTxHash('')
      setAmount('')
      load()
    } catch (err: any) {
      setError(err.response?.data?.detail || '提交失败')
    }
  }

  const statusLabel = (s: string) => t(`settlements.status.${s}`) || s

  return (
    <Layout>
      <PageHeader title={t('settlements.title')} subtitle={t('settlements.subtitle')} />

      <GlassCard green className="p-6" style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 500, marginBottom: 16 }}>平台 USDT 收款地址</h3>
        {addresses.length === 0 ? (
          <p className="text-muted">管理员尚未配置收款地址</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {addresses.map(a => (
              <div key={a.id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                flexWrap: 'wrap', gap: 12, padding: '12px 16px',
                background: 'rgba(255,255,255,0.03)', borderRadius: 10,
              }}>
                <div>
                  <span className="badge badge-green">{a.chain}</span>
                  {a.label && <span className="text-muted" style={{ marginLeft: 8, fontSize: 12 }}>{a.label}</span>}
                  <p style={{ fontSize: 13, marginTop: 8, wordBreak: 'break-all', fontFamily: 'monospace' }}>{a.address}</p>
                </div>
                <button className="btn btn-ghost" onClick={() => copyAddr(a.address, String(a.id))}>
                  {copied === String(a.id) ? <Check size={14} /> : <Copy size={14} />}
                  {copied === String(a.id) ? '已复制' : '复制'}
                </button>
              </div>
            ))}
          </div>
        )}
      </GlassCard>

      {msg && <p className="text-green" style={{ marginBottom: 16 }}>{msg}</p>}
      {error && <p className="text-red" style={{ marginBottom: 16 }}>{error}</p>}

      <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
        <table className="data-table">
          <thead>
            <tr>
              <th>周期</th><th>天数</th><th>净盈利</th><th>平台分成</th><th>应付</th><th>状态</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={7} className="text-muted" style={{ textAlign: 'center', padding: 40 }}>暂无结算记录</td></tr>
            ) : items.map(s => (
              <tr key={s.id}>
                <td>{s.period_start} ~ {s.period_end}</td>
                <td><span className="badge badge-gray">{s.cycle_days || 7}天</span></td>
                <td className="text-green">${s.net_profit?.toFixed(2)}</td>
                <td>${s.platform_fee?.toFixed(2)}</td>
                <td>${s.user_payable?.toFixed(2)}</td>
                <td>
                  <span className={`badge ${s.payment_status === 'confirmed' ? 'badge-green' : 'badge-gray'}`}>
                    {statusLabel(s.payment_status)}
                  </span>
                </td>
                <td>
                  {s.payment_status === 'pending' && (
                    <button className="btn btn-ghost" style={{ padding: '4px 12px', fontSize: 12 }}
                      onClick={() => { setPayingId(s.id); setAmount(String(s.user_payable)) }}>
                      提交支付
                    </button>
                  )}
                  {s.payment_tx_hash && (
                    <span className="text-muted" style={{ fontSize: 11 }} title={s.payment_tx_hash}>
                      {s.payment_chain} · {s.payment_tx_hash.slice(0, 8)}...
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      {payingId && (
        <GlassCard green className="p-6" style={{ marginTop: 24, maxWidth: 480 }}>
          <h3 style={{ fontSize: 15, marginBottom: 16 }}>提交 USDT 支付凭证</h3>
          <div style={{ marginBottom: 12 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>公链</label>
            <select className="input" value={chain} onChange={e => setChain(e.target.value)}>
              {['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL'].map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: 12 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>转账金额 (USDT)</label>
            <input className="input" type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>交易哈希 TxHash</label>
            <input className="input" value={txHash} onChange={e => setTxHash(e.target.value)} placeholder="0x..." required />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary" onClick={() => submitPay(payingId, parseFloat(amount))}>确认提交</button>
            <button className="btn btn-ghost" onClick={() => setPayingId(null)}>取消</button>
          </div>
        </GlassCard>
      )}
    </Layout>
  )
}
