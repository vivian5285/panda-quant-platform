import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { ShieldAlert, CheckCircle2, XCircle, RefreshCw } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import DualVerifyFields from '../components/DualVerifyFields'
import { authApi, settingsApi, userApi } from '../api'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'

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
  withdraw_disabled?: boolean | null
  enable_futures?: boolean | null
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
  const [profile, setProfile] = useState<any>(null)
  const [totpEnabled, setTotpEnabled] = useState<boolean | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(false)
  const [secEmailCode, setSecEmailCode] = useState('')
  const [secPhoneCode, setSecPhoneCode] = useState('')
  const [devEmail, setDevEmail] = useState('')
  const [devPhone, setDevPhone] = useState('')

  const needsDualVerify = profile?.has_email && profile?.has_phone

  const isBindReady = (v: VerifyResult | null) => {
    if (!v?.valid) return false
    if (v.withdraw_disabled !== true) return false
    if (!v.can_trade) return false
    if (!v.one_way_mode) return false
    if (!v.leverage_ok) return false
    if (v.enable_futures === false) return false
    return true
  }

  const bindReady = isBindReady(verify)
  const dualCodesOk = !needsDualVerify || (secEmailCode.length > 0 && secPhoneCode.length > 0)
  const canBind = bindReady && dualCodesOk && !!apiKey && !!apiSecret

  useEffect(() => {
    userApi.apiStatus().then(setBoundStatus).catch(() => {})
    authApi.me().then(setProfile).catch(() => {})
    settingsApi.get().then(p => setTotpEnabled(!!p.totp_enabled)).catch(() => {})
  }, [])

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
    setError('')
    try {
      if (!verify?.valid || !isBindReady(verify)) {
        const res = await userApi.verifyApi(apiKey, apiSecret)
        setVerify(res)
        if (!isBindReady(res)) {
          setError(res.message || t('api.bindBlockedHint'))
          return
        }
      }
      const res = await userApi.bindApi(
        apiKey,
        apiSecret,
        needsDualVerify ? secEmailCode : undefined,
        needsDualVerify ? secPhoneCode : undefined,
      )
      toast.success(res.message || t('api.bindSuccessMsg', { amount: `$${res.initial_principal?.toFixed(2)}` }))
      const snapshot = await userApi.apiStatus()
      setBoundStatus(snapshot)
      setApiKey('')
      setApiSecret('')
      setVerify(null)
      setSecEmailCode('')
      setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('api.bindFail'))
    } finally {
      setLoading(false)
    }
  }

  const flag = (ok: boolean | null | undefined) => {
    if (ok === null || ok === undefined) return '—'
    return ok ? '✓' : '✗'
  }

  const renderVerifyPanel = (v: VerifyResult, title: string) => (
    <div className={`verify-panel ${v.valid ? 'verify-ok' : 'verify-fail'}`}>
      <p className="verify-panel-title">{title}</p>
      <p className="verify-panel-msg">{v.message}</p>
      <div className="verify-grid">
        <div><span className="text-muted">{t('api.futuresEquity')}</span><br />${v.total_balance.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.availableBalance')}</span><br />${v.available_balance.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.unrealizedPnl')}</span><br />${v.unrealized_pnl.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.tradePermission')}</span><br />{v.can_trade ? '✓' : '✗'}</div>
        <div><span className="text-muted">{t('api.withdrawDisabled')}</span><br />{flag(v.withdraw_disabled)}</div>
        <div><span className="text-muted">{t('api.futuresFlag')}</span><br />{flag(v.enable_futures ?? v.can_trade)}</div>
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
      <div className="api-danger-banner">
        <ShieldAlert size={20} />
        <div>
          <strong>{t('api.securityTitle')}</strong>
          <p>{t('api.sec1Highlight')}{t('api.sec1Detail')} · {t('api.sec2Warn')}{t('api.sec2Detail')}</p>
        </div>
      </div>

      {totpEnabled === false && (
        <div className="api-welcome-banner">
          <ShieldAlert size={18} />
          <div>
            <strong>{t('api.totpRecommend')}</strong>
            <p>{t('profile.totpRecommendDesc')} · <Link to="/profile">{t('api.totpRecommendLink')}</Link></p>
          </div>
        </div>
      )}

      <GlassCard className="p-8 api-page-panel" key={locale}>
        <p className="text-secondary api-intro">
          {t('api.intro1')}
          <strong>{t('api.introBinance')}</strong>
          {t('api.intro2')}
          <strong>{t('api.intro3')}</strong>
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

        <div className="api-actions">
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

          <div className="api-actions">
            <button type="button" className="btn btn-secondary" disabled={checking || !apiKey || !apiSecret} onClick={handleVerify}>
              {checking ? t('api.verifying') : t('api.verify')}
            </button>
          </div>

          {verify && renderVerifyPanel(verify, t('api.verifyResultTitle'))}

          {needsDualVerify && (
            <GlassCard className="p-4 api-bind-security">
              <p className="text-muted form-hint-sm">{t('api.bindSecurityHint')}</p>
              <DualVerifyFields
                emailCode={secEmailCode}
                phoneCode={secPhoneCode}
                onEmailCode={setSecEmailCode}
                onPhoneCode={setSecPhoneCode}
                devEmail={devEmail}
                devPhone={devPhone}
                onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
              />
            </GlassCard>
          )}

          {verify && !bindReady && (
            <p className="form-error form-hint-sm">{t('api.bindBlockedHint')}</p>
          )}

          {error && <p className="form-error">{error}</p>}
          <button className="btn btn-primary" disabled={loading || checking || !canBind}>
            {loading ? t('api.binding') : t('api.bind')}
          </button>
        </form>
      </GlassCard>

      {boundStatus?.valid && (
        <GlassCard className="p-6 section-mt-lg">
          <h3 className="card-heading">{t('api.unbindTitle')}</h3>
          <p className="text-muted text-sm section-mb-sm">{t('api.unbindHint')}</p>
          {needsDualVerify && (
            <DualVerifyFields
              emailCode={secEmailCode}
              phoneCode={secPhoneCode}
              onEmailCode={setSecEmailCode}
              onPhoneCode={setSecPhoneCode}
              devEmail={devEmail}
              devPhone={devPhone}
              onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
            />
          )}
          <button className="btn btn-danger section-mt-sm" type="button" disabled={loading || (needsDualVerify && (!secEmailCode || !secPhoneCode))}
            onClick={async () => {
              setLoading(true)
              try {
                await userApi.unbindApi(secEmailCode, secPhoneCode)
                toast.success(t('api.unbindSuccess'))
                setBoundStatus(null)
                setVerify(null)
              } catch (err: any) {
                toast.error(err.response?.data?.detail || t('api.unbindFail'))
              } finally {
                setLoading(false)
              }
            }}>
            {t('api.unbindBtn')}
          </button>
        </GlassCard>
      )}
    </Layout>
  )
}
