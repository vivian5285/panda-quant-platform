import { useEffect, useState } from 'react'
import { Copy, Check } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import DualVerifyFields from '../components/DualVerifyFields'
import LanguageSwitcher from '../components/LanguageSwitcher'
import ThemeToggle from '../components/ThemeToggle'
import WithdrawCta from '../components/WithdrawCta'
import { authApi, settingsApi, notificationApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'

export default function Profile() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [profile, setProfile] = useState<any>(null)
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState('')
  const { setAuth, token, uid, displayName, role } = useAuth()

  const [oldPwd, setOldPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [withdrawPwd, setWithdrawPwd] = useState('')
  const [bindEmailVal, setBindEmailVal] = useState('')
  const [bindPhoneVal, setBindPhoneVal] = useState('')
  const [bindEmailCode, setBindEmailCode] = useState('')
  const [bindPhoneCode, setBindPhoneCode] = useState('')
  const [bindOtherCode, setBindOtherCode] = useState('')
  const [secEmailCode, setSecEmailCode] = useState('')
  const [secPhoneCode, setSecPhoneCode] = useState('')
  const [devEmail, setDevEmail] = useState('')
  const [devPhone, setDevPhone] = useState('')

  const [prefs, setPrefs] = useState<any>(null)
  const [totp, setTotp] = useState<any>(null)
  const [totpCode, setTotpCode] = useState('')
  const [disableTotpCode, setDisableTotpCode] = useState('')
  const [apiKeys, setApiKeys] = useState<any[]>([])
  const [newKey, setNewKey] = useState<string | null>(null)
  const [notifications, setNotifications] = useState<any[]>([])

  const loadSettings = () => {
    settingsApi.get().then(setPrefs).catch(() => {})
    settingsApi.apiKeys().then(setApiKeys).catch(() => {})
    notificationApi.list().then(setNotifications).catch(() => [])
  }

  useEffect(() => {
    authApi.me().then(p => {
      setProfile(p)
      setNickname(p.nickname || '')
    })
    loadSettings()
  }, [])

  const copyText = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const saveNickname = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const p = await authApi.updateNickname(nickname.trim())
      setProfile(p)
      if (token) setAuth(token, p.uid, p.display_name, role || p.role)
      toast.success(t('profile.nicknameUpdated'))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.updateFail'))
    }
  }

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const p = await authApi.changePassword(oldPwd, newPwd, secEmailCode, secPhoneCode)
      setProfile(p)
      toast.success(t('profile.pwdChanged'))
      setOldPwd(''); setNewPwd(''); setSecEmailCode(''); setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.changeFail'))
    }
  }

  const saveWithdrawPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const p = await authApi.setWithdrawPassword(withdrawPwd, secEmailCode, secPhoneCode)
      setProfile(p)
      toast.success(t('profile.withdrawPwdSet'))
      setWithdrawPwd(''); setSecEmailCode(''); setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.setFail'))
    }
  }

  const bindEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const p = await authApi.bindEmail(bindEmailVal, bindEmailCode, profile?.has_phone ? bindOtherCode : undefined)
      setProfile(p)
      toast.success(t('profile.emailBound'))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.bindFail'))
    }
  }

  const bindPhone = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const p = await authApi.bindPhone(bindPhoneVal, bindPhoneCode, profile?.has_email ? bindOtherCode : undefined)
      setProfile(p)
      toast.success(t('profile.phoneBound'))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.bindFail'))
    }
  }

  const bothBound = profile?.has_email

  const savePrefs = async () => {
    if (!prefs) return
    setError('')
    try {
      await settingsApi.update(prefs)
      toast.success(t('settings.saved'))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.updateFail'))
    }
  }

  const setup2fa = async () => {
    setError('')
    try {
      setTotp(await settingsApi.totpSetup())
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.updateFail'))
    }
  }

  const enable2fa = async () => {
    setError('')
    try {
      await settingsApi.totpEnable(totpCode)
      toast.success(t('settings.totpEnabled'))
      setTotp(null)
      setTotpCode('')
      loadSettings()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.updateFail'))
    }
  }

  const disable2fa = async () => {
    setError('')
    try {
      await settingsApi.totpDisable(disableTotpCode)
      toast.success(t('settings.totpDisabled'))
      setDisableTotpCode('')
      loadSettings()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.updateFail'))
    }
  }

  const createKey = async () => {
    setError('')
    try {
      const res = await settingsApi.createApiKey(t('settings.defaultApiKeyName'))
      setNewKey(res.key)
      loadSettings()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.updateFail'))
    }
  }

  return (
    <Layout>
      <PageHeader title={t('profile.title')} />

      <WithdrawCta />

      <div key={locale} className="profile-page">
        <GlassCard className="p-6 page-panel">
          <h3 className="card-heading">{t('profile.myUid')}</h3>
          <div className="uid-row">
            <span className="uid-display">{profile?.uid || uid || '...'}</span>
            <button className="btn btn-ghost btn-sm" onClick={() => copyText(profile?.uid || uid || '', 'uid')}>
              {copied === 'uid' ? <Check size={14} /> : <Copy size={14} />}
              {copied === 'uid' ? t('common.copied') : t('profile.copyUid')}
            </button>
          </div>
        </GlassCard>

        <GlassCard className="p-6 page-panel">
          <h3 className="card-heading">{t('profile.accountInfo')}</h3>
          <div className="account-info-grid">
            <div><span className="text-muted">{t('common.email')}</span><p>{profile?.email || t('profile.notBound')}</p></div>
            {!profile?.has_email && (
              <p className="text-muted form-hint-sm">{t('profile.bindHint')}</p>
            )}
          </div>
        </GlassCard>

        {!profile?.has_email && (
          <GlassCard className="p-6 page-panel">
            <h3 className="card-heading">{t('profile.bindEmail')}</h3>
            <form onSubmit={bindEmail} className="form-stack">
              <input className="input" type="email" placeholder={t('common.email')} value={bindEmailVal} onChange={e => setBindEmailVal(e.target.value)} required />
              <div className="form-row">
                <input className="input" placeholder={t('profile.emailCodePh')} value={bindEmailCode} onChange={e => setBindEmailCode(e.target.value)} required />
                <button type="button" className="btn btn-ghost" onClick={() => authApi.sendEmail(bindEmailVal, 'register')}>{t('common.get')}</button>
              </div>
              {profile?.has_phone && (
                <input className="input" placeholder={t('profile.existingPhoneCodePh')} value={bindOtherCode} onChange={e => setBindOtherCode(e.target.value)} />
              )}
              <button className="btn btn-primary" type="submit">{t('profile.bindEmailBtn')}</button>
            </form>
          </GlassCard>
        )}

        <GlassCard className="p-6 page-panel">
          <h3 className="card-heading">{t('profile.setNickname')}</h3>
          <form onSubmit={saveNickname} className="form-stack-lg">
            <input className="input" value={nickname} onChange={e => setNickname(e.target.value)}
              placeholder={displayName || t('profile.nicknamePh')} maxLength={32} />
            <button className="btn btn-primary" type="submit">{t('profile.saveNickname')}</button>
          </form>
        </GlassCard>

        {bothBound && (
          <GlassCard className="p-6 page-panel">
            <h3 className="card-heading">{t('profile.securitySettings')}</h3>
            <p className="text-muted form-hint-sm">{t('profile.securityHint')}</p>

            <DualVerifyFields
              emailCode={secEmailCode} phoneCode={secPhoneCode}
              onEmailCode={setSecEmailCode} onPhoneCode={setSecPhoneCode}
              devEmail={devEmail} devPhone={devPhone}
              onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
            />

            <form onSubmit={changePassword} className="form-section form-stack">
              <h4 className="form-section-title">{t('profile.changeLoginPwd')}</h4>
              <input className="input" type="password" placeholder={t('profile.oldPwdPh')} value={oldPwd} onChange={e => setOldPwd(e.target.value)} required />
              <input className="input" type="password" placeholder={t('profile.newPwdPh')} value={newPwd} onChange={e => setNewPwd(e.target.value)} required />
              <button className="btn btn-primary" type="submit">{t('profile.changePwdBtn')}</button>
            </form>

            <form onSubmit={saveWithdrawPassword} className="form-stack">
              <h4 className="form-section-title">
                {profile?.has_withdraw_password ? t('profile.changeWithdrawPwd') : t('profile.setWithdrawPwd')}
              </h4>
              <input className="input" type="password" placeholder={t('profile.withdrawPwdPh')} value={withdrawPwd} onChange={e => setWithdrawPwd(e.target.value)} required />
              <button className="btn btn-primary" type="submit">{t('profile.saveWithdrawPwd')}</button>
            </form>
          </GlassCard>
        )}

        <GlassCard className="p-6 page-panel">
          <h3 className="card-heading">{t('profile.preferences')}</h3>
          <p className="text-muted form-hint">{t('profile.preferencesHint')}</p>
          <div className="profile-pref-toolbar">
            <ThemeToggle />
            <LanguageSwitcher />
          </div>
        </GlassCard>

        {prefs && (
          <>
            <GlassCard className="p-6 page-panel">
              <h3 className="card-heading">{t('profile.appSettings')}</h3>
              <p className="text-muted form-hint-sm">{t('settings.subtitle')}</p>
              <h4 className="form-section-title">{t('settings.notifications')}</h4>
              {['notify_email', 'notify_in_app', 'notify_telegram', 'notify_webhook'].map(k => (
                <label key={k} className="auth-remember notify-check">
                  <input type="checkbox" checked={!!prefs[k]} onChange={e => setPrefs({ ...prefs, [k]: e.target.checked })} />
                  {t(`settings.${k}`)}
                </label>
              ))}
              <div className="form-field"><label className="form-label">{t('settings.telegramChatId')}</label>
                <input className="input" value={prefs.telegram_chat_id || ''} onChange={e => setPrefs({ ...prefs, telegram_chat_id: e.target.value })} /></div>
              <div className="form-field"><label className="form-label">{t('settings.discordWebhook')}</label>
                <input className="input" value={prefs.discord_webhook_url || ''} onChange={e => setPrefs({ ...prefs, discord_webhook_url: e.target.value })} /></div>
              <button type="button" className="btn btn-primary" onClick={savePrefs}>{t('common.save')}</button>
            </GlassCard>

            <GlassCard className="p-6 page-panel">
              <h3 className="card-heading">{t('settings.totp')}</h3>
              <p className="text-muted">{prefs.totp_enabled ? t('settings.totpOn') : t('settings.totpOff')}</p>
              {!prefs.totp_enabled ? (
                !totp ? (
                  <button type="button" className="btn btn-secondary" onClick={setup2fa}>{t('settings.setup2fa')}</button>
                ) : (
                  <div>
                    <p className="text-muted totp-uri">{totp.provisioning_uri}</p>
                    <div className="totp-actions">
                      <input className="input totp-field" value={totpCode} onChange={e => setTotpCode(e.target.value)} placeholder={t('settings.totpCodePh')} />
                      <button type="button" className="btn btn-primary" onClick={enable2fa}>{t('settings.enable2fa')}</button>
                    </div>
                  </div>
                )
              ) : (
                <div className="totp-actions">
                  <input className="input totp-field" value={disableTotpCode} onChange={e => setDisableTotpCode(e.target.value)} placeholder={t('settings.totpCodePh')} />
                  <button type="button" className="btn btn-ghost" onClick={disable2fa}>{t('settings.disable2fa')}</button>
                </div>
              )}
            </GlassCard>

            <GlassCard className="p-6 page-panel section-mb-lg">
              <h3 className="card-heading">{t('profile.notificationsInbox')}</h3>
              {notifications.length === 0 ? (
                <p className="text-muted">{t('common.noData')}</p>
              ) : (
                <ul className="log-list-stack">
                  {notifications.slice(0, 20).map((n: any) => (
                    <li key={n.id} className={`panel-muted-lg ${n.is_read ? '' : 'notify-unread'}`}>
                      <strong>{n.title}</strong>
                      <p className="text-sm">{n.message}</p>
                    </li>
                  ))}
                </ul>
              )}
              <button type="button" className="btn btn-ghost btn-sm section-mt-sm" onClick={() => notificationApi.markAllRead().then(loadSettings)}>
                {t('common.markAllRead')}
              </button>
            </GlassCard>

            <GlassCard className="p-6 page-panel">
              <h3 className="card-heading">{t('settings.openApi')}</h3>
              {newKey && <p className="link-box mb-sm">{newKey}</p>}
              <button type="button" className="btn btn-primary" onClick={createKey}>{t('settings.createKey')}</button>
              <ul className="api-key-list">
                {apiKeys.map(k => (
                  <li key={k.id}>
                    <span>{k.name} · {k.key_prefix}…</span>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => settingsApi.revokeApiKey(k.id).then(loadSettings)}>{t('common.delete')}</button>
                  </li>
                ))}
              </ul>
            </GlassCard>
          </>
        )}

        {error && <p className="form-error">{error}</p>}
      </div>
    </Layout>
  )
}
