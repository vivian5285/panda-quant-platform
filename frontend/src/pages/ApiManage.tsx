import { useState } from 'react'
import { ShieldAlert, CheckCircle2, XCircle, RefreshCw } from 'lucide-react'
import Layout from '../components/Layout'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'

type VerifyResult = {
  valid: boolean
  message: string
  total_balance: number
  available_balance: number
  wallet_balance: number
  unrealized_pnl: number
  can_trade: boolean
  one_way_mode: boolean
  leverage_ok: boolean
  symbol: string
  symbol_price: number
  leverage: number
  initial_principal: number
  detail?: string
}

export default function ApiManage() {
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [verify, setVerify] = useState<VerifyResult | null>(null)
  const [boundStatus, setBoundStatus] = useState<VerifyResult | null>(null)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(false)

  const handleVerify = async () => {
    if (!apiKey || !apiSecret) {
      setError('请先填写 API Key 和 Secret')
      return
    }
    setChecking(true)
    setError('')
    setVerify(null)
    try {
      const res = await userApi.verifyApi(apiKey, apiSecret)
      setVerify(res)
      if (!res.valid) setError(res.message)
    } catch (err: any) {
      setError(err.response?.data?.detail || '验证失败')
    } finally {
      setChecking(false)
    }
  }

  const handleCheckBound = async () => {
    setChecking(true)
    setError('')
    try {
      const res = await userApi.apiStatus()
      setBoundStatus(res)
      if (!res.valid) setError(res.message)
    } catch (err: any) {
      setError(err.response?.data?.detail || '复查失败')
    } finally {
      setChecking(false)
    }
  }

  const handleBind = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setMsg('')
    setError('')
    try {
      if (!verify?.valid) {
        const res = await userApi.verifyApi(apiKey, apiSecret)
        setVerify(res)
        if (!res.valid) {
          setError(res.message)
          return
        }
      }
      const res = await userApi.bindApi(apiKey, apiSecret)
      setMsg(res.message || `币安 API 绑定成功 · 初始本金 $${res.initial_principal?.toFixed(2)}`)
      setApiKey('')
      setApiSecret('')
      setVerify(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || '绑定失败')
    } finally {
      setLoading(false)
    }
  }

  const renderVerifyPanel = (v: VerifyResult, title: string) => (
    <div className={`verify-panel ${v.valid ? 'verify-ok' : 'verify-fail'}`} style={{ marginBottom: 20 }}>
      <p style={{ fontWeight: 600, marginBottom: 8 }}>{title}</p>
      <p style={{ fontSize: 13, marginBottom: 12 }}>{v.message}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, fontSize: 13 }}>
        <div><span className="text-muted">合约权益</span><br />${v.total_balance.toFixed(2)}</div>
        <div><span className="text-muted">可用余额</span><br />${v.available_balance.toFixed(2)}</div>
        <div><span className="text-muted">未实现盈亏</span><br />${v.unrealized_pnl.toFixed(2)}</div>
        <div><span className="text-muted">交易权限</span><br />{v.can_trade ? '✓' : '✗'}</div>
        <div><span className="text-muted">单向持仓</span><br />{v.one_way_mode ? '✓' : '✗'}</div>
        <div><span className="text-muted">杠杆 {v.leverage}x</span><br />{v.leverage_ok ? '✓' : '✗'}</div>
        {v.initial_principal > 0 && (
          <div><span className="text-muted">初始本金</span><br />${v.initial_principal.toFixed(2)}</div>
        )}
      </div>
    </div>
  )

  return (
    <Layout>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>API 管理</h1>
      <GlassCard green className="p-8" style={{ maxWidth: 560 }}>
        <p className="text-secondary" style={{ fontSize: 14, marginBottom: 20, lineHeight: 1.6 }}>
          请填写您在<strong className="text-green"> 币安（Binance）交易所 </strong>创建的 API Key，用于 U 本位合约自动跟单。
          绑定前会先校验连接、余额与交易权限，并<strong className="text-green"> 记载当前权益为初始本金</strong>。
        </p>

        <div className="security-notice">
          <div className="security-notice-title">
            <ShieldAlert size={18} />
            安全绑定说明（请务必遵守）
          </div>
          <ul className="security-notice-list">
            <li>
              <CheckCircle2 size={16} className="icon-ok" />
              <span>
                <span className="security-notice-highlight">必须开启：合约交易（Futures）权限</span>
                <span className="text-secondary"> — 否则无法下单，绑定会失败</span>
              </span>
            </li>
            <li>
              <XCircle size={16} className="icon-no" />
              <span>
                <span className="security-notice-warn">必须关闭：提现（Withdraw）权限</span>
                <span className="text-secondary"> — 平台只需交易权限，</span>
                <span className="security-notice-warn"> 关闭提现 = 安全提现，保护您的资金</span>
              </span>
            </li>
            <li>
              <CheckCircle2 size={16} className="icon-ok" />
              <span className="text-secondary">
                分润结算确认到账后，平台将以当时权益重新记载初始本金，开始新周期
              </span>
            </li>
          </ul>
        </div>

        <div style={{ marginBottom: 16 }}>
          <button type="button" className="btn btn-secondary" disabled={checking} onClick={handleCheckBound}>
            <RefreshCw size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
            {checking ? '检查中...' : '复查已绑定 API'}
          </button>
        </div>
        {boundStatus && renderVerifyPanel(boundStatus, '已绑定 API 状态')}

        <form onSubmit={handleBind}>
          <div style={{ marginBottom: 16 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
              币安 API Key
            </label>
            <input
              className="input"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="粘贴币安 API Key"
              required
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
              币安 API Secret
            </label>
            <input
              className="input"
              type="password"
              value={apiSecret}
              onChange={e => setApiSecret(e.target.value)}
              placeholder="粘贴币安 API Secret"
              required
            />
          </div>

          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            <button type="button" className="btn btn-secondary" disabled={checking || !apiKey || !apiSecret} onClick={handleVerify}>
              {checking ? '验证中...' : '先验证 API'}
            </button>
          </div>

          {verify && renderVerifyPanel(verify, '验证结果')}

          {msg && <p className="text-green" style={{ fontSize: 13, marginBottom: 12 }}>{msg}</p>}
          {error && <p className="text-red" style={{ fontSize: 13, marginBottom: 12 }}>{error}</p>}
          <button className="btn btn-primary" disabled={loading || checking}>
            {loading ? '绑定中...' : '确认绑定'}
          </button>
        </form>
      </GlassCard>
    </Layout>
  )
}
