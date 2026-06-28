import { Link } from 'react-router-dom'
import LandingNav from './landing/LandingNav'
import LandingFooter from './landing/LandingFooter'
import TopToolbar from './TopToolbar'
import ScrollReveal from './ui/ScrollReveal'
import ParticleBackground from './ui/ParticleBackground'
import { useI18n } from '../i18n'
import { ChevronLeft } from 'lucide-react'

interface Props {
  titleKey: string
  updatedKey: string
  sectionKeys: readonly string[]
  ns: 'privacy' | 'terms'
}

export default function LegalLayout({ titleKey, updatedKey, sectionKeys, ns }: Props) {
  const t = useI18n(s => s.t)

  return (
    <div className="legal-page">
      <div className="legal-bg-grid" aria-hidden />
      <TopToolbar />
      <LandingNav />

      <header className="legal-hero">
        <ParticleBackground />
        <ScrollReveal className="legal-hero-inner">
          <Link to="/" className="legal-back"><ChevronLeft size={16} /> {t('auth.backHome')}</Link>
          <h1>{t(titleKey)}</h1>
          <p className="text-muted">{t(updatedKey)}</p>
        </ScrollReveal>
      </header>

      <article className="legal-content glass">
        {sectionKeys.map((key, i) => (
          <ScrollReveal key={key} delay={i * 0.04} className="legal-section">
            <h2>{t(`legal.${ns}.sections.${key}.title`)}</h2>
            <p>{t(`legal.${ns}.sections.${key}.body`)}</p>
          </ScrollReveal>
        ))}
        <p className="legal-footer-note">{t('landing.footer.riskDisclaimer')}</p>
      </article>

      <LandingFooter />
    </div>
  )
}
