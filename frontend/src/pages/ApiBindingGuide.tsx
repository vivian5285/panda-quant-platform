import { Link } from 'react-router-dom'
import {
  ArrowRight, BookOpen, CheckCircle2, ChevronRight, KeyRound,
  Shield, ClipboardCheck, Wallet, ExternalLink,
} from 'lucide-react'
import Layout from '../components/Layout'
import FramerPublicShell from '../components/FramerPublicShell'
import GlassCard from '../components/GlassCard'
import PageHeader from '../components/PageHeader'
import FramerBrand from '../components/FramerBrand'
import { useAuth } from '../store/auth'
import { useTranslation } from '../i18n'

const BINANCE_STEP_IDS = ['bn1', 'bn2', 'bn3', 'bn4', 'bn5', 'bn6', 'bn7', 'bn8'] as const
const GEMINI_STEP_IDS = ['gem1', 'gem2', 'gem3', 'gem4'] as const

const STEP_IMAGES: Partial<Record<string, string>> = {
  bn1: '/guides/api-binding/step-bn-01-futures.png',
  gem1: '/guides/api-binding/step-gem-01-sidebar.png',
  gem2: '/guides/api-binding/step-gem-02-exchange.png',
  gem3: '/guides/api-binding/step-gem-03-paste-keys.png',
  gem4: '/guides/api-binding/step-gem-04-verify-bind.png',
}

const CHECKLIST_KEYS = ['futures', 'noWithdraw', 'oneWay', 'balance', 'ip'] as const

function GuideFooter() {
  const { t } = useTranslation()
  return (
    <footer className="framer-legal-footer platform-guide-public-footer">
      <FramerBrand />
      <div className="framer-legal-links">
        <Link to="/privacy">{t('framer.footer.privacy')}</Link>
        <Link to="/terms">{t('framer.footer.terms')}</Link>
        <Link to="/help">{t('nav.help')}</Link>
        <Link to="/api-guide">{t('apiBindingGuide.title')}</Link>
      </div>
      <p className="text-muted text-xs">{t('apiBindingGuide.disclaimer')}</p>
    </footer>
  )
}

function StepCard({ stepId, index }: { stepId: string; index: number }) {
  const { t } = useTranslation()
  const image = STEP_IMAGES[stepId]
  return (
    <article className="abg-step-card" id={`step-${stepId}`}>
      <div className="abg-step-head">
        <span className="abg-step-num">{index}</span>
        <div>
          <h3>{t(`apiBindingGuide.steps.${stepId}.title`)}</h3>
          <p className="text-muted abg-step-lead">{t(`apiBindingGuide.steps.${stepId}.body`)}</p>
        </div>
      </div>
      {image && (
        <figure className="abg-step-figure">
          <img
            src={image}
            alt={t(`apiBindingGuide.steps.${stepId}.title`)}
            loading="lazy"
            decoding="async"
          />
          <figcaption className="text-muted text-xs">
            {t(`apiBindingGuide.steps.${stepId}.caption`)}
          </figcaption>
        </figure>
      )}
      {t(`apiBindingGuide.steps.${stepId}.tip`) && (
        <p className="abg-step-tip">
          <ChevronRight size={14} />
          {t(`apiBindingGuide.steps.${stepId}.tip`)}
        </p>
      )}
    </article>
  )
}

function GuideContent() {
  const { t } = useTranslation()
  const token = useAuth(s => s.token)

  return (
    <div className="api-binding-guide">
      <PageHeader title={t('apiBindingGuide.title')} subtitle={t('apiBindingGuide.subtitle')} />

      <GlassCard className="p-6 section-mb-lg abg-hero">
        <p className="framer-kicker">{t('apiBindingGuide.kicker')}</p>
        <h2 className="abg-hero-title">{t('apiBindingGuide.heroTitle')}</h2>
        <p className="text-muted abg-hero-lead">{t('apiBindingGuide.heroLead')}</p>
        <div className="abg-hero-actions">
          {token ? (
            <Link to="/api" className="btn btn-primary">
              {t('apiBindingGuide.ctaGoBind')} <ArrowRight size={16} />
            </Link>
          ) : (
            <Link to="/login" className="btn btn-primary">
              {t('apiBindingGuide.ctaLogin')} <ArrowRight size={16} />
            </Link>
          )}
          <a
            href="https://www.binance.com/zh-CN/futures/ETHUSDT"
            className="btn btn-ghost"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t('apiBindingGuide.openBinance')} <ExternalLink size={14} />
          </a>
        </div>
      </GlassCard>

      <GlassCard className="p-5 section-mb-lg abg-checklist-card">
        <div className="abg-checklist-head">
          <Shield size={20} />
          <h3>{t('apiBindingGuide.checklistTitle')}</h3>
        </div>
        <ul className="abg-checklist">
          {CHECKLIST_KEYS.map(key => (
            <li key={key}>
              <CheckCircle2 size={16} className="abg-check-icon" />
              <span>{t(`apiBindingGuide.checklist.${key}`)}</span>
            </li>
          ))}
        </ul>
      </GlassCard>

      <section className="abg-phase section-mb-lg">
        <div className="abg-phase-head">
          <span className="abg-phase-badge abg-phase-badge-binance">A</span>
          <div>
            <h2>{t('apiBindingGuide.phaseBinanceTitle')}</h2>
            <p className="text-muted text-sm">{t('apiBindingGuide.phaseBinanceDesc')}</p>
          </div>
        </div>
        <div className="abg-steps">
          {BINANCE_STEP_IDS.map((id, i) => (
            <StepCard key={id} stepId={id} index={i + 1} />
          ))}
        </div>
      </section>

      <section className="abg-phase section-mb-lg">
        <div className="abg-phase-head">
          <span className="abg-phase-badge abg-phase-badge-gemini">B</span>
          <div>
            <h2>{t('apiBindingGuide.phaseGeminiTitle')}</h2>
            <p className="text-muted text-sm">{t('apiBindingGuide.phaseGeminiDesc')}</p>
          </div>
        </div>
        <div className="abg-steps">
          {GEMINI_STEP_IDS.map((id, i) => (
            <StepCard key={id} stepId={id} index={BINANCE_STEP_IDS.length + i + 1} />
          ))}
        </div>
      </section>

      <GlassCard className="p-6 abg-finish">
        <div className="abg-finish-icons">
          <KeyRound size={22} />
          <ClipboardCheck size={22} />
          <Wallet size={22} />
        </div>
        <h3>{t('apiBindingGuide.finishTitle')}</h3>
        <p className="text-muted">{t('apiBindingGuide.finishDesc')}</p>
        <div className="abg-hero-actions section-mt-sm">
          {token ? (
            <Link to="/api" className="btn btn-primary">
              {t('apiBindingGuide.ctaGoBind')} <ArrowRight size={16} />
            </Link>
          ) : (
            <>
              <Link to="/register" className="btn btn-primary">{t('apiBindingGuide.ctaRegister')}</Link>
              <Link to="/login" className="btn btn-ghost">{t('apiBindingGuide.ctaLogin')}</Link>
            </>
          )}
        </div>
      </GlassCard>

      <p className="text-muted text-xs abg-disclaimer">{t('apiBindingGuide.disclaimer')}</p>
    </div>
  )
}

export default function ApiBindingGuide() {
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
      <main className="framer-public-main api-binding-guide-public">
        <GuideContent />
        <GuideFooter />
      </main>
    </FramerPublicShell>
  )
}

/** Compact banner for ApiManage page */
export function ApiBindingGuideBanner() {
  const { t } = useTranslation()
  return (
    <Link to="/api-guide" className="abg-banner">
      <div className="abg-banner-icon">
        <BookOpen size={22} />
      </div>
      <div className="abg-banner-text">
        <strong>{t('apiBindingGuide.bannerTitle')}</strong>
        <p>{t('apiBindingGuide.bannerDesc')}</p>
      </div>
      <span className="abg-banner-cta">
        {t('apiBindingGuide.bannerCta')} <ArrowRight size={16} />
      </span>
    </Link>
  )
}
