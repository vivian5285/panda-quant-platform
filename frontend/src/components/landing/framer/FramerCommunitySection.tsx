import { useI18n } from '../../../i18n'
import ScrollReveal from '../../ui/ScrollReveal'

const POSTS = ['a', 'b', 'c', 'd'] as const

export default function FramerCommunitySection() {
  const t = useI18n(s => s.t)

  return (
    <section id="community" className="framer-section framer-community">
      <ScrollReveal>
        <div className="framer-section-head">
          <p className="framer-kicker">{t('framer.community.kicker')}</p>
          <h2>{t('framer.community.title')}</h2>
          <p>{t('framer.community.subtitle')}</p>
        </div>
      </ScrollReveal>

      <ScrollReveal delay={0.08} y={36}>
        <div className="framer-community-shell">
          <div className="framer-community-sidebar">
            <div className="framer-community-search">{t('framer.community.search')}</div>
            {(['explore', 'referrals', 'marketplace'] as const).map((k, i) => (
              <div key={k} className={`framer-community-nav${i === 0 ? ' active' : ''}`}>
                {t(`framer.community.nav.${k}`)}
              </div>
            ))}
          </div>
          <div className="framer-community-feed">
            {POSTS.map(k => (
              <article key={k} className="framer-community-post framer-community-post-hover">
                <div className="framer-community-post-head">
                  <span className="framer-community-avatar" />
                  <div>
                    <strong>{t(`framer.community.posts.${k}.author`)}</strong>
                    <small>{t(`framer.community.posts.${k}.meta`)}</small>
                  </div>
                </div>
                <p>{t(`framer.community.posts.${k}.body`)}</p>
                <div className="framer-community-post-stats">
                  <span>{t(`framer.community.posts.${k}.likes`)}</span>
                  <span>{t(`framer.community.posts.${k}.comments`)}</span>
                </div>
              </article>
            ))}
          </div>
        </div>
      </ScrollReveal>
    </section>
  )
}
