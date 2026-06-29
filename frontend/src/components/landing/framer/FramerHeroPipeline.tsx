import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'
import { useAuth } from '../../../store/auth'
import FramerHeroBackdrop from './FramerHeroBackdrop'
import FramerHeroCanvas from './FramerHeroCanvas'
import FramerCryptoTicker from './FramerCryptoTicker'
import WatchDemoModal from './WatchDemoModal'
import RippleButton from '../../ui/RippleButton'

const heroEase = [0.22, 1, 0.36, 1] as const

export default function FramerHeroPipeline() {
  const t = useI18n(s => s.t)
  const token = useAuth(s => s.token)
  const reduceMotion = useReducedMotion()
  const [demoOpen, setDemoOpen] = useState(false)

  const item = (delay: number) =>
    reduceMotion
      ? {}
      : {
          initial: { opacity: 0, y: 28 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.65, delay, ease: heroEase },
        }

  return (
    <div className="framer-hero-zone framer-hero-zone-stacked">
      <FramerHeroBackdrop />
      <FramerCryptoTicker />
      <section className="framer-hero-stacked">
        <motion.div className="framer-pill" {...item(0.05)}>
          {t('framer.hero.pill')}
        </motion.div>
        <motion.h1 {...item(0.12)}>
          <span className="framer-title-line">{t('framer.hero.titleLine1')}</span>
          <span className="framer-title-line">{t('framer.hero.titleLine2')}</span>
        </motion.h1>
        <motion.p className="framer-hero-sub framer-hero-sub-stacked" {...item(0.2)}>
          {t('framer.hero.subtitle')}
        </motion.p>
        <motion.div className="framer-hero-cta-row" {...item(0.28)}>
          <div className="framer-hero-cta framer-hero-cta-left">
            <Link to={token ? '/dashboard' : '/register'} className="framer-btn-primary framer-btn-white framer-btn-glow">
              {t('framer.hero.ctaPrimary')}
            </Link>
            <RippleButton type="button" className="framer-btn-secondary" onClick={() => setDemoOpen(true)}>
              {t('framer.hero.ctaSecondary')}
            </RippleButton>
          </div>
          <Link
            to="#agents"
            className="framer-hero-version-link"
            onClick={e => { e.preventDefault(); document.getElementById('agents')?.scrollIntoView({ behavior: 'smooth' }) }}
          >
            {t('framer.hero.versionLink')} →
          </Link>
        </motion.div>

        <motion.div className="framer-hero-mockup-full" {...item(0.38)}>
          <FramerHeroCanvas />
        </motion.div>
      </section>
      <WatchDemoModal open={demoOpen} onClose={() => setDemoOpen(false)} />
    </div>
  )
}
