import { useEffect, useState } from 'react'
import { Copy, Check } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import DualVerifyFields from '../components/DualVerifyFields'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'

export default function Profile() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [profile, setProfile] = useState<any>(null)
  const [nickname, setNickname] = useState('')
  const [msg, setMsg] = useState('')
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

  useEffect(() => {
    authApi.me().then(p => {
      setProfile(p)
      setNickname(p.nickname || '')
    })
  }, [])

  const copyText = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const saveNickname = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.updateNickname(nickname.trim())
      setProfile(p)
      if (token) setAuth(token, p.uid, p.display_name, role || p.role)
      setMsg(t('profile.nicknameUpdated'))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.updateFail'))
    }
  }

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.changePassword(oldPwd, newPwd, secEmailCode, secPhoneCode)
      setProfile(p)
      setMsg(t('profile.pwdChanged'))
      setOldPwd(''); setNewPwd(''); setSecEmailCode(''); setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.changeFail'))
    }
  }

  const saveWithdrawPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.setWithdrawPassword(withdrawPwd, secEmailCode, secPhoneCode)
      setProfile(p)
      setMsg(t('profile.withdrawPwdSet'))
      setWithdrawPwd(''); setSecEmailCode(''); setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.setFail'))
    }
  }

  const bindEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.bindEmail(bindEmailVal, bindEmailCode, profile?.has_phone ? bindOtherCode : undefined)
      setProfile(p)
      setMsg(t('profile.emailBound'))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.bindFail'))
    }
  }

  const bindPhone = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.bindPhone(bindPhoneVal, bindPhoneCode, profile?.has_email ? bindOtherCode : undefined)
      setProfile(p)
      setMsg(t('profile.phoneBound'))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('profile.bindFail'))
    }
  }

  const bothBound = profile?.has_email && profile?.has_phone

  return (
    <Layout>
      <PageHeader title={t('profile.title')} />

      <div key={locale}>
        <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
          <h3 className="card-heading">{t('profile.myUid')}</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 28, fontWeight: 700, letterSpacing: 3, fontFamily: 'ui-monospace, monospace' }}>
              {profile?.uid || uid || '...'}
            </span>
            <button className="btn btn-ghost btn-sm" onClick={() => copyText(profile?.uid || uid || '', 'uid')}>
              {copied === 'uid' ? <Check size={14} /> : <Copy size={14} />}
              {copied === 'uid' ? t('common.copied') : t('profile.copyUid')}
            </button>
          </div>
        </GlassCard>

        <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
          <h3 className="card-heading">{t('profile.accountInfo')}</h3>
          <div style={{ display: 'grid', gap: 12, fontSize: 14 }}>
            <div><span className="text-muted">{t('common.email')}</span><p>{profile?.email || t('profile.notBound')}</p></div>
            <div><span className="text-muted">{t('common.phone')}</span><p>{profile?.phone || t('profile.notBound')}</p></div>
            {!bothBound && (
              <p className="text-muted" style={{ fontSize: 12 }}>{t('profile.bindHint')}</p>
            )}
          </div>
        </GlassCard>

        {!profile?.has_email && (
          <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
            <h3 className="card-heading">{t('profile.bindEmail')}</h3>
            <form onSubmit={bindEmail}>
              <input className="input" type="email" placeholder={t('common.email')} value={bindEmailVal} onChange={e => setBindEmailVal(e.target.value)} style={{ marginBottom: 8 }} required />
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                <input className="input" placeholder={t('profile.emailCodePh')} value={bindEmailCode} onChange={e => setBindEmailCode(e.target.value)} required />
                <button type="button" className="btn btn-ghost" onClick={() => authApi.sendEmail(bindEmailVal, 'register')}>{t('common.get')}</button>
              </div>
              {profile?.has_phone && (
                <input className="input" placeholder={t('profile.existingPhoneCodePh')} value={bindOtherCode} onChange={e => setBindOtherCode(e.target.value)} style={{ marginBottom: 8 }} />
              )}
              <button className="btn btn-primary" type="submit">{t('profile.bindEmailBtn')}</button>
            </form>
          </GlassCard>
        )}

        {!profile?.has_phone && (
          <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
            <h3 className="card-heading">{t('profile.bindPhone')}</h3>
            <form onSubmit={bindPhone}>
              <input className="input" placeholder={t('auth.phonePh')} value={bindPhoneVal} onChange={e => setBindPhoneVal(e.target.value)} style={{ marginBottom: 8 }} required />
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                <input className="input" placeholder={t('profile.phoneCodePh')} value={bindPhoneCode} onChange={e => setBindPhoneCode(e.target.value)} required />
                <button type="button" className="btn btn-ghost" onClick={() => authApi.sendSms(bindPhoneVal, 'register')}>{t('common.get')}</button>
              </div>
              {profile?.has_email && (
                <input className="input" placeholder={t('profile.existingEmailCodePh')} value={bindOtherCode} onChange={e => setBindOtherCode(e.target.value)} style={{ marginBottom: 8 }} />
              )}
              <button className="btn btn-primary" type="submit">{t('profile.bindPhoneBtn')}</button>
            </form>
          </GlassCard>
        )}

        <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
          <h3 className="card-heading">{t('profile.setNickname')}</h3>
          <form onSubmit={saveNickname}>
            <input className="input" value={nickname} onChange={e => setNickname(e.target.value)}
              placeholder={displayName || t('profile.nicknamePh')} maxLength={32} style={{ marginBottom: 12 }} />
            <button className="btn btn-primary" type="submit">{t('profile.saveNickname')}</button>
          </form>
        </GlassCard>

        {bothBound && (
          <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
            <h3 className="card-heading">{t('profile.securitySettings')}</h3>
            <p className="text-muted" style={{ fontSize: 12, marginBottom: 16 }}>{t('profile.securityHint')}</p>

            <DualVerifyFields
              emailCode={secEmailCode} phoneCode={secPhoneCode}
              onEmailCode={setSecEmailCode} onPhoneCode={setSecPhoneCode}
              devEmail={devEmail} devPhone={devPhone}
              onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
            />

            <form onSubmit={changePassword} style={{ marginBottom: 24 }}>
              <h4 style={{ fontSize: 14, marginBottom: 12, fontWeight: 600 }}>{t('profile.changeLoginPwd')}</h4>
              <input className="input" type="password" placeholder={t('profile.oldPwdPh')} value={oldPwd} onChange={e => setOldPwd(e.target.value)} style={{ marginBottom: 8 }} required />
              <input className="input" type="password" placeholder={t('profile.newPwdPh')} value={newPwd} onChange={e => setNewPwd(e.target.value)} style={{ marginBottom: 12 }} required />
              <button className="btn btn-primary" type="submit">{t('profile.changePwdBtn')}</button>
            </form>

            <form onSubmit={saveWithdrawPassword}>
              <h4 style={{ fontSize: 14, marginBottom: 12, fontWeight: 600 }}>
                {profile?.has_withdraw_password ? t('profile.changeWithdrawPwd') : t('profile.setWithdrawPwd')}
              </h4>
              <input className="input" type="password" placeholder={t('profile.withdrawPwdPh')} value={withdrawPwd} onChange={e => setWithdrawPwd(e.target.value)} style={{ marginBottom: 12 }} required />
              <button className="btn btn-primary" type="submit">{t('profile.saveWithdrawPwd')}</button>
            </form>
          </GlassCard>
        )}

        {msg && <div className="flash-msg">{msg}</div>}
        {error && <p className="form-error">{error}</p>}
      </div>
    </Layout>
  )
}
