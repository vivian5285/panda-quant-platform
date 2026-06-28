import { Link } from 'react-router-dom'
import { ArrowUpRight } from 'lucide-react'
import { useI18n } from '../../../i18n'
import ScrollReveal from '../../ui/ScrollReveal'

const STORIES = ['atlas', 'vertex', 'pulse', 'northstar'] as const

const GRADIENTS: Record<(typeof STORIES)[number], string> = {
  atlas: 'linear-gradient(135deg, #1e3a8a 0%, #60a5fa 50%, #dbeafe 100%)',
  vertex: 'linear-gradient(135deg, #0f172a 0%, #334155 45%, #94a3b8 100%)',
  pulse: 'linear-gradient(135deg, #064e3b 0%, #059669 50%, #a7f3d0 100%)',
  northstar: 'linear-gradient(135deg, #312e81 0%, #6366f1 55%, #c7d2fe 100%)',
}

export default function FramerCustomerStories() {
  const t = useI18n(s => s.t)

  return (
    <ScrollReveal delay={0.12} y={32}>
      <div className="framer-stories-grid">
        {STORIES.map((key, i) => (
          <Link
            key={key}
            to="/help"
            className="framer-story-card"
            style={{ animationDelay: `${i * 0.06}s` }}
          >
            <div className="framer-story-visual" style={{ background: GRADIENTS[key] }}>
              <div className="framer-story-mock">
                <span className="framer-story-mock-bar" />
                <span className="framer-story-mock-bar short" />
                <span className="framer-story-mock-chart" />
              </div>
              <span className="framer-story-badge">{t(`framer.partners.stories.${key}.badge`)}</span>
            </div>
            <div className="framer-story-body">
              <div className="framer-story-head">
                <strong>{t(`framer.partners.stories.${key}.company`)}</strong>
                <ArrowUpRight size={16} className="framer-story-arrow" />
              </div>
              <p className="framer-story-metric">{t(`framer.partners.stories.${key}.metric`)}</p>
              <p className="framer-story-quote">{t(`framer.partners.stories.${key}.quote`)}</p>
              <span className="framer-story-read">{t('framer.partners.stories.read')}</span>
            </div>
          </Link>
        ))}
      </div>
    </ScrollReveal>
  )
}
