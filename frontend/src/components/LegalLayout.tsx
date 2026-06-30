import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import FramerBrand from './FramerBrand'
import TopToolbar from './TopToolbar'
import { ChevronLeft } from 'lucide-react'

interface Props {
  titleKey: string
  updatedKey: string
  sectionKeys: readonly string[]
  ns: 'privacy' | 'terms'
}

export default function LegalLayout({ titleKey, updatedKey, sectionKeys, ns }: Props) {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)

  return (
    <div className="legal-page" key={locale}>
      <header className="framer-public-nav">
        <FramerBrand />
        <TopToolbar />
      </header>

      <header className="legal-hero">
        <Link to="/" className="legal-back"><ChevronLeft size={16} /> {t('auth.backHome')}</Link>
        <h1>{t(titleKey)}</h1>
        <p className="text-muted">{t(updatedKey)}</p>
      </header>

      <article className="legal-content">
        {sectionKeys.map(key => (
          <section key={key} className="legal-section">
            <h2>{t(`legal.${ns}.sections.${key}.title`)}</h2>
            <p>{t(`legal.${ns}.sections.${key}.body`)}</p>
          </section>
        ))}
        <p className="legal-footer-note">{t('framer.footer.risk')}</p>
      </article>

      <footer className="framer-legal-footer">
        <FramerBrand />
        <div className="framer-legal-links">
          <Link to="/privacy">{t('framer.footer.privacy')}</Link>
          <Link to="/terms">{t('framer.footer.terms')}</Link>
          <Link to="/guide">{t('nav.guide')}</Link>
          <Link to="/help">{t('nav.help')}</Link>
        </div>
        <p>{t('framer.footer.rights')}</p>
      </footer>
    </div>
  )
}
