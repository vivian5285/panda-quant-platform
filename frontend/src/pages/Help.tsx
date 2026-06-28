import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import FaqSection from '../components/landing/FaqSection'
import Layout from '../components/Layout'
import FramerPublicShell from '../components/FramerPublicShell'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { BookOpen, Mail, MessageSquare } from 'lucide-react'

function HelpContent() {
  const t = useI18n(s => s.t)

  return (
    <>
      <PageHeader title={t('nav.help')} subtitle={t('help.subtitle')} />
      <div className="help-cards">
        {[
          { icon: BookOpen, title: t('help.docs'), desc: t('help.docsDesc') },
          { icon: MessageSquare, title: t('help.support'), desc: t('help.supportDesc') },
          { icon: Mail, title: t('help.contact'), desc: t('help.contactDesc') },
        ].map(({ icon: Icon, title, desc }, i) => (
          <GlassCard key={title} className="p-6 help-card" delay={i * 0.06}>
            <Icon size={24} />
            <h3>{title}</h3>
            <p className="text-muted">{desc}</p>
          </GlassCard>
        ))}
      </div>
      <div style={{ marginTop: 32, maxWidth: 720, marginLeft: 'auto', marginRight: 'auto' }}>
        <FaqSection />
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
      <main style={{ maxWidth: 960, margin: '0 auto', padding: '32px 24px 64px' }}>
        <HelpContent />
      </main>
    </FramerPublicShell>
  )
}
