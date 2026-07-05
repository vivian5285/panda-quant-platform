import { useState, useEffect } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'
import GlassCard from '../components/GlassCard'
import AuthShell from '../components/AuthShell'
import RippleButton from '../components/ui/RippleButton'
import PasswordInput from '../components/PasswordInput'

export default function Register() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
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
      const res = await authApi.sendEmail(email, 'register')
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
    if (password !== confirmPassword) {
      toast.error(t('auth.passwordMismatch'))
      setError(t('auth.passwordMismatch'))
      return
    }
    if (!referralCode.trim()) {
      toast.error(t('auth.referralRequired'))
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await authApi.register({
        email,
        password,
        verification_code: code,
        referral_code: referralCode.trim(),
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
        {searchParams.get('from') && (
          <p className="register-inviter-banner">{t('register.inviterBanner', { uid: searchParams.get('from') ?? '' })}</p>
        )}

        <form key={locale} onSubmit={handleSubmit}>
          <div className="form-field">
            <label className="form-label">{t('common.email')}</label>
            <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
          </div>
          <div className="auth-code-row">
            <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder={t('auth.codePh')} required />
            <button type="button" className="btn btn-ghost" disabled={countdown > 0 || !email} onClick={sendCode}>
              {countdown > 0 ? `${countdown}s` : t('auth.getCode')}
            </button>
          </div>
          {devCode && <p className="text-muted auth-dev-hint">{t('auth.devCode')}: {devCode}</p>}
          <div className="form-field">
            <label className="form-label">{t('auth.loginPassword')}</label>
            <PasswordInput value={password} onChange={setPassword} minLength={6} required autoComplete="new-password" />
          </div>
          <div className="form-field">
            <label className="form-label">{t('auth.confirmPassword')}</label>
            <PasswordInput value={confirmPassword} onChange={setConfirmPassword} minLength={6} required autoComplete="new-password" />
          </div>
          <div className="form-field">
            <label className="form-label">{t('auth.referralRequired')}</label>
            <input className="input" value={referralCode} onChange={e => setReferralCode(e.target.value)} placeholder="UID 或 GEMINI-XXXXXXXX" required readOnly={!!searchParams.get('ref')} />
            <p className="text-muted text-xs section-mt-xs">{t('auth.referralRequiredHint')}</p>
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
