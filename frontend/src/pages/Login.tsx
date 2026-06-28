import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import GlassCard from '../components/GlassCard'

export default function Login() {
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
      setError('登录响应异常，请重试')
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
      setError('账号或密码错误')
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
      const t = setInterval(() => {
        setCountdown(c => { if (c <= 1) { clearInterval(t); return 0 }; return c - 1 })
      }, 1000)
    } catch (err: any) {
      setError(err.response?.data?.detail || '发送失败')
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
      setError(err.response?.data?.detail || '验证码错误或已过期')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: 'var(--bg-primary)' }}>
      <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} style={{ width: '100%', maxWidth: 420 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <motion.span style={{ fontSize: 56, display: 'block' }} animate={{ y: [0, -6, 0] }} transition={{ repeat: Infinity, duration: 3 }}>🐼</motion.span>
          <h1 style={{ fontSize: 28, fontWeight: 700, marginTop: 12 }}>熊猫量化</h1>
        </div>

        <GlassCard green className="p-8">
          <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
            <button type="button" className={`btn ${mode === 'password' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('password')}>密码登录</button>
            <button type="button" className={`btn ${mode === 'code' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ flex: 1, fontSize: 13 }} onClick={() => setMode('code')}>验证码登录</button>
          </div>

          {mode === 'password' ? (
            <form onSubmit={handlePasswordLogin}>
              <div style={{ marginBottom: 16 }}>
                <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>邮箱 / 手机号</label>
                <input className="input" value={account} onChange={e => setAccount(e.target.value)} placeholder="your@email.com 或 13800138000" required />
              </div>
              <div style={{ marginBottom: 24 }}>
                <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>密码</label>
                <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} required />
              </div>
              {error && <p className="text-red" style={{ fontSize: 13, marginBottom: 16 }}>{error}</p>}
              <button className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>{loading ? '登录中...' : '登 录'}</button>
            </form>
          ) : (
            <form onSubmit={handleCodeLogin}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                <button type="button" className={`btn ${codeChannel === 'phone' ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ flex: 1, fontSize: 12 }} onClick={() => setCodeChannel('phone')}>手机验证码</button>
                <button type="button" className={`btn ${codeChannel === 'email' ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ flex: 1, fontSize: 12 }} onClick={() => setCodeChannel('email')}>邮箱验证码</button>
              </div>
              {codeChannel === 'phone' ? (
                <div style={{ marginBottom: 16 }}>
                  <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>手机号</label>
                  <input className="input" value={phone} onChange={e => setPhone(e.target.value)} placeholder="13800138000" required />
                </div>
              ) : (
                <div style={{ marginBottom: 16 }}>
                  <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>邮箱</label>
                  <input className="input" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder="验证码" required style={{ flex: 1 }} />
                <button type="button" className="btn btn-ghost" disabled={countdown > 0 || (codeChannel === 'phone' ? !phone : !email)} onClick={sendCode}>
                  {countdown > 0 ? `${countdown}s` : '获取验证码'}
                </button>
              </div>
              {devCode && <p className="text-muted" style={{ fontSize: 12, marginBottom: 12 }}>开发模式验证码：{devCode}</p>}
              {error && <p className="text-red" style={{ fontSize: 13, marginBottom: 16 }}>{error}</p>}
              <button className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>{loading ? '登录中...' : '验证码登录'}</button>
            </form>
          )}

          <p className="text-muted" style={{ textAlign: 'center', marginTop: 20, fontSize: 13 }}>
            还没有账户？ <Link to="/register" className="text-green" style={{ textDecoration: 'none' }}>立即注册</Link>
          </p>
        </GlassCard>
      </motion.div>
    </div>
  )
}
