import { Link } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import FramerLandingFAQ from '../components/landing/framer/FramerLandingFAQ'
import Layout from '../components/Layout'
import FramerPublicShell from '../components/FramerPublicShell'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { BookOpen, Mail, MessageSquare, ShieldCheck } from 'lucide-react'

const SUPPORT_EMAIL = 'support@gemini-quant.com'

function HelpContent() {
  const t = useI18n(s => s.t)

  const cards = [
    { icon: BookOpen, title: t('help.docs'), desc: t('help.docsDesc'), to: '/api' as const },
    { icon: MessageSquare, title: t('help.support'), desc: t('help.supportDesc'), href: `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(t('help.support'))}` },
    { icon: Mail, title: t('help.contact'), desc: t('help.contactDesc'), href: `mailto:${SUPPORT_EMAIL}` },
  ]

  const transparencyKeys = ['howTrade', 'fees', 'pause', 'risk'] as const

  return (
    <>
      <PageHeader title={t('nav.help')} subtitle={t('help.subtitle')} />

      <div className="help-cards">
        {cards.map(({ icon: Icon, title, desc, href, to }, i) => {
          const inner = (
            <GlassCard className="p-6 help-card" delay={i * 0.06}>
              <Icon size={24} />
              <h3>{title}</h3>
              <p className="text-muted">{desc}</p>
            </GlassCard>
          )
          if (to) {
            return (
              <Link key={title} to={to} className="help-card-link">{inner}</Link>
            )
          }
          return (
            <a key={title} href={href} className="help-card-link" target="_blank" rel="noopener noreferrer">{inner}</a>
          )
        })}
      </div>

      <section className="help-transparency section-mb-lg">
        <div className="strategies-section-head">
          <p className="framer-kicker">TRANSPARENCY</p>
          <h2>{t('help.transparencyTitle')}</h2>
        </div>
        <div className="help-transparency-grid">
          {transparencyKeys.map((key, i) => (
            <GlassCard key={key} className="p-6 help-transparency-card" delay={i * 0.05}>
              <ShieldCheck size={20} className="strategies-icon" />
              <h3>{t(`help.transparencyItems.${key}.title`)}</h3>
              <p className="text-muted">{t(`help.transparencyItems.${key}.desc`)}</p>
            </GlassCard>
          ))}
        </div>
      </section>

      <div className="help-faq-wrap">
        <FramerLandingFAQ />
      </div>
    </>
  )
}

export default function Help() {
  const token = useAuth(s => s.token)

  if (token) {
    return (
      <Layout>
        <HelpContent />
      </Layout>
    )
  }

  return (
    <FramerPublicShell>
      <main className="public-content">
        <HelpContent />
      </main>
    </FramerPublicShell>
  )
}
