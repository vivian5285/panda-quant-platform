import { useState, useEffect } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import GlassCard from '../components/GlassCard'
import TopToolbar from '../components/TopToolbar'
import { useI18n } from '../i18n'

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
      setError(err.response?.data?.detail || t('auth.sendFail'))
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
      navigate('/profile')
    } catch (err: any) {
      setError(err.response?.data?.detail || t('auth.registerFail'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <TopToolbar />
      <motion.div key={locale} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="auth-container">
        <div className="auth-header">
          <span className="auth-logo" style={{ fontSize: 48 }}>🐼</span>
          <h1 className="auth-title" style={{ fontSize: 28 }}>{t('auth.registerTitle')}</h1>
          <p className="auth-tagline">{t('auth.registerSubtitle')}</p>
        </div>
        <GlassCard green className="p-8">
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            <button type="button" className={`btn ${mode === 'email' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('email')}>{t('auth.emailRegister')}</button>
            <button type="button" className={`btn ${mode === 'phone' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('phone')}>{t('auth.phoneRegister')}</button>
          </div>
          <form onSubmit={handleSubmit}>
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
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder={t('auth.codePh')} required style={{ flex: 1 }} />
              <button type="button" className="btn btn-ghost" disabled={countdown > 0 || (mode === 'email' ? !email : !phone)} onClick={sendCode}>
                {countdown > 0 ? `${countdown}s` : t('auth.getCode')}
              </button>
            </div>
            {devCode && <p className="text-muted" style={{ fontSize: 12, marginBottom: 12 }}>{t('auth.devCode')}: {devCode}</p>}
            <div className="form-field">
              <label className="form-label">{t('auth.loginPassword')}</label>
              <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} minLength={6} required />
            </div>
            <div className="form-field">
              <label className="form-label">{t('auth.referralOptional')}</label>
              <input className="input" value={referralCode} onChange={e => setReferralCode(e.target.value)} placeholder="PANDA-XXXXXXXX" readOnly={!!searchParams.get('ref')} />
            </div>
            {error && <p className="form-error">{error}</p>}
            <button className="btn btn-primary auth-submit" disabled={loading}>
              {loading ? t('auth.registering') : t('auth.register')}
            </button>
          </form>
          <p className="auth-footer">
            {t('auth.hasAccount')}{' '}
            <Link to="/login" className="auth-link">{t('auth.loginNow')}</Link>
          </p>
        </GlassCard>
      </motion.div>
    </div>
  )
}
