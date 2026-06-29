import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { useToastStore } from '../../store/toast'

const ICONS = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
} as const

export default function ToastHost() {
  const toasts = useToastStore(s => s.toasts)
  const dismiss = useToastStore(s => s.dismiss)

  if (!toasts.length) return null

  return (
    <div className="toast-host" aria-live="polite">
      {toasts.map(item => {
        const Icon = ICONS[item.type]
        return (
          <div key={item.id} className={`toast-item toast-${item.type}`} role="status">
            <Icon size={18} className="toast-icon" aria-hidden />
            <span className="toast-text">{item.message}</span>
            <button type="button" className="toast-close" onClick={() => dismiss(item.id)} aria-label="Close">
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
