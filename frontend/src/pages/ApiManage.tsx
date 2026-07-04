import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { ShieldAlert, CheckCircle2, XCircle, RefreshCw, ListChecks } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import DualVerifyFields from '../components/DualVerifyFields'
import { authApi, settingsApi, userApi } from '../api'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'

type ApiCheckItem = {
  id: string
  ok: boolean
  hint_key?: string | null
}

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
  checks?: ApiCheckItem[]
  checks_passed?: number
  checks_total?: number
  exchange?: string
  open_orders_count?: number
  open_positions_count?: number
  hedge_mode?: boolean | null
  filed_sub_count?: number
}

const BINANCE_CHECK_IDS = [
  'connect',
  'withdraw_off',
  'futures_on',
  'can_trade',
  'balance',
  'one_way',
  'leverage',
] as const

const ALT_EXCHANGE_CHECK_IDS = ['connect', 'balance', 'can_trade', 'leverage'] as const

type AccountMode = 'master' | 'sub'

type SubAccountOption = { uid: string; label: string }

type ExchangeId = 'binance' | 'deepcoin' | 'okx' | 'gate'

/** Display order: Binance → OKX → Gate → DeepCoin */
const EXCHANGE_OPTIONS: ExchangeId[] = ['binance', 'okx', 'gate', 'deepcoin']

const EXCHANGE_LABEL_KEYS: Record<ExchangeId, string> = {
  binance: 'api.exchangeBinance',
  okx: 'api.exchangeOkx',
  gate: 'api.exchangeGate',
  deepcoin: 'api.exchangeDeepcoin',
}

const PASSPHRASE_EXCHANGES: ExchangeId[] = ['deepcoin', 'okx']

function isAltExchange(ex: string | undefined, selected?: ExchangeId): boolean {
  const id = (ex || selected || 'binance') as ExchangeId
  return id !== 'binance'
}

function needsPassphrase(ex: ExchangeId): boolean {
  return PASSPHRASE_EXCHANGES.includes(ex)
}

function normalizeExchangeFromApi(ex: string | undefined): ExchangeId {
  const val = (ex || 'binance').toLowerCase()
  if (val === 'gateio') return 'gate'
  if (val === 'deepcoin' || val === 'okx' || val === 'gate') return val
  return 'binance'
}

export default function ApiManage() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [exchange, setExchange] = useState<ExchangeId>('binance')
  const [accountMode, setAccountMode] = useState<AccountMode>('master')
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [masterApiKey, setMasterApiKey] = useState('')
  const [masterApiSecret, setMasterApiSecret] = useState('')
  const [masterPassphrase, setMasterPassphrase] = useState('')
  const [masterExchangeUid, setMasterExchangeUid] = useState('')
  const [subExchangeUid, setSubExchangeUid] = useState('')
  const [subAccounts, setSubAccounts] = useState<SubAccountOption[]>([])
  const [discoverRelaxed, setDiscoverRelaxed] = useState(false)
  const [discovering, setDiscovering] = useState(false)
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

  const requiresPassphrase = needsPassphrase(exchange)
  const masterRequiresPassphrase = needsPassphrase(exchange)

  const buildBindPayload = (email_code?: string, phone_code?: string) => {
    const base = {
      api_key: apiKey,
      api_secret: apiSecret,
      exchange,
      passphrase: passphrase || undefined,
      email_code,
      phone_code,
    }
    if (accountMode === 'sub') {
      return {
        ...base,
        account_mode: 'sub',
        master_api_key: masterApiKey,
        master_api_secret: masterApiSecret,
        master_passphrase: masterRequiresPassphrase ? masterPassphrase || undefined : undefined,
        master_exchange_uid: masterExchangeUid,
        sub_exchange_uid: subExchangeUid,
      }
    }
    return {
      ...base,
      account_mode: 'master',
      exchange_uid: masterExchangeUid || undefined,
    }
  }

  const subFieldsReady =
    !!masterApiKey &&
    !!masterApiSecret &&
    !!masterExchangeUid &&
    !!subExchangeUid &&
    (!masterRequiresPassphrase || !!masterPassphrase)

  const passphrasePlaceholder = () => {
    if (exchange === 'okx') return t('api.passphrasePhOkx')
    return t('api.passphrasePhDeepcoin')
  }

  const keyLabel = () => {
    if (exchange === 'deepcoin') return t('api.deepcoinKey')
    if (exchange === 'okx') return t('api.okxKey')
    if (exchange === 'gate') return t('api.gateKey')
    return t('api.binanceKey')
  }

  const secretLabel = () => {
    if (exchange === 'deepcoin') return t('api.deepcoinSecret')
    if (exchange === 'okx') return t('api.okxSecret')
    if (exchange === 'gate') return t('api.gateSecret')
    return t('api.binanceSecret')
  }

  const isBindReady = (v: VerifyResult | null) => {
    if (!v?.valid) return false
    if (isAltExchange(v.exchange, exchange)) {
      if (v.checks && v.checks.length > 0) {
        return v.checks.every(c => c.ok)
      }
      return v.can_trade && v.leverage_ok && v.total_balance > 0
    }
    if (v.checks && v.checks.length > 0) {
      return v.checks.every(c => c.ok)
    }
    if (v.withdraw_disabled !== true) return false
    if (!v.can_trade) return false
    if (!v.one_way_mode) return false
    if (!v.leverage_ok) return false
    if (v.enable_futures === false) return false
    return true
  }

  const bindReady = isBindReady(verify)
  const dualCodesOk = !needsDualVerify || (secEmailCode.length > 0 && secPhoneCode.length > 0)
  const canBind =
    bindReady &&
    dualCodesOk &&
    !!apiKey &&
    !!apiSecret &&
    (!requiresPassphrase || !!passphrase) &&
    (accountMode !== 'sub' || subFieldsReady)

  const handleDiscoverSubs = async () => {
    if (!masterApiKey || !masterApiSecret || (masterRequiresPassphrase && !masterPassphrase)) {
      setError(t('api.fillRequired'))
      return
    }
    setDiscovering(true)
    setError('')
    try {
      const res = await userApi.discoverSubs({
        exchange,
        master_api_key: masterApiKey,
        master_api_secret: masterApiSecret,
        master_passphrase: masterRequiresPassphrase ? masterPassphrase : undefined,
      })
      if (!res.ok) {
        setError(res.message || t('api.discoverSubsFail'))
        return
      }
      if (res.uid) setMasterExchangeUid(String(res.uid))
      setSubAccounts(res.sub_accounts || [])
      setDiscoverRelaxed(!!res.relaxed)
      toast.success(
        res.relaxed
          ? t('api.discoverSubsRelaxed')
          : t('api.discoverSubsOk', { count: String((res.sub_accounts || []).length) }),
      )
    } catch (err: any) {
      setError(err.response?.data?.detail || t('api.discoverSubsFail'))
    } finally {
      setDiscovering(false)
    }
  }

  useEffect(() => {
    userApi.apiStatus().then(res => {
      setBoundStatus(res)
      if (res.exchange) setExchange(normalizeExchangeFromApi(res.exchange))
    }).catch(() => {})
    authApi.me().then(p => {
      setProfile(p)
      if (p.exchange) setExchange(normalizeExchangeFromApi(p.exchange))
      if (p.api_account_mode === 'sub') setAccountMode('sub')
    }).catch(() => {})
    settingsApi.get().then(p => setTotpEnabled(!!p.totp_enabled)).catch(() => {})
  }, [])

  const checkLabel = (id: string) => {
    const labels: Record<string, string> = {
      connect: t('api.checkConnect'),
      withdraw_off: t('api.checkWithdrawOff'),
      futures_on: t('api.checkFuturesOn'),
      can_trade: t('api.checkCanTrade'),
      balance: t('api.checkBalance'),
      one_way: t('api.checkOneWay'),
      leverage: t('api.checkLeverage'),
    }
    return labels[id] || id
  }

  const checkHint = (item: ApiCheckItem) => {
    if (item.ok) return null
    const byKey: Record<string, string> = {
      'api.hint.connect': t('api.hintConnect'),
      'api.hint.withdraw_off': t('api.hintWithdrawOff'),
      'api.hint.futures_on': t('api.hintFuturesOn'),
      'api.hint.can_trade': t('api.hintCanTrade'),
      'api.hint.balance': t('api.hintBalance'),
      'api.hint.one_way_need_flat': t('api.hintOneWayNeedFlat'),
      'api.hint.one_way_manual': t('api.hintOneWayManual'),
      'api.hint.one_way_failed': t('api.hintOneWayFailed'),
      'api.hint.leverage': t('api.hintLeverage'),
    }
    if (item.hint_key && byKey[item.hint_key]) return byKey[item.hint_key]
    const fallback: Record<string, string> = {
      connect: t('api.hintConnect'),
      withdraw_off: t('api.hintWithdrawOff'),
      futures_on: t('api.hintFuturesOn'),
      can_trade: t('api.hintCanTrade'),
      balance: t('api.hintBalance'),
      one_way: t('api.hintOneWayFailed'),
      leverage: t('api.hintLeverage'),
    }
    return fallback[item.id] || null
  }

  const handleVerify = async () => {
    if (accountMode === 'sub') {
      if (!subFieldsReady || !apiKey || !apiSecret || (requiresPassphrase && !passphrase)) {
        setError(t('api.fillRequired'))
        return
      }
    } else if (!apiKey || !apiSecret || (requiresPassphrase && !passphrase)) {
      setError(t('api.fillRequired'))
      return
    }
    setChecking(true)
    setError('')
    setVerify(null)
    try {
      const res = await userApi.verifyApi(buildBindPayload())
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
        const res = await userApi.verifyApi(buildBindPayload())
        setVerify(res)
        if (!isBindReady(res)) {
          setError(res.message || t('api.bindBlockedHint'))
          return
        }
      }
      const res = await userApi.bindApi(
        buildBindPayload(
          needsDualVerify ? secEmailCode : undefined,
          needsDualVerify ? secPhoneCode : undefined,
        ),
      )
      toast.success(res.message || t('api.bindSuccessMsg', { amount: `$${res.initial_principal?.toFixed(2)}` }))
      const snapshot = await userApi.apiStatus()
      setBoundStatus(snapshot)
      setApiKey('')
      setApiSecret('')
      setPassphrase('')
      setMasterApiKey('')
      setMasterApiSecret('')
      setMasterPassphrase('')
      setMasterExchangeUid('')
      setSubExchangeUid('')
      setSubAccounts([])
      setVerify(null)
      setSecEmailCode('')
      setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('api.bindFail'))
    } finally {
      setLoading(false)
    }
  }

  const renderChecklist = (v: VerifyResult) => {
    const checkIds = isAltExchange(v.exchange, exchange) ? ALT_EXCHANGE_CHECK_IDS : BINANCE_CHECK_IDS
    const items = v.checks?.length
      ? v.checks
      : checkIds.map(id => ({
          id,
          ok:
            (id === 'connect' && true) ||
            (id === 'withdraw_off' && v.withdraw_disabled === true) ||
            (id === 'futures_on' && v.enable_futures !== false && v.can_trade) ||
            (id === 'can_trade' && v.can_trade) ||
            (id === 'balance' && v.total_balance > 0) ||
            (id === 'one_way' && v.one_way_mode) ||
            (id === 'leverage' && v.leverage_ok),
        }))
    const passed = v.checks_passed ?? items.filter(i => i.ok).length
    const total = v.checks_total ?? items.length

    return (
      <div className="api-checklist">
        <div className="api-checklist-head">
          <ListChecks size={18} />
          <span>{t('api.checkListTitle')}</span>
          <span className={`api-checklist-score ${v.valid ? 'ok' : 'fail'}`}>
            {t('api.checkSummary', { passed, total })}
          </span>
        </div>
        <ul className="api-checklist-items">
          {items.map(item => (
            <li key={item.id} className={item.ok ? 'check-ok' : 'check-fail'}>
              <span className="api-check-icon">{item.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}</span>
              <div className="api-check-body">
                <span className="api-check-label">{checkLabel(item.id)}</span>
                {!item.ok && checkHint(item) && (
                  <p className="api-check-hint">{checkHint(item)}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
        {(v.open_orders_count ?? 0) > 0 || (v.open_positions_count ?? 0) > 0 ? (
          <p className="api-activity-note text-muted">
            {t('api.activityNote', {
              orders: v.open_orders_count ?? 0,
              positions: v.open_positions_count ?? 0,
            })}
          </p>
        ) : null}
        <p className={`api-checklist-footer ${v.valid ? 'ok' : 'fail'}`}>
          {v.valid ? t('api.allChecksPass') : t('api.checksPending')}
        </p>
        {(v as VerifyResult).filed_sub_count != null && (v as VerifyResult).filed_sub_count! > 0 && (
          <p className="text-muted text-sm section-mt-sm">
            {t('api.filedSubCount', { count: String((v as VerifyResult).filed_sub_count) })}
          </p>
        )}
      </div>
    )
  }

  const renderVerifyPanel = (v: VerifyResult, title: string) => (
    <div className={`verify-panel ${v.valid ? 'verify-ok' : 'verify-fail'}`}>
      <p className="verify-panel-title">{title}</p>
      <p className="verify-panel-msg">{v.message}</p>
      {renderChecklist(v)}
      <div className="verify-grid">
        <div><span className="text-muted">{t('api.futuresEquity')}</span><br />${v.total_balance.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.availableBalance')}</span><br />${v.available_balance.toFixed(2)}</div>
        <div><span className="text-muted">{t('api.unrealizedPnl')}</span><br />${v.unrealized_pnl.toFixed(2)}</div>
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
          {exchange === 'deepcoin' ? (
            <>
              {t('api.introDeepcoin1')}
              <strong>{t('api.introDeepcoin')}</strong>
              {t('api.introDeepcoin2')}
            </>
          ) : exchange === 'okx' ? (
            <>
              {t('api.introDeepcoin1')}
              <strong>{t('api.introOkx')}</strong>
              {t('api.introOkx2')}
            </>
          ) : exchange === 'gate' ? (
            <>
              {t('api.intro1')}
              <strong>{t('api.introGate')}</strong>
              {t('api.introGate2')}
            </>
          ) : (
            <>
              {t('api.intro1')}
              <strong>{t('api.introBinance')}</strong>
              {t('api.intro2')}
              <strong>{t('api.intro3')}</strong>
              {t('api.intro4')}
            </>
          )}
        </p>

        <div className="api-prep-guide">
          <h3 className="api-prep-title">{t('api.prepTitle')}</h3>
          <p className="text-muted api-prep-intro">{t('api.prepIntro')}</p>
          <ol className="api-prep-steps">
            <li>
              <strong>{t('api.prepStep1Title')}</strong>
              <p>{t('api.prepStep1Body')}</p>
            </li>
            <li>
              <strong>{t('api.prepStep2Title')}</strong>
              <p>{t('api.prepStep2Body')}</p>
            </li>
            <li>
              <strong>{t('api.prepStep3Title')}</strong>
              <p>{t('api.prepStep3Body')}</p>
            </li>
            <li>
              <strong>{t('api.prepStep4Title')}</strong>
              <p>{t('api.prepStep4Body')}</p>
            </li>
          </ol>
        </div>

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
        {boundStatus && (
          <>
            {profile?.api_account_mode === 'sub' && profile?.master_exchange_uid && (
              <p className="text-muted text-sm section-mb-sm">
                {t('api.boundModeSub', { master: profile.master_exchange_uid })}
                {profile.exchange_uid ? ` · ${t('api.boundExchangeUid')}: ${profile.exchange_uid}` : ''}
              </p>
            )}
            {profile?.api_account_mode !== 'sub' && profile?.exchange_uid && (
              <p className="text-muted text-sm section-mb-sm">
                {t('api.boundModeMaster')} · {t('api.boundExchangeUid')}: {profile.exchange_uid}
              </p>
            )}
            {renderVerifyPanel(boundStatus, t('api.boundStatusTitle'))}
          </>
        )}

        <form onSubmit={handleBind}>
          <div className="form-field">
            <label className="form-label">{t('api.exchangeLabel')}</label>
            <select
              className="input"
              value={exchange}
              onChange={e => {
                setExchange(normalizeExchangeFromApi(e.target.value))
                setVerify(null)
                setError('')
                setPassphrase('')
                setSubAccounts([])
                setDiscoverRelaxed(false)
              }}
            >
              {EXCHANGE_OPTIONS.map(id => (
                <option key={id} value={id}>{t(EXCHANGE_LABEL_KEYS[id])}</option>
              ))}
            </select>
          </div>

          <div className="form-field">
            <label className="form-label">{t('api.accountModeLabel')}</label>
            <select
              className="input"
              value={accountMode}
              onChange={e => {
                setAccountMode(e.target.value as AccountMode)
                setVerify(null)
                setError('')
              }}
            >
              <option value="master">{t('api.accountModeMaster')}</option>
              <option value="sub">{t('api.accountModeSub')}</option>
            </select>
            <p className="text-muted form-hint-sm section-mt-sm">
              {accountMode === 'sub' ? t('api.accountModeSubHint') : t('api.accountModeMasterHint')}
            </p>
          </div>

          {accountMode === 'sub' && (
            <GlassCard className="p-4 section-mb-sm api-mode-guide">
              <h4 className="card-heading text-sm">{t('api.subModeGuideTitle')}</h4>
              <ol className="api-prep-steps text-sm">
                <li><strong>{t('api.subModeStep1Title')}</strong><p>{t('api.subModeStep1Body')}</p></li>
                <li><strong>{t('api.subModeStep2Title')}</strong><p>{t('api.subModeStep2Body')}</p></li>
                <li><strong>{t('api.subModeStep3Title')}</strong><p>{t('api.subModeStep3Body')}</p></li>
              </ol>
            </GlassCard>
          )}

          {accountMode === 'master' && (
            <GlassCard className="p-4 section-mb-sm api-mode-guide">
              <h4 className="card-heading text-sm">{t('api.masterFilingTitle')}</h4>
              <p className="text-muted text-sm section-mb-sm">{t('api.masterFilingHint')}</p>
              <ol className="api-prep-steps text-sm">
                <li><strong>{t('api.masterGuideStep1Title')}</strong><p>{t('api.masterGuideStep1Body')}</p></li>
                <li><strong>{t('api.masterGuideStep2Title')}</strong><p>{t('api.masterGuideStep2Body')}</p></li>
                <li><strong>{t('api.masterGuideStep3Title')}</strong><p>{t('api.masterGuideStep3Body')}</p></li>
              </ol>
            </GlassCard>
          )}

          {accountMode === 'sub' && (
            <GlassCard className="p-4 section-mb-sm">
              <h4 className="card-heading text-sm">{t('api.masterSectionTitle')}</h4>
              <p className="text-muted text-sm section-mb-sm">{t('api.masterSectionHint')}</p>
              <div className="form-field">
                <label className="form-label">{t('api.masterKey')}</label>
                <input className="input" value={masterApiKey} onChange={e => setMasterApiKey(e.target.value)} placeholder={t('api.keyPh')} />
              </div>
              <div className="form-field">
                <label className="form-label">{t('api.masterSecret')}</label>
                <input className="input" type="password" value={masterApiSecret} onChange={e => setMasterApiSecret(e.target.value)} placeholder={t('api.secretPh')} />
              </div>
              {masterRequiresPassphrase && (
                <div className="form-field">
                  <label className="form-label">{t('api.masterPassphrase')}</label>
                  <input className="input" type="password" value={masterPassphrase} onChange={e => setMasterPassphrase(e.target.value)} placeholder={passphrasePlaceholder()} />
                </div>
              )}
              <div className="form-field">
                <label className="form-label">{t('api.masterUidLabel')}</label>
                <input className="input" value={masterExchangeUid} onChange={e => setMasterExchangeUid(e.target.value)} placeholder={t('api.masterUidPh')} />
                <p className="text-muted form-hint-sm">{t('api.masterUidHintSub')}</p>
              </div>
              <div className="api-actions">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={discovering || !masterApiKey || !masterApiSecret || (masterRequiresPassphrase && !masterPassphrase)}
                  onClick={handleDiscoverSubs}
                >
                  {discovering ? t('api.discoveringSubs') : t('api.discoverSubs')}
                </button>
              </div>
              {discoverRelaxed && (
                <p className="text-muted form-hint-sm">{t('api.discoverSubsRelaxed')}</p>
              )}
            </GlassCard>
          )}

          <GlassCard className={`p-4 ${accountMode === 'sub' ? 'section-mb-sm' : ''}`}>
            {accountMode === 'sub' && (
              <>
                <h4 className="card-heading text-sm">{t('api.subSectionTitle')}</h4>
                <p className="text-muted text-sm section-mb-sm">{t('api.subSectionHint')}</p>
              </>
            )}
            <div className="form-field">
              <label className="form-label">{accountMode === 'sub' ? t('api.subSectionTitle') + ' · ' + keyLabel() : keyLabel()}</label>
              <input className="input" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={t('api.keyPh')} required />
            </div>
            <div className="form-field">
              <label className="form-label">{secretLabel()}</label>
              <input className="input" type="password" value={apiSecret} onChange={e => setApiSecret(e.target.value)} placeholder={t('api.secretPh')} required />
            </div>
            {requiresPassphrase && (
              <div className="form-field">
                <label className="form-label">{t('api.passphraseLabel')}</label>
                <input className="input" type="password" value={passphrase} onChange={e => setPassphrase(e.target.value)} placeholder={passphrasePlaceholder()} required />
              </div>
            )}
            {accountMode === 'sub' && (
              <div className="form-field">
                <label className="form-label">{t('api.subUidLabel')}</label>
                {subAccounts.length > 0 ? (
                  <select className="input" value={subExchangeUid} onChange={e => setSubExchangeUid(e.target.value)}>
                    <option value="">{t('api.subUidPh')}</option>
                    {subAccounts.map(s => (
                      <option key={s.uid} value={s.uid}>{s.label} ({s.uid})</option>
                    ))}
                  </select>
                ) : (
                  <input className="input" value={subExchangeUid} onChange={e => setSubExchangeUid(e.target.value)} placeholder={t('api.subUidPh')} />
                )}
              </div>
            )}
            {accountMode === 'master' && (
              <div className="form-field">
                <label className="form-label">{t('api.masterUidLabel')}</label>
                <input className="input" value={masterExchangeUid} onChange={e => setMasterExchangeUid(e.target.value)} placeholder={t('api.masterUidPh')} />
                <p className="text-muted form-hint-sm">{t('api.masterUidHintMaster')}</p>
              </div>
            )}
          </GlassCard>

          <div className="api-actions">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={
                checking ||
                (accountMode === 'sub' ? !subFieldsReady || !apiKey || !apiSecret || (requiresPassphrase && !passphrase) : !apiKey || !apiSecret || (requiresPassphrase && !passphrase))
              }
              onClick={handleVerify}
            >
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
