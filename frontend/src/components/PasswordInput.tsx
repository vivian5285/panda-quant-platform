import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { useI18n } from '../i18n'

type Props = {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  minLength?: number
  required?: boolean
  autoComplete?: string
  id?: string
}

export default function PasswordInput({
  value, onChange, placeholder, minLength, required, autoComplete, id,
}: Props) {
  const t = useI18n(s => s.t)
  const [show, setShow] = useState(false)

  return (
    <div className="input-password-wrap">
      <input
        id={id}
        className="input input-password"
        type={show ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        minLength={minLength}
        required={required}
        autoComplete={autoComplete}
      />
      <button
        type="button"
        className="input-password-toggle"
        onClick={() => setShow(v => !v)}
        aria-label={show ? t('auth.hidePassword') : t('auth.showPassword')}
        tabIndex={-1}
      >
        {show ? <EyeOff size={18} /> : <Eye size={18} />}
      </button>
    </div>
  )
}
