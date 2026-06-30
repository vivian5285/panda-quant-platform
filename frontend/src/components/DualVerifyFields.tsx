import { useState } from 'react'
import { authApi } from '../api'
import { useI18n } from '../i18n'

type Props = {
  emailCode: string
  phoneCode?: string
  onEmailCode: (v: string) => void
  onPhoneCode?: (v: string) => void
  devEmail?: string
  devPhone?: string
  onDevCodes?: (email?: string, phone?: string) => void
}

export default function DualVerifyFields({
  emailCode, onEmailCode, devEmail, onDevCodes,
}: Props) {
  const { t } = useI18n()
  const [countdown, setCountdown] = useState(0)
  const [error, setError] = useState('')

  const sendCodes = async () => {
    setError('')
    try {
      const res = await authApi.sendSecurityCodes()
      onDevCodes?.(res.dev_email_code, undefined)
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
    <div className="security-notice dual-verify-panel">
      <p className="dual-verify-lead">{t('security.emailOnlyTitle')}</p>
      <button type="button" className="btn btn-ghost dual-verify-send"
        disabled={countdown > 0} onClick={sendCodes}>
        {countdown > 0 ? t('security.resendIn', { n: countdown }) : t('security.getCodes')}
      </button>
      {devEmail && (
        <p className="text-muted dual-verify-dev">
          {t('security.devMode')} — {t('common.email')}: {devEmail}
        </p>
      )}
      <div className="dual-verify-codes dual-verify-codes--single">
        <input className="input" placeholder={t('security.emailCodePh')} value={emailCode}
          onChange={e => onEmailCode(e.target.value)} required />
      </div>
      {error && <p className="text-red dual-verify-error">{error}</p>}
    </div>
  )
}
