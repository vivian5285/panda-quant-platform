import { useEffect } from 'react'
import { X } from 'lucide-react'
import { useI18n } from '../../../i18n'
import FramerDemoAnimation from './FramerDemoAnimation'

type Props = {
  open: boolean
  onClose: () => void
}

export default function WatchDemoModal({ open, onClose }: Props) {
  const t = useI18n(s => s.t)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="framer-demo-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={t('framer.hero.demoModalTitle')}
      onClick={onClose}
    >
      <div className="framer-demo-modal framer-demo-modal-showcase" onClick={e => e.stopPropagation()}>
        <div className="framer-demo-modal-head">
          <span>{t('framer.hero.demoModalTitle')}</span>
          <button
            type="button"
            className="framer-demo-close"
            onClick={onClose}
            aria-label={t('framer.hero.demoModalClose')}
          >
            <X size={18} />
          </button>
        </div>
        <div className="framer-demo-modal-body">
          <FramerDemoAnimation />
          <p className="framer-demo-modal-hint">{t('framer.hero.demoModalHint')}</p>
        </div>
      </div>
    </div>
  )
}
