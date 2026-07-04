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

type GuideStep = {
  id: string
  image?: string
  substeps?: string[]
}

/** 币安 ①–⑬ + GEMINI ⑭–⑰，与截图标注序号一致 */
const BINANCE_STEPS: GuideStep[] = [
  { id: 'bn1', image: '/guides/api-binding/step-bn-01-futures.png', substeps: ['s1', 's2', 's3', 's4'] },
  { id: 'bn2', substeps: ['s5'] },
  { id: 'bn3', substeps: ['s6'] },
  { id: 'bn4', substeps: ['s7', 's8'] },
  { id: 'bn5', substeps: ['s9'] },
  { id: 'bn6', substeps: ['s10'] },
  { id: 'bn7', image: '/guides/api-binding/step-bn-07-permissions.png', substeps: ['s11', 's12', 's13'] },
]

const GEMINI_STEPS: GuideStep[] = [
  { id: 'gem1', image: '/guides/api-binding/step-gem-01-sidebar.png', substeps: ['s14'] },
  { id: 'gem2', image: '/guides/api-binding/step-gem-02-exchange.png', substeps: ['s15'] },
  { id: 'gem3', image: '/guides/api-binding/step-gem-03-paste-keys.png', substeps: ['s16'] },
  { id: 'gem4', image: '/guides/api-binding/step-gem-04-verify-bind.png', substeps: ['s17'] },
]

const CHECKLIST_KEYS = ['futures', 'noWithdraw', 'oneWay', 'balance', 'ip'] as const

const TOC_IDS = [
  ...BINANCE_STEPS.flatMap(s => s.substeps || []),
  ...GEMINI_STEPS.flatMap(s => s.substeps || []),
]

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

function StepCard({
  step,
  startIndex,
}: {
  step: GuideStep
  startIndex: number
}) {
  const { t } = useTranslation()
  const substeps = step.substeps || []
  const caption = t(`apiBindingGuide.steps.${step.id}.caption`)
  const tip = t(`apiBindingGuide.steps.${step.id}.tip`)

  return (
    <article className="abg-step-card" id={`step-${step.id}`}>
      <div className="abg-step-head">
        <span className="abg-step-num">{startIndex}</span>
        <div>
          <p className="abg-step-badge">{t(`apiBindingGuide.steps.${step.id}.badge`)}</p>
          <h3>{t(`apiBindingGuide.steps.${step.id}.title`)}</h3>
          <p className="text-muted abg-step-lead">{t(`apiBindingGuide.steps.${step.id}.body`)}</p>
        </div>
      </div>

      {substeps.length > 0 && (
        <ol className="abg-substeps">
          {substeps.map((sid, i) => (
            <li key={sid} id={`step-${sid}`}>
              <span className="abg-substep-index">{startIndex + i}</span>
              <span>{t(`apiBindingGuide.substeps.${sid}`)}</span>
            </li>
          ))}
        </ol>
      )}

      {step.image && (
        <figure className="abg-step-figure">
          <img
            src={step.image}
            alt={t(`apiBindingGuide.steps.${step.id}.title`)}
            loading="lazy"
            decoding="async"
          />
          {caption && (
            <figcaption className="text-muted text-xs">{caption}</figcaption>
          )}
        </figure>
      )}

      {tip && (
        <p className="abg-step-tip">
          <ChevronRight size={14} />
          {tip}
        </p>
      )}
    </article>
  )
}

function GuideContent() {
  const { t } = useTranslation()
  const token = useAuth(s => s.token)

  let stepCounter = 0
  const renderPhase = (steps: GuideStep[], phaseKey: 'binance' | 'gemini') => {
    const cards = steps.map(step => {
      const subCount = step.substeps?.length || 1
      const start = stepCounter + 1
      stepCounter += subCount
      return <StepCard key={step.id} step={step} startIndex={start} />
    })
    return (
      <section className="abg-phase section-mb-lg">
        <div className="abg-phase-head">
          <span className={`abg-phase-badge abg-phase-badge-${phaseKey === 'binance' ? 'binance' : 'gemini'}`}>
            {phaseKey === 'binance' ? 'A' : 'B'}
          </span>
          <div>
            <h2>{t(`apiBindingGuide.phase${phaseKey === 'binance' ? 'Binance' : 'Gemini'}Title`)}</h2>
            <p className="text-muted text-sm">
              {t(`apiBindingGuide.phase${phaseKey === 'binance' ? 'Binance' : 'Gemini'}Desc`)}
            </p>
          </div>
        </div>
        <div className="abg-steps">{cards}</div>
      </section>
    )
  }

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

      <GlassCard className="p-5 section-mb-lg abg-toc-card">
        <h3 className="abg-toc-title">{t('apiBindingGuide.tocTitle')}</h3>
        <ol className="abg-toc">
          {TOC_IDS.map((sid, i) => (
            <li key={sid}>
              <a href={`#step-${sid}`}>
                <span className="abg-toc-num">{i + 1}</span>
                {t(`apiBindingGuide.substeps.${sid}`)}
              </a>
            </li>
          ))}
        </ol>
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

      {renderPhase(BINANCE_STEPS, 'binance')}
      {renderPhase(GEMINI_STEPS, 'gemini')}

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
