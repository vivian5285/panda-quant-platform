import { useState, useEffect } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import GlassCard from '../components/GlassCard'

export default function Register() {
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
      const t = setInterval(() => {
        setCountdown(c => { if (c <= 1) { clearInterval(t); return 0 }; return c - 1 })
      }, 1000)
    } catch (err: any) {
      setError(err.response?.data?.detail || '发送失败')
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
      setError(err.response?.data?.detail || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: 'var(--bg-primary)' }}>
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} style={{ width: '100%', maxWidth: 420 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <span style={{ fontSize: 48 }}>🐼</span>
          <h1 style={{ fontSize: 24, fontWeight: 600, marginTop: 8 }}>创建账户</h1>
          <p className="text-muted" style={{ fontSize: 13, marginTop: 8 }}>邮箱或手机注册，需验证码确认</p>
        </div>
        <GlassCard green className="p-8">
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            <button type="button" className={`btn ${mode === 'email' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('email')}>邮箱注册</button>
            <button type="button" className={`btn ${mode === 'phone' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('phone')}>手机注册</button>
          </div>
          <form onSubmit={handleSubmit}>
            {mode === 'email' ? (
              <div style={{ marginBottom: 16 }}>
                <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>邮箱</label>
                <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
              </div>
            ) : (
              <div style={{ marginBottom: 16 }}>
                <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>手机号</label>
                <input className="input" value={phone} onChange={e => setPhone(e.target.value)} placeholder="13800138000" required />
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder="验证码" required style={{ flex: 1 }} />
              <button type="button" className="btn btn-ghost" disabled={countdown > 0 || (mode === 'email' ? !email : !phone)} onClick={sendCode}>
                {countdown > 0 ? `${countdown}s` : '获取验证码'}
              </button>
            </div>
            {devCode && <p className="text-muted" style={{ fontSize: 12, marginBottom: 12 }}>开发模式验证码：{devCode}</p>}
            <div style={{ marginBottom: 16 }}>
              <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>登录密码</label>
              <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} minLength={6} required />
            </div>
            <div style={{ marginBottom: 24 }}>
              <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>推荐码（可选）</label>
              <input className="input" value={referralCode} onChange={e => setReferralCode(e.target.value)} placeholder="PANDA-XXXXXXXX" readOnly={!!searchParams.get('ref')} />
            </div>
            {error && <p className="text-red" style={{ fontSize: 13, marginBottom: 16 }}>{error}</p>}
            <button className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>
              {loading ? '注册中...' : '注 册'}
            </button>
          </form>
          <p className="text-muted" style={{ textAlign: 'center', marginTop: 20, fontSize: 13 }}>
            已有账户？ <Link to="/login" className="text-green" style={{ textDecoration: 'none' }}>登录</Link>
          </p>
        </GlassCard>
      </motion.div>
    </div>
  )
}
