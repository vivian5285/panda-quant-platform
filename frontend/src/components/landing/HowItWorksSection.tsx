import { UserPlus, Link2, Zap, Wallet } from 'lucide-react'
import ScrollReveal from '../ui/ScrollReveal'
import { useI18n } from '../../i18n'

const STEPS = [
  { key: 'register' as const, icon: UserPlus, n: '01' },
  { key: 'bind' as const, icon: Link2, n: '02' },
  { key: 'trade' as const, icon: Zap, n: '03' },
  { key: 'settle' as const, icon: Wallet, n: '04' },
]

export default function HowItWorksSection() {
  const t = useI18n(s => s.t)

  return (
    <section id="how" className="landing-section landing-section-alt">
      <ScrollReveal className="landing-section-head">
        <p className="landing-kicker">{t('landing.how.kicker')}</p>
        <h2>{t('landing.how.title')}</h2>
      </ScrollReveal>
      <div className="how-steps-grid">
        {STEPS.map(({ key, icon: Icon, n }, i) => (
          <ScrollReveal key={key} delay={i * 0.06} className="how-step-card glass">
            <div className="how-step-top">
              <span className="how-step-num">{n}</span>
              <Icon size={20} className="text-green" />
            </div>
            <h3>{t(`landing.how.steps.${key}.title`)}</h3>
            <p>{t(`landing.how.steps.${key}.desc`)}</p>
          </ScrollReveal>
        ))}
      </div>
    </section>
  )
}
