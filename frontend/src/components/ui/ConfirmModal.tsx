import { useEffect, useState } from 'react'
import GlassCard from '../GlassCard'
import RippleButton from './RippleButton'
import { useI18n } from '../../i18n'

type Props = {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'primary'
  loading?: boolean
  /** When set, user must type this exact string to enable confirm. */
  confirmPhrase?: string
  confirmPhraseHint?: string
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  variant = 'primary',
  loading = false,
  confirmPhrase,
  confirmPhraseHint,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useI18n()
  const [phrase, setPhrase] = useState('')

  useEffect(() => {
    if (!open) setPhrase('')
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !loading) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, loading, onCancel])

  if (!open) return null

  const phraseOk = !confirmPhrase || phrase === confirmPhrase

  return (
    <div
      className="confirm-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      onClick={() => !loading && onCancel()}
    >
      <div className="confirm-modal-wrap" onClick={e => e.stopPropagation()}>
        <GlassCard className="confirm-modal">
          <h3 id="confirm-modal-title" className="card-heading confirm-modal-title">{title}</h3>
          <p className="confirm-modal-body">{message}</p>
          {confirmPhrase && (
            <div className="confirm-modal-phrase">
              <label htmlFor="confirm-phrase-input">
                {confirmPhraseHint ?? t('common.typeToConfirm', { phrase: confirmPhrase })}
              </label>
              <input
                id="confirm-phrase-input"
                className="input"
                value={phrase}
                onChange={e => setPhrase(e.target.value)}
                placeholder={confirmPhrase}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
          )}
          <div className="confirm-modal-actions">
            <RippleButton className="btn btn-ghost" disabled={loading} onClick={onCancel}>
              {cancelLabel ?? t('common.cancel')}
            </RippleButton>
            <RippleButton
              className={`btn ${variant === 'danger' ? 'btn-danger' : 'btn-primary'}`}
              disabled={loading || !phraseOk}
              onClick={onConfirm}
            >
              {confirmLabel ?? t('common.confirm')}
            </RippleButton>
          </div>
        </GlassCard>
      </div>
    </div>
  )
}
