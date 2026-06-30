import { Link } from 'react-router-dom'
import {
  Bot, Shield, LineChart, Users, CheckCircle2, ArrowRight,
  Layers, Eye, Wallet,
} from 'lucide-react'
import Layout from '../components/Layout'
import FramerPublicShell from '../components/FramerPublicShell'
import GlassCard from '../components/GlassCard'
import PageHeader from '../components/PageHeader'
import FramerBrand from '../components/FramerBrand'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'

const HOSTING_STEPS = ['s1', 's2', 's3', 's4'] as const
const LOGIC_ITEMS = ['signal', 'risk', 'execute', 'audit'] as const
const PHILOSOPHY_ITEMS = ['discipline', 'trend', 'nonCustodial', 'transparent'] as const
const PARTNER_STEPS = ['p1', 'p2', 'p3'] as const

function GuideFooter() {
  const t = useI18n(s => s.t)
  return (
    <footer className="framer-legal-footer platform-guide-public-footer">
      <FramerBrand />
      <div className="framer-legal-links">
        <Link to="/privacy">{t('framer.footer.privacy')}</Link>
        <Link to="/terms">{t('framer.footer.terms')}</Link>
        <Link to="/help">{t('nav.help')}</Link>
      </div>
      <p className="text-muted text-xs">{t('platformGuide.disclaimer')}</p>
    </footer>
  )
}

function GuideContent() {
  const t = useI18n(s => s.t)

  return (
    <div className="platform-guide">
      <PageHeader title={t('platformGuide.title')} subtitle={t('platformGuide.subtitle')} />

      <GlassCard className="p-6 section-mb-lg platform-guide-hero">
        <p className="framer-kicker">{t('platformGuide.kicker')}</p>
        <h2 className="platform-guide-hero-title">{t('platformGuide.heroTitle')}</h2>
        <p className="text-muted platform-guide-lead">{t('platformGuide.heroLead')}</p>
        <div className="platform-guide-hero-actions">
          <Link to="/register" className="btn btn-primary">{t('platformGuide.ctaRegister')}</Link>
          <Link to="/help" className="btn btn-ghost">{t('nav.help')}</Link>
        </div>
      </GlassCard>

      <section className="platform-guide-section">
        <div className="platform-guide-section-head">
          <Layers size={22} />
          <h2>{t('platformGuide.logicTitle')}</h2>
        </div>
        <p className="text-muted section-mb-sm">{t('platformGuide.logicIntro')}</p>
        <div className="platform-guide-grid">
          {LOGIC_ITEMS.map(key => (
            <GlassCard key={key} className="p-5 platform-guide-card">
              <h3>{t(`platformGuide.logicItems.${key}.title`)}</h3>
              <p className="text-muted text-sm">{t(`platformGuide.logicItems.${key}.desc`)}</p>
            </GlassCard>
          ))}
        </div>
      </section>

      <section className="platform-guide-section">
        <div className="platform-guide-section-head">
          <LineChart size={22} />
          <h2>{t('platformGuide.philosophyTitle')}</h2>
        </div>
        <p className="text-muted section-mb-sm">{t('platformGuide.philosophyIntro')}</p>
        <div className="platform-guide-grid">
          {PHILOSOPHY_ITEMS.map(key => (
            <GlassCard key={key} className="p-5 platform-guide-card">
              <CheckCircle2 size={18} className="platform-guide-icon" />
              <h3>{t(`platformGuide.philosophyItems.${key}.title`)}</h3>
              <p className="text-muted text-sm">{t(`platformGuide.philosophyItems.${key}.desc`)}</p>
            </GlassCard>
          ))}
        </div>
      </section>

      <section className="platform-guide-section">
        <div className="platform-guide-section-head">
          <Bot size={22} />
          <h2>{t('platformGuide.hostingTitle')}</h2>
        </div>
        <p className="text-muted section-mb-md">{t('platformGuide.hostingIntro')}</p>
        <div className="platform-guide-steps">
          {HOSTING_STEPS.map((key, i) => (
            <GlassCard key={key} className="p-5 platform-guide-step">
              <span className="platform-guide-step-num">{i + 1}</span>
              <div>
                <h3>{t(`platformGuide.hostingSteps.${key}.title`)}</h3>
                <p className="text-muted text-sm">{t(`platformGuide.hostingSteps.${key}.desc`)}</p>
              </div>
            </GlassCard>
          ))}
        </div>
      </section>

      <section className="platform-guide-section">
        <div className="platform-guide-section-head">
          <Users size={22} />
          <h2>{t('platformGuide.partnerTitle')}</h2>
        </div>
        <p className="text-muted section-mb-sm">{t('platformGuide.partnerIntro')}</p>
        <GlassCard className="p-6 section-mb-md platform-guide-note">
          <p className="text-sm text-muted">{t('platformGuide.partnerNote')}</p>
        </GlassCard>
        <div className="platform-guide-steps platform-guide-steps-compact">
          {PARTNER_STEPS.map((key, i) => (
            <GlassCard key={key} className="p-5 platform-guide-step">
              <span className="platform-guide-step-num">{i + 1}</span>
              <div>
                <h3>{t(`platformGuide.partnerSteps.${key}.title`)}</h3>
                <p className="text-muted text-sm">{t(`platformGuide.partnerSteps.${key}.desc`)}</p>
              </div>
            </GlassCard>
          ))}
        </div>
      </section>

      <section className="platform-guide-section">
        <div className="platform-guide-section-head">
          <Shield size={22} />
          <h2>{t('platformGuide.complianceTitle')}</h2>
        </div>
        <GlassCard className="p-6 platform-guide-compliance">
          <ul className="platform-guide-list">
            {[1, 2, 3, 4, 5].map(n => (
              <li key={n}>{t(`platformGuide.complianceItems.c${n}`)}</li>
            ))}
          </ul>
        </GlassCard>
      </section>

      <GlassCard className="p-6 platform-guide-final">
        <div className="platform-guide-final-grid">
          <div className="platform-guide-final-col">
            <Eye size={20} className="platform-guide-icon" />
            <h3>{t('platformGuide.finalHostTitle')}</h3>
            <p className="text-muted text-sm">{t('platformGuide.finalHostDesc')}</p>
            <Link to="/register" className="btn btn-primary btn-sm section-mt-sm">
              {t('platformGuide.ctaHost')} <ArrowRight size={14} />
            </Link>
          </div>
          <div className="platform-guide-final-col">
            <Wallet size={20} className="platform-guide-icon" />
            <h3>{t('platformGuide.finalPartnerTitle')}</h3>
            <p className="text-muted text-sm">{t('platformGuide.finalPartnerDesc')}</p>
            <Link to="/register" className="btn btn-ghost btn-sm section-mt-sm">
              {t('platformGuide.ctaPartner')} <ArrowRight size={14} />
            </Link>
          </div>
        </div>
        <p className="text-muted text-xs platform-guide-disclaimer">{t('platformGuide.disclaimer')}</p>
      </GlassCard>
    </div>
  )
}

export default function PlatformGuide() {
  const token = useAuth(s => s.token)
  if (token) {
    return (
      <Layout>
        <GuideContent />
      </Layout>
    )
  }
  return (
    <FramerPublicShell>
      <main className="framer-public-main platform-guide-public">
        <GuideContent />
        <GuideFooter />
      </main>
    </FramerPublicShell>
  )
}
