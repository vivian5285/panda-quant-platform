import { Quote } from 'lucide-react'
import { motion } from 'framer-motion'
import { useI18n } from '../../i18n'
import ScrollReveal from '../ui/ScrollReveal'

const KEYS = ['a', 'b', 'c'] as const

export default function TestimonialsSection() {
  const t = useI18n(s => s.t)

  return (
    <section className="landing-section landing-section-alt">
      <ScrollReveal className="landing-section-head">
        <p className="landing-kicker">{t('saas.testimonials.kicker')}</p>
        <h2>{t('saas.testimonials.title')}</h2>
      </ScrollReveal>
      <div className="testimonial-track">
        {[...KEYS, ...KEYS].map((key, i) => (
          <motion.div
            key={`${key}-${i}`}
            className="testimonial-card glass"
            whileHover={{ scale: 1.03, rotateY: 4 }}
          >
            <Quote size={20} className="testimonial-quote" />
            <p>{t(`saas.testimonials.items.${key}.text`)}</p>
            <div className="testimonial-author">
              <span className="testimonial-avatar">{t(`saas.testimonials.items.${key}.name`).charAt(0)}</span>
              <div>
                <strong>{t(`saas.testimonials.items.${key}.name`)}</strong>
                <span>{t(`saas.testimonials.items.${key}.role`)}</span>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </section>
  )
}
