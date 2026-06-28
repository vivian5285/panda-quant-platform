import { Bot, Radar, Receipt } from 'lucide-react'
import ScrollReveal from '../ui/ScrollReveal'
import { useI18n } from '../../i18n'

const AGENTS = [
  { key: 'signal' as const, icon: Bot },
  { key: 'risk' as const, icon: Radar },
  { key: 'settle' as const, icon: Receipt },
]

export default function AiAgentsSection() {
  const t = useI18n(s => s.t)

  return (
    <section id="agents" className="landing-section">
      <ScrollReveal className="landing-section-head">
        <p className="landing-kicker">{t('landing.agents.kicker')}</p>
        <h2>{t('landing.agents.title')}</h2>
        <p>{t('landing.agents.subtitle')}</p>
      </ScrollReveal>
      <div className="agents-grid">
        {AGENTS.map(({ key, icon: Icon }, i) => (
          <ScrollReveal key={key} delay={i * 0.08} className="agent-card glass">
            <div className="agent-card-icon"><Icon size={22} /></div>
            <h3>{t(`landing.agents.items.${key}.title`)}</h3>
            <p>{t(`landing.agents.items.${key}.desc`)}</p>
            <div className="agent-card-mock">
              <span className="agent-dot" />
              <span>{t(`landing.agents.items.${key}.status`)}</span>
            </div>
          </ScrollReveal>
        ))}
      </div>
    </section>
  )
}
