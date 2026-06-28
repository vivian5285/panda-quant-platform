import { useState } from 'react'
import { authApi } from '../api'
import { useI18n } from '../i18n'

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
  const { t } = useI18n()
  const [countdown, setCountdown] = useState(0)
  const [error, setError] = useState('')

  const sendCodes = async () => {
    setError('')
    try {
      const res = await authApi.sendSecurityCodes()
      onDevCodes?.(res.dev_email_code, res.dev_phone_code)
      setCountdown(60)
      const timer = setInterval(() => {
        setCountdown(c => {
          if (c <= 1) { clearInterval(timer); return 0 }
          return c - 1
        })
      }, 1000)
    } catch (err: any) {
      setError(err.response?.data?.detail || t('security.sendFail'))
    }
  }

  return (
    <div className="security-notice" style={{ marginBottom: 16 }}>
      <p style={{ fontSize: 13, marginBottom: 12, color: 'var(--text-secondary)' }}>
        {t('security.dualTitle')}
      </p>
      <button type="button" className="btn btn-ghost" style={{ width: '100%', marginBottom: 12, fontSize: 12 }}
        disabled={countdown > 0} onClick={sendCodes}>
        {countdown > 0 ? t('security.resendIn', { n: countdown }) : t('security.getCodes')}
      </button>
      {(devEmail || devPhone) && (
        <p className="text-muted" style={{ fontSize: 11, marginBottom: 8 }}>
          {t('security.devMode')} — {t('common.email')}: {devEmail || '—'} / {t('common.phone')}: {devPhone || '—'}
        </p>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <input className="input" placeholder={t('security.emailCodePh')} value={emailCode}
          onChange={e => onEmailCode(e.target.value)} required />
        <input className="input" placeholder={t('security.phoneCodePh')} value={phoneCode}
          onChange={e => onPhoneCode(e.target.value)} required />
      </div>
      {error && <p className="text-red" style={{ fontSize: 12, marginTop: 8 }}>{error}</p>}
    </div>
  )
}
