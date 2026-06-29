import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import GlassCard from './GlassCard'
import { useI18n } from '../i18n'

type Props = {
  children?: ReactNode
  className?: string
}

/** Shared withdraw CTA — Referrals · Settlements · Profile */
export default function WithdrawCta({ children, className }: Props) {
  const { t } = useI18n()
  return (
    <GlassCard className={`p-4 section-mb-lg withdraw-cta ${className ?? ''}`}>
      {children}
      <p className="text-muted text-sm withdraw-cta-hint">{t('withdraw.ctaHint')}</p>
      <Link to="/withdraw" className="btn btn-primary btn-link">{t('withdraw.ctaButton')}</Link>
    </GlassCard>
  )
}
