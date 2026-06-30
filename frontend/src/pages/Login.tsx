import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'
import GlassCard from '../components/GlassCard'
import AuthShell from '../components/AuthShell'
import RippleButton from '../components/ui/RippleButton'
import PasswordInput from '../components/PasswordInput'

export default function Login() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [mode, setMode] = useState<'password' | 'code'>('password')
  const [account, setAccount] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [challengeToken, setChallengeToken] = useState('')
  const [pendingUser, setPendingUser] = useState<{ uid: string; display_name: string; role: string; api_status?: string } | null>(null)
  const [remember, setRemember] = useState(true)
  const [countdown, setCountdown] = useState(0)
  const [devCode, setDevCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    const saved = localStorage.getItem('remember_account')
    if (saved) {
      setAccount(saved)
      setEmail(saved)
    }
  }, [])

  const navigatePostLogin = (data: { role?: string; api_status?: string }) => {
    if (data.role === 'admin') navigate('/admin')
    else if (data.api_status && data.api_status !== 'active') navigate('/api')
    else navigate('/dashboard')
  }

  const finishLogin = (data: any) => {
    if (data?.requires_totp && data.challenge_token) {
      setChallengeToken(data.challenge_token)
      setPendingUser({ uid: data.uid, display_name: data.display_name, role: data.role, api_status: data.api_status })
      setError('')
      return
    }
    if (!data?.access_token) {
      toast.error(t('auth.loginRespError'))
      setError(t('auth.loginRespError'))
      return
    }
    setAuth(data.access_token, data.uid, data.display_name, data.role)
    const remembered = mode === 'password' ? account : email
    if (remember && remembered) localStorage.setItem('remember_account', remembered)
    else localStorage.removeItem('remember_account')
    navigatePostLogin(data)
  }

  const submitTotp = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      finishLogin(await authApi.loginTotp(challengeToken, totpCode))
    } catch {
      toast.error(t('auth.totpError'))
      setError(t('auth.totpError'))
    } finally {
      setLoading(false)
    }
  }

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      finishLogin(await authApi.login(account, password))
    } catch {
      toast.error(t('auth.loginError'))
      setError(t('auth.loginError'))
    } finally {
      setLoading(false)
    }
  }

  const sendCode = async () => {
    setError('')
    try {
      const res = await authApi.sendEmail(email, 'login')
      setDevCode(res.dev_code || '')
      setCountdown(60)
      const timer = setInterval(() => {
        setCountdown(c => { if (c <= 1) { clearInterval(timer); return 0 }; return c - 1 })
      }, 1000)
    } catch (err: any) {
      const msg = err.response?.data?.detail || t('auth.sendFail')
      toast.error(msg)
      setError(msg)
    } finally { /* noop */ }
  }

  const handleCodeLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      finishLogin(await authApi.loginEmail(email, code))
    } catch (err: any) {
      const msg = err.response?.data?.detail || t('auth.codeError')
      toast.error(msg)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  if (challengeToken) {
    return (
      <AuthShell>
        <GlassCard className="auth-glass-card">
          <h2 className="auth-card-title">{t('auth.totpTitle')}</h2>
          <p className="text-muted auth-card-sub">{t('auth.totpSubtitle', { name: pendingUser?.display_name || pendingUser?.uid || '' })}</p>
          <form onSubmit={submitTotp}>
            <div className="form-field">
              <label className="form-label">{t('auth.totpCode')}</label>
              <input className="input" value={totpCode} onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                placeholder="000000" inputMode="numeric" autoComplete="one-time-code" required />
            </div>
            {error && <p className="form-error">{error}</p>}
            <RippleButton type="submit" className="btn btn-auth-primary auth-submit" disabled={loading}>
              {loading ? t('auth.loggingIn') : t('auth.totpVerify')}
            </RippleButton>
            <button type="button" className="btn btn-ghost auth-submit auth-submit-spaced"
              onClick={() => { setChallengeToken(''); setPendingUser(null); setTotpCode('') }}>
              {t('auth.totpBack')}
            </button>
          </form>
        </GlassCard>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <GlassCard className="auth-glass-card">
        <h2 className="auth-card-title">{t('auth.login')}</h2>
        <p className="text-muted auth-card-sub">{t('brand.tagline')}</p>

        <div className="auth-mode-tabs">
          <button type="button" className={`btn ${mode === 'password' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setMode('password')}>{t('auth.passwordLogin')}</button>
          <button type="button" className={`btn ${mode === 'code' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setMode('code')}>{t('auth.emailCodeLogin')}</button>
        </div>

        {mode === 'password' ? (
          <form onSubmit={handlePasswordLogin}>
            <div className="form-field">
              <label className="form-label">{t('common.email')}</label>
              <input className="input" type="email" value={account} onChange={e => setAccount(e.target.value)} placeholder={t('auth.emailPh')} required />
            </div>
            <div className="form-field">
              <label className="form-label">{t('common.password')}</label>
              <PasswordInput value={password} onChange={setPassword} placeholder={t('auth.passwordPh')} required autoComplete="current-password" />
            </div>
            <label className="auth-remember">
              <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
              {t('auth.rememberMe')}
            </label>
            {error && <p className="form-error">{error}</p>}
            <RippleButton type="submit" className="btn btn-auth-primary auth-submit" disabled={loading}>
              {loading ? t('auth.loggingIn') : t('auth.login')}
            </RippleButton>
          </form>
        ) : (
          <form key={locale} onSubmit={handleCodeLogin}>
            <div className="form-field">
              <label className="form-label">{t('common.email')}</label>
              <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder={t('auth.emailPh')} required />
            </div>
            <div className="auth-code-row">
              <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder={t('auth.codePh')} required />
              <button type="button" className="btn btn-ghost" disabled={countdown > 0 || !email} onClick={sendCode}>
                {countdown > 0 ? `${countdown}s` : t('auth.getCode')}
              </button>
            </div>
            {devCode && <p className="text-muted auth-dev-hint">{t('auth.devCode')}: {devCode}</p>}
            {error && <p className="form-error">{error}</p>}
            <RippleButton type="submit" className="btn btn-auth-primary auth-submit" disabled={loading}>
              {loading ? t('auth.loggingIn') : t('auth.emailCodeLogin')}
            </RippleButton>
          </form>
        )}

        <p className="auth-footer">
          {t('auth.noAccount')}{' '}
          <Link to="/register" className="auth-link">{t('auth.registerNow')}</Link>
        </p>
      </GlassCard>
    </AuthShell>
  )
}
