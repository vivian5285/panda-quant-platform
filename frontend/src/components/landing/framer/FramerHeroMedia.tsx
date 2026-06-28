import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'
import FramerHeroCanvas from './FramerHeroCanvas'
import FramerMacDock from './FramerMacDock'

const VIDEO_SRC = '/demo/console-demo.webm'
const POSTER_SRC = '/demo/console-poster.svg'

export default function FramerHeroMedia() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const videoRef = useRef<HTMLVideoElement>(null)
  const [mode, setMode] = useState<'loading' | 'video' | 'canvas'>('loading')

  useEffect(() => {
    if (reduceMotion) {
      setMode('canvas')
      return
    }
    const video = videoRef.current
    if (!video) return

    const onReady = () => setMode('video')
    const onFail = () => setMode('canvas')

    video.addEventListener('loadeddata', onReady)
    video.addEventListener('error', onFail)

    if (video.readyState >= 2) onReady()

    const timeout = setTimeout(() => {
      if (video.readyState < 2) onFail()
    }, 2500)

    return () => {
      clearTimeout(timeout)
      video.removeEventListener('loadeddata', onReady)
      video.removeEventListener('error', onFail)
    }
  }, [reduceMotion])

  const showVideo = mode === 'video' || mode === 'loading'

  return (
    <div className="framer-hero-media">
      {showVideo && (
        <div className={`framer-rec-shell framer-hero-video-shell${mode === 'loading' ? ' is-loading' : ''}`}>
          <div className="framer-rec-chrome">
            <span className="framer-rec-badge">
              <span className="framer-rec-dot" />
              {t('framer.hero.recording.demo')}
            </span>
            <span className="framer-rec-live">{t('framer.hero.recording.live')}</span>
          </div>

          <div className="framer-canvas-wrap framer-canvas-hero framer-rec-video framer-hero-video-frame">
            <div className="framer-rec-scanline" aria-hidden />
            <div className="framer-rec-vignette" aria-hidden />

            <div className="framer-canvas-topbar">
              <div className="framer-canvas-dots"><span /><span /><span /></div>
              <div className="framer-canvas-meta">
                <span className="framer-canvas-site">{t('framer.hero.toolbar.site')}</span>
                <span className="framer-canvas-dot">·</span>
                <span>{t('framer.hero.toolbar.branch')}</span>
              </div>
              <div className="framer-canvas-actions">
                <span className="framer-canvas-pill-btn framer-canvas-pill-btn-dark">
                  {t('framer.hero.toolbar.publish')}
                </span>
              </div>
            </div>

            <div className="framer-hero-video-body">
              <video
                ref={videoRef}
                className="framer-hero-video-el"
                src={VIDEO_SRC}
                poster={POSTER_SRC}
                autoPlay
                loop
                muted
                playsInline
                preload="auto"
              />
              {mode === 'loading' && (
                <div className="framer-hero-video-loader">
                  <span className="framer-agent-dot" />
                  {t('framer.hero.recording.loading')}
                </div>
              )}
            </div>
          </div>

          <FramerMacDock />
        </div>
      )}

      {(mode === 'canvas') && (
        <div className="framer-hero-canvas-fallback">
          <FramerHeroCanvas />
          <FramerMacDock />
        </div>
      )}
    </div>
  )
}
