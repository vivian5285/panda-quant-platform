import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import FaqSection from '../components/landing/FaqSection'
import { useI18n } from '../i18n'
import { BookOpen, Mail, MessageSquare } from 'lucide-react'

export default function Help() {
  const t = useI18n(s => s.t)

  return (
    <Layout>
      <PageHeader title={t('nav.help')} subtitle={t('help.subtitle')} />
      <div className="help-cards">
        {[
          { icon: BookOpen, title: t('help.docs'), desc: t('help.docsDesc') },
          { icon: MessageSquare, title: t('help.support'), desc: t('help.supportDesc') },
          { icon: Mail, title: t('help.contact'), desc: t('help.contactDesc') },
        ].map(({ icon: Icon, title, desc }, i) => (
          <GlassCard key={title} className="p-6 help-card" delay={i * 0.06}>
            <Icon size={24} className="text-green" />
            <h3>{title}</h3>
            <p className="text-muted">{desc}</p>
          </GlassCard>
        ))}
      </div>
      <div style={{ marginTop: 32 }}>
        <FaqSection />
      </div>
    </Layout>
  )
}
