import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import GeminiLogo from './GeminiLogo'

interface Props {
  to?: string | null
  showTagline?: boolean
  className?: string
  logoSize?: 'sm' | 'md' | 'lg'
}

export default function FramerBrand({ to = '/', showTagline = false, className = '', logoSize = 'md' }: Props) {
  const t = useI18n(s => s.t)
  const inner = (
    <>
      <GeminiLogo size={logoSize} />
      <span className="framer-logo-text">
        <strong>{t('brand.name')}</strong>
        {showTagline && <small>{t('brand.tagline')}</small>}
      </span>
    </>
  )
  if (to === null || to === undefined) {
    return <div className={`framer-logo ${className}`}>{inner}</div>
  }
  return (
    <Link to={to} className={`framer-logo ${className}`}>
      {inner}
    </Link>
  )
}
