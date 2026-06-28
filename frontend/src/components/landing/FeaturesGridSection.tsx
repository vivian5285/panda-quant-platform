import { Brain, Layers, Coins, Zap, CalendarCheck, Shield } from 'lucide-react'
import ScrollReveal from '../ui/ScrollReveal'
import { useI18n } from '../../i18n'

const FEATURES = [
  { key: 'ai' as const, icon: Brain },
  { key: 'strategy' as const, icon: Layers },
  { key: 'crypto' as const, icon: Coins },
  { key: 'execution' as const, icon: Zap },
  { key: 'settlement' as const, icon: CalendarCheck },
  { key: 'security' as const, icon: Shield },
]

export default function FeaturesGridSection() {
  const t = useI18n(s => s.t)

  return (
    <section id="features" className="landing-section">
      <ScrollReveal className="landing-section-head">
        <p className="landing-kicker">{t('landing.features.kicker')}</p>
        <h2>{t('landing.features.title')}</h2>
        <p>{t('landing.features.subtitle')}</p>
      </ScrollReveal>
      <div className="features-premium-grid">
        {FEATURES.map(({ key, icon: Icon }, i) => (
          <ScrollReveal key={key} delay={i * 0.05} className="feature-premium-card glass">
            <div className="feature-premium-icon"><Icon size={20} /></div>
            <h3>{t(`landing.features.items.${key}.title`)}</h3>
            <p>{t(`landing.features.items.${key}.desc`)}</p>
          </ScrollReveal>
        ))}
      </div>
    </section>
  )
}
