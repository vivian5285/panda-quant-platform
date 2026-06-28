import { useState } from 'react'
import { authApi } from '../api'

type Props = {
  emailCode: string
  phoneCode: string
  onEmailCode: (v: string) => void
  onPhoneCode: (v: string) => void
  devEmail?: string
  devPhone?: string
  onDevCodes?: (email?: string, phone?: string) => void
}

export default function DualVerifyFields({
  emailCode, phoneCode, onEmailCode, onPhoneCode, devEmail, devPhone, onDevCodes,
}: Props) {
  const [countdown, setCountdown] = useState(0)
  const [error, setError] = useState('')

  const sendCodes = async () => {
    setError('')
    try {
      const res = await authApi.sendSecurityCodes()
      onDevCodes?.(res.dev_email_code, res.dev_phone_code)
      setCountdown(60)
      const t = setInterval(() => {
        setCountdown(c => {
          if (c <= 1) { clearInterval(t); return 0 }
          return c - 1
        })
      }, 1000)
    } catch (err: any) {
      setError(err.response?.data?.detail || '发送失败，请先绑定邮箱和手机')
    }
  }

  return (
    <div style={{ marginBottom: 16, padding: 16, borderRadius: 10, border: '1px solid rgba(255,193,7,0.35)', background: 'rgba(255,193,7,0.06)' }}>
      <p style={{ fontSize: 13, marginBottom: 12, color: 'rgba(255,255,255,0.7)' }}>
        安全操作需<strong style={{ color: '#ffc107' }}> 邮箱 + 手机双重验证码</strong>
      </p>
      <button type="button" className="btn btn-ghost" style={{ width: '100%', marginBottom: 12, fontSize: 12 }}
        disabled={countdown > 0} onClick={sendCodes}>
        {countdown > 0 ? `${countdown}s 后可重发` : '获取安全验证码（邮箱+手机）'}
      </button>
      {(devEmail || devPhone) && (
        <p className="text-muted" style={{ fontSize: 11, marginBottom: 8 }}>
          开发模式 — 邮箱: {devEmail || '—'} / 手机: {devPhone || '—'}
        </p>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <input className="input" placeholder="邮箱验证码" value={emailCode}
          onChange={e => onEmailCode(e.target.value)} required />
        <input className="input" placeholder="手机验证码" value={phoneCode}
          onChange={e => onPhoneCode(e.target.value)} required />
      </div>
      {error && <p className="text-red" style={{ fontSize: 12, marginTop: 8 }}>{error}</p>}
    </div>
  )
}
