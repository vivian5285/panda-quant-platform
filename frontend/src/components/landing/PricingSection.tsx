import { Link } from 'react-router-dom'
import { Check } from 'lucide-react'
import ScrollReveal from '../ui/ScrollReveal'
import { useI18n } from '../../i18n'

const PLANS = ['starter', 'pro', 'vip'] as const

export default function PricingSection() {
  const t = useI18n(s => s.t)

  return (
    <section id="pricing" className="landing-section landing-section-alt">
      <ScrollReveal className="landing-section-head">
        <p className="landing-kicker">{t('landing.pricing.kicker')}</p>
        <h2>{t('landing.pricing.title')}</h2>
        <p>{t('landing.pricing.subtitle')}</p>
      </ScrollReveal>
      <div className="pricing-grid">
        {PLANS.map((plan, i) => (
          <ScrollReveal key={plan} delay={i * 0.07} className={`pricing-card glass ${plan === 'pro' ? 'pricing-card-popular' : ''}`}>
            {plan === 'pro' && <span className="pricing-badge">{t('landing.pricing.popular')}</span>}
            <h3>{t(`billing.plans.${plan}.name`)}</h3>
            <p className="pricing-price">{t(`billing.plans.${plan}.price`)}</p>
            <ul>
              {(['f1', 'f2', 'f3'] as const).map(f => (
                <li key={f}><Check size={14} /> {t(`billing.plans.${plan}.${f}`)}</li>
              ))}
            </ul>
            <Link to="/register" className={`btn ${plan === 'pro' ? 'btn-primary' : 'btn-secondary'} ripple-btn`}>
              {t('landing.pricing.cta')}
            </Link>
          </ScrollReveal>
        ))}
      </div>
    </section>
  )
}
