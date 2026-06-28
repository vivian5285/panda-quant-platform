import { useEffect, useState } from 'react'
import { Copy, Check } from 'lucide-react'
import Layout from '../components/Layout'
import GlassCard from '../components/GlassCard'
import DualVerifyFields from '../components/DualVerifyFields'
import { authApi } from '../api'
import { useAuth } from '../store/auth'

export default function Profile() {
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
      setMsg('昵称已更新')
    } catch (err: any) {
      setError(err.response?.data?.detail || '更新失败')
    }
  }

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.changePassword(oldPwd, newPwd, secEmailCode, secPhoneCode)
      setProfile(p)
      setMsg('登录密码已修改')
      setOldPwd(''); setNewPwd(''); setSecEmailCode(''); setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || '修改失败')
    }
  }

  const saveWithdrawPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.setWithdrawPassword(withdrawPwd, secEmailCode, secPhoneCode)
      setProfile(p)
      setMsg('提现密码已设置')
      setWithdrawPwd(''); setSecEmailCode(''); setSecPhoneCode('')
    } catch (err: any) {
      setError(err.response?.data?.detail || '设置失败')
    }
  }

  const bindEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.bindEmail(bindEmailVal, bindEmailCode, profile?.has_phone ? bindOtherCode : undefined)
      setProfile(p)
      setMsg('邮箱绑定成功')
    } catch (err: any) {
      setError(err.response?.data?.detail || '绑定失败')
    }
  }

  const bindPhone = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setMsg('')
    try {
      const p = await authApi.bindPhone(bindPhoneVal, bindPhoneCode, profile?.has_email ? bindOtherCode : undefined)
      setProfile(p)
      setMsg('手机绑定成功')
    } catch (err: any) {
      setError(err.response?.data?.detail || '绑定失败')
    }
  }

  const bothBound = profile?.has_email && profile?.has_phone

  return (
    <Layout>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>个人资料</h1>

      <GlassCard green className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
        <h3 style={{ fontSize: 15, marginBottom: 16 }}>我的 UID</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span className="text-green" style={{ fontSize: 28, fontWeight: 700, letterSpacing: 3, fontFamily: 'monospace' }}>
            {profile?.uid || uid || '...'}
          </span>
          <button className="btn btn-ghost" onClick={() => copyText(profile?.uid || uid || '', 'uid')}>
            {copied === 'uid' ? <Check size={14} /> : <Copy size={14} />}
            {copied === 'uid' ? '已复制' : '复制 UID'}
          </button>
        </div>
      </GlassCard>

      <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
        <h3 style={{ fontSize: 15, marginBottom: 16 }}>账号信息</h3>
        <div style={{ display: 'grid', gap: 12, fontSize: 14 }}>
          <div><span className="text-muted">邮箱</span><p>{profile?.email || '未绑定'}</p></div>
          <div><span className="text-muted">手机</span><p>{profile?.phone || '未绑定'}</p></div>
          {!bothBound && (
            <p className="text-muted" style={{ fontSize: 12 }}>
              安全操作（改密码、提现密码、绑定提现地址）需同时绑定邮箱和手机
            </p>
          )}
        </div>
      </GlassCard>

      {!profile?.has_email && (
        <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
          <h3 style={{ fontSize: 15, marginBottom: 16 }}>绑定邮箱</h3>
          <form onSubmit={bindEmail}>
            <input className="input" type="email" placeholder="邮箱" value={bindEmailVal} onChange={e => setBindEmailVal(e.target.value)} style={{ marginBottom: 8 }} required />
            <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <input className="input" placeholder="邮箱验证码" value={bindEmailCode} onChange={e => setBindEmailCode(e.target.value)} required />
              <button type="button" className="btn btn-ghost" onClick={() => authApi.sendEmail(bindEmailVal, 'register')}>获取</button>
            </div>
            {profile?.has_phone && (
              <input className="input" placeholder="现有手机安全验证码" value={bindOtherCode} onChange={e => setBindOtherCode(e.target.value)} style={{ marginBottom: 8 }} />
            )}
            <button className="btn btn-primary" type="submit">绑定邮箱</button>
          </form>
        </GlassCard>
      )}

      {!profile?.has_phone && (
        <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
          <h3 style={{ fontSize: 15, marginBottom: 16 }}>绑定手机</h3>
          <form onSubmit={bindPhone}>
            <input className="input" placeholder="手机号" value={bindPhoneVal} onChange={e => setBindPhoneVal(e.target.value)} style={{ marginBottom: 8 }} required />
            <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <input className="input" placeholder="手机验证码" value={bindPhoneCode} onChange={e => setBindPhoneCode(e.target.value)} required />
              <button type="button" className="btn btn-ghost" onClick={() => authApi.sendSms(bindPhoneVal, 'register')}>获取</button>
            </div>
            {profile?.has_email && (
              <input className="input" placeholder="现有邮箱安全验证码" value={bindOtherCode} onChange={e => setBindOtherCode(e.target.value)} style={{ marginBottom: 8 }} />
            )}
            <button className="btn btn-primary" type="submit">绑定手机</button>
          </form>
        </GlassCard>
      )}

      <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
        <h3 style={{ fontSize: 15, marginBottom: 16 }}>设置昵称</h3>
        <form onSubmit={saveNickname}>
          <input className="input" value={nickname} onChange={e => setNickname(e.target.value)}
            placeholder={displayName || '输入昵称'} maxLength={32} style={{ marginBottom: 12 }} />
          <button className="btn btn-primary" type="submit">保存昵称</button>
        </form>
      </GlassCard>

      {bothBound && (
        <GlassCard className="p-6" style={{ marginBottom: 24, maxWidth: 560 }}>
          <h3 style={{ fontSize: 15, marginBottom: 8 }}>安全设置</h3>
          <p className="text-muted" style={{ fontSize: 12, marginBottom: 16 }}>修改密码、提现密码需邮箱+手机双重验证码</p>

          <DualVerifyFields
            emailCode={secEmailCode} phoneCode={secPhoneCode}
            onEmailCode={setSecEmailCode} onPhoneCode={setSecPhoneCode}
            devEmail={devEmail} devPhone={devPhone}
            onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
          />

          <form onSubmit={changePassword} style={{ marginBottom: 24 }}>
            <h4 style={{ fontSize: 14, marginBottom: 12 }}>修改登录密码</h4>
            <input className="input" type="password" placeholder="原密码" value={oldPwd} onChange={e => setOldPwd(e.target.value)} style={{ marginBottom: 8 }} required />
            <input className="input" type="password" placeholder="新密码（至少6位）" value={newPwd} onChange={e => setNewPwd(e.target.value)} style={{ marginBottom: 12 }} required />
            <button className="btn btn-primary" type="submit">修改登录密码</button>
          </form>

          <form onSubmit={saveWithdrawPassword}>
            <h4 style={{ fontSize: 14, marginBottom: 12 }}>
              {profile?.has_withdraw_password ? '修改提现密码' : '设置提现密码'}
            </h4>
            <input className="input" type="password" placeholder="提现密码（至少6位）" value={withdrawPwd} onChange={e => setWithdrawPwd(e.target.value)} style={{ marginBottom: 12 }} required />
            <button className="btn btn-primary" type="submit">保存提现密码</button>
          </form>
        </GlassCard>
      )}

      {msg && <p className="text-green" style={{ marginBottom: 12 }}>{msg}</p>}
      {error && <p className="text-red" style={{ marginBottom: 12 }}>{error}</p>}
    </Layout>
  )
}
