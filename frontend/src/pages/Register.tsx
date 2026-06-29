import { useState, useEffect } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'
import GlassCard from '../components/GlassCard'
import AuthShell from '../components/AuthShell'
import OAuthSocialButtons from '../components/OAuthSocialButtons'
import RippleButton from '../components/ui/RippleButton'

export default function Register() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [mode, setMode] = useState<'email' | 'phone'>('email')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [referralCode, setReferralCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [devCode, setDevCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  useEffect(() => {
    const ref = searchParams.get('ref')
    if (ref) setReferralCode(ref)
  }, [searchParams])

  const sendCode = async () => {
    setError('')
    try {
      const res = mode === 'email'
        ? await authApi.sendEmail(email, 'register')
        : await authApi.sendSms(phone, 'register')
      setDevCode(res.dev_code || '')
      setCountdown(60)
      const timer = setInterval(() => {
        setCountdown(c => { if (c <= 1) { clearInterval(timer); return 0 }; return c - 1 })
      }, 1000)
    } catch (err: any) {
      const msg = err.response?.data?.detail || t('auth.sendFail')
      toast.error(msg)
      setError(msg)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const data = await authApi.register({
        email: mode === 'email' ? email : undefined,
        phone: mode === 'phone' ? phone : undefined,
        password,
        verification_code: code,
        referral_code: referralCode || undefined,
      })
      setAuth(data.access_token, data.uid, data.display_name, data.role)
      navigate('/api')
    } catch (err: any) {
      const msg = err.response?.data?.detail || t('auth.registerFail')
      toast.error(msg)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthShell>
      <GlassCard className="auth-glass-card">
        <h2 className="auth-card-title">{t('auth.registerTitle')}</h2>
        <p className="text-muted auth-card-sub">{t('auth.registerSubtitle')}</p>

        <OAuthSocialButtons />

        <div className="auth-mode-tabs">
          <button type="button" className={`btn ${mode === 'email' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setMode('email')}>{t('auth.emailRegister')}</button>
          <button type="button" className={`btn ${mode === 'phone' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setMode('phone')}>{t('auth.phoneRegister')}</button>
        </div>

        <form key={locale} onSubmit={handleSubmit}>
          {mode === 'email' ? (
            <div className="form-field">
              <label className="form-label">{t('common.email')}</label>
              <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
            </div>
          ) : (
            <div className="form-field">
              <label className="form-label">{t('auth.phoneLabel')}</label>
              <input className="input" value={phone} onChange={e => setPhone(e.target.value)} placeholder={t('auth.phonePh')} required />
            </div>
          )}
          <div className="auth-code-row">
            <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder={t('auth.codePh')} required />
            <button type="button" className="btn btn-ghost" disabled={countdown > 0 || (mode === 'email' ? !email : !phone)} onClick={sendCode}>
              {countdown > 0 ? `${countdown}s` : t('auth.getCode')}
            </button>
          </div>
          {devCode && <p className="text-muted auth-dev-hint">{t('auth.devCode')}: {devCode}</p>}
          <div className="form-field">
            <label className="form-label">{t('auth.loginPassword')}</label>
            <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} minLength={6} required />
          </div>
          <div className="form-field">
            <label className="form-label">{t('auth.referralOptional')}</label>
            <input className="input" value={referralCode} onChange={e => setReferralCode(e.target.value)} placeholder="GEMINI-XXXXXXXX" readOnly={!!searchParams.get('ref')} />
          </div>
          {error && <p className="form-error">{error}</p>}
          <RippleButton type="submit" className="btn btn-auth-primary auth-submit" disabled={loading}>
            {loading ? t('auth.registering') : t('auth.register')}
          </RippleButton>
        </form>

        <p className="auth-footer">
          {t('auth.hasAccount')}{' '}
          <Link to="/login" className="auth-link">{t('auth.loginNow')}</Link>
        </p>
      </GlassCard>
    </AuthShell>
  )
}
