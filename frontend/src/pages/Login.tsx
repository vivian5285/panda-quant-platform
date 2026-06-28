import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import GlassCard from '../components/GlassCard'
import TopToolbar from '../components/TopToolbar'

export default function Login() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [mode, setMode] = useState<'password' | 'code'>('password')
  const [codeChannel, setCodeChannel] = useState<'phone' | 'email'>('phone')
  const [account, setAccount] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [devCode, setDevCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuth()
  const navigate = useNavigate()

  const finishLogin = (data: any) => {
    if (!data?.access_token) {
      setError(t('auth.loginRespError'))
      return
    }
    setAuth(data.access_token, data.uid, data.display_name, data.role)
    navigate(data.role === 'admin' ? '/admin' : '/dashboard')
  }

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      finishLogin(await authApi.login(account, password))
    } catch {
      setError(t('auth.loginError'))
    } finally {
      setLoading(false)
    }
  }

  const sendCode = async () => {
    setError('')
    try {
      const res = codeChannel === 'phone'
        ? await authApi.sendSms(phone, 'login')
        : await authApi.sendEmail(email, 'login')
      setDevCode(res.dev_code || '')
      setCountdown(60)
      const timer = setInterval(() => {
        setCountdown(c => { if (c <= 1) { clearInterval(timer); return 0 }; return c - 1 })
      }, 1000)
    } catch (err: any) {
      setError(err.response?.data?.detail || t('auth.sendFail'))
    }
  }

  const handleCodeLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const data = codeChannel === 'phone'
        ? await authApi.loginSms(phone, code)
        : await authApi.loginEmail(email, code)
      finishLogin(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || t('auth.codeError'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <TopToolbar />
      <motion.div key={locale} initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className="auth-container">
        <div className="auth-header">
          <motion.span className="auth-logo" animate={{ y: [0, -6, 0] }} transition={{ repeat: Infinity, duration: 3 }}>🐼</motion.span>
          <h1 className="auth-title">{t('brand.name')}</h1>
          <p className="auth-tagline">{t('brand.tagline')}</p>
        </div>

        <GlassCard green className="p-8">
          <div className="auth-mode-tabs">
            <button type="button" className={`btn ${mode === 'password' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('password')}>{t('auth.passwordLogin')}</button>
            <button type="button" className={`btn ${mode === 'code' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('code')}>{t('auth.codeLogin')}</button>
          </div>

          {mode === 'password' ? (
            <form onSubmit={handlePasswordLogin}>
              <div className="form-field">
                <label className="form-label">{t('auth.account')}</label>
                <input className="input" value={account} onChange={e => setAccount(e.target.value)} placeholder={t('auth.accountPh')} required />
              </div>
              <div className="form-field">
                <label className="form-label">{t('common.password')}</label>
                <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder={t('auth.passwordPh')} required />
              </div>
              {error && <p className="form-error">{error}</p>}
              <button className="btn btn-primary auth-submit" disabled={loading}>
                {loading ? t('auth.loggingIn') : t('auth.login')}
              </button>
            </form>
          ) : (
            <form onSubmit={handleCodeLogin}>
              <div className="auth-mode-tabs" style={{ marginBottom: 16 }}>
                <button type="button" className={`btn ${codeChannel === 'phone' ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ flex: 1, fontSize: 12 }} onClick={() => setCodeChannel('phone')}>{t('auth.phoneCode')}</button>
                <button type="button" className={`btn ${codeChannel === 'email' ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ flex: 1, fontSize: 12 }} onClick={() => setCodeChannel('email')}>{t('auth.emailCode')}</button>
              </div>
              {codeChannel === 'phone' ? (
                <div className="form-field">
                  <label className="form-label">{t('common.phone')}</label>
                  <input className="input" value={phone} onChange={e => setPhone(e.target.value)} placeholder={t('auth.phonePh')} required />
                </div>
              ) : (
                <div className="form-field">
                  <label className="form-label">{t('common.email')}</label>
                  <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder={t('auth.codePh')} required style={{ flex: 1 }} />
                <button type="button" className="btn btn-ghost" disabled={countdown > 0 || (codeChannel === 'phone' ? !phone : !email)} onClick={sendCode}>
                  {countdown > 0 ? `${countdown}s` : t('auth.getCode')}
                </button>
              </div>
              {devCode && <p className="text-muted" style={{ fontSize: 12, marginBottom: 12 }}>{t('auth.devCode')}: {devCode}</p>}
              {error && <p className="form-error">{error}</p>}
              <button className="btn btn-primary auth-submit" disabled={loading}>
                {loading ? t('auth.loggingIn') : t('auth.codeLogin')}
              </button>
            </form>
          )}

          <p className="auth-footer">
            {t('auth.noAccount')}{' '}
            <Link to="/register" className="auth-link">{t('auth.registerNow')}</Link>
          </p>
        </GlassCard>
      </motion.div>
    </div>
  )
}
