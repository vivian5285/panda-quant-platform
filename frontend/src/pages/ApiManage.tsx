import { useState } from 'react'
import { ShieldAlert, CheckCircle2, XCircle, RefreshCw } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'
import { useI18n } from '../i18n'

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
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
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
      setError(t('api.fillRequired'))
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
      setError(err.response?.data?.detail || t('api.verifyFail'))
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
      setError(err.response?.data?.detail || t('api.recheckFail'))
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
      setMsg(res.message || t('api.bindSuccessMsg', { amount: `$${res.initial_principal?.toFixed(2)}` }))
      setApiKey('')
      setApiSecret('')
      setVerify(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || t('api.bindFail'))
    } finally {
      setLoading(false)
    }
  }

  const renderVerifyPanel = (v: VerifyResult, title: string) => (
    <div className={`verify-panel ${v.valid ? 'verify-ok' : 'verify-fail'}`} style={{ marginBottom: 20 }}>
      <p style={{ fontWeight: 600, marginBottom: 8 }}>{title}</p>
      <p style={{ fontSize: 13, marginBottom: 12 }}>{v.message}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, fontSize: 13 }}>
        <div><span className="text-muted">{t('api.futuresEquity')}</span><br />${v.total_balance.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.availableBalance')}</span><br />${v.available_balance.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.unrealizedPnl')}</span><br />${v.unrealized_pnl.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.tradePermission')}</span><br />{v.can_trade ? '✓' : '✗'}</div>
        <div><span className="text-muted">{t('api.oneWayMode')}</span><br />{v.one_way_mode ? '✓' : '✗'}</div>
        <div><span className="text-muted">{t('api.leverage')} {v.leverage}x</span><br />{v.leverage_ok ? '✓' : '✗'}</div>
        {v.initial_principal > 0 && (
          <div><span className="text-muted">{t('api.initialPrincipal')}</span><br />${v.initial_principal.toFixed(2)}</div>
        )}
      </div>
    </div>
  )

  return (
    <Layout>
      <PageHeader title={t('api.title')} />
      <GlassCard green className="p-8" style={{ maxWidth: 560 }} key={locale}>
        <p className="text-secondary" style={{ fontSize: 14, marginBottom: 20, lineHeight: 1.6 }}>
          {t('api.intro1')}
          <strong className="text-green">{t('api.introBinance')}</strong>
          {t('api.intro2')}
          <strong className="text-green">{t('api.intro3')}</strong>
          {t('api.intro4')}
        </p>

        <div className="security-notice">
          <div className="security-notice-title">
            <ShieldAlert size={18} />
            {t('api.securityTitle')}
          </div>
          <ul className="security-notice-list">
            <li>
              <CheckCircle2 size={16} className="icon-ok" />
              <span>
                <span className="security-notice-highlight">{t('api.sec1Highlight')}</span>
                <span className="text-secondary">{t('api.sec1Detail')}</span>
              </span>
            </li>
            <li>
              <XCircle size={16} className="icon-no" />
              <span>
                <span className="security-notice-warn">{t('api.sec2Warn')}</span>
                <span className="text-secondary">{t('api.sec2Detail')}</span>
                <span className="security-notice-warn">{t('api.sec2Warn2')}</span>
              </span>
            </li>
            <li>
              <CheckCircle2 size={16} className="icon-ok" />
              <span className="text-secondary">{t('api.sec3')}</span>
            </li>
          </ul>
        </div>

        <div style={{ marginBottom: 16 }}>
          <button type="button" className="btn btn-secondary" disabled={checking} onClick={handleCheckBound}>
            <RefreshCw size={14} />
            {checking ? t('api.checking') : t('api.recheckBound')}
          </button>
        </div>
        {boundStatus && renderVerifyPanel(boundStatus, t('api.boundStatusTitle'))}

        <form onSubmit={handleBind}>
          <div className="form-field">
            <label className="form-label">{t('api.binanceKey')}</label>
            <input className="input" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={t('api.keyPh')} required />
          </div>
          <div className="form-field">
            <label className="form-label">{t('api.binanceSecret')}</label>
            <input className="input" type="password" value={apiSecret} onChange={e => setApiSecret(e.target.value)} placeholder={t('api.secretPh')} required />
          </div>

          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            <button type="button" className="btn btn-secondary" disabled={checking || !apiKey || !apiSecret} onClick={handleVerify}>
              {checking ? t('api.verifying') : t('api.verify')}
            </button>
          </div>

          {verify && renderVerifyPanel(verify, t('api.verifyResultTitle'))}

          {msg && <div className="flash-msg">{msg}</div>}
          {error && <p className="form-error">{error}</p>}
          <button className="btn btn-primary" disabled={loading || checking}>
            {loading ? t('api.binding') : t('api.bind')}
          </button>
        </form>
      </GlassCard>
    </Layout>
  )
}
