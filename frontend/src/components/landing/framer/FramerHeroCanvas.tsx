import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../../i18n'
import DashboardPreview from '../DashboardPreview'

type Viewport = 'desktop' | 'tablet' | 'agent'
type Slide = 'dashboard' | 'trading' | 'analytics'

const VIEWPORTS: Viewport[] = ['desktop', 'tablet', 'agent']
const SLIDE_KEYS = ['dashboard', 'trading', 'signals', 'analytics', 'settlement'] as const
const SLIDES: Slide[] = ['dashboard', 'trading', 'analytics']

function formatRecTime(sec: number) {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function FramerHeroCanvas() {
  const t = useI18n(s => s.t)
  const [viewport, setViewport] = useState<Viewport>('desktop')
  const [slide, setSlide] = useState<Slide>('dashboard')
  const [activePage, setActivePage] = useState(0)
  const [recSec, setRecSec] = useState(0)
  const [agentPhase, setAgentPhase] = useState(0)
  const [progress, setProgress] = useState(0)
  const userPaused = useRef(false)
  const pauseTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const pauseAuto = () => {
    userPaused.current = true
    if (pauseTimer.current) clearTimeout(pauseTimer.current)
    pauseTimer.current = setTimeout(() => {
      userPaused.current = false
    }, 12000)
  }

  useEffect(() => {
    const tick = setInterval(() => setRecSec(s => s + 1), 1000)
    return () => clearInterval(tick)
  }, [])

  useEffect(() => {
    const bar = setInterval(() => {
      setProgress(p => (p >= 100 ? 0 : p + 0.35))
    }, 50)
    return () => clearInterval(bar)
  }, [])

  useEffect(() => {
    const demo = setInterval(() => {
      if (userPaused.current) return
      setViewport(v => {
        const i = VIEWPORTS.indexOf(v)
        return VIEWPORTS[(i + 1) % VIEWPORTS.length]
      })
    }, 5500)
    return () => clearInterval(demo)
  }, [])

  useEffect(() => {
    if (userPaused.current || viewport === 'agent') return
    const slideTimer = setInterval(() => {
      setActivePage(p => {
        const next = (p + 1) % SLIDE_KEYS.length
        setSlide(SLIDES[Math.min(next, SLIDES.length - 1)])
        return next
      })
    }, 2800)
    return () => clearInterval(slideTimer)
  }, [viewport])

  useEffect(() => {
    if (viewport !== 'agent') {
      setAgentPhase(0)
      return
    }
    setAgentPhase(0)
    const steps = [400, 1800, 3200, 4800]
    const timers = steps.map((ms, i) => setTimeout(() => setAgentPhase(i + 1), ms))
    const loop = setInterval(() => {
      setAgentPhase(0)
      steps.forEach((ms, i) => setTimeout(() => setAgentPhase(i + 1), ms))
    }, 6000)
    return () => {
      timers.forEach(clearTimeout)
      clearInterval(loop)
    }
  }, [viewport])

  const selectPage = (i: number) => {
    pauseAuto()
    setActivePage(i)
    setSlide(SLIDES[Math.min(i, SLIDES.length - 1)])
  }

  const selectViewport = (v: Viewport) => {
    pauseAuto()
    setViewport(v)
  }

  return (
    <div className="framer-rec-shell">
      <div className="framer-rec-chrome" aria-hidden>
        <span className="framer-rec-badge">
          <span className="framer-rec-dot" />
          REC · {formatRecTime(recSec)}
        </span>
        <span className="framer-rec-live">{t('framer.hero.recording.live')}</span>
      </div>

      <div className="framer-canvas-wrap framer-canvas-hero framer-rec-video">
        <div className="framer-rec-scanline" aria-hidden />
        <div className="framer-rec-vignette" aria-hidden />
        <div className="framer-rec-cursor" aria-hidden />

        <div className="framer-canvas-topbar">
          <div className="framer-canvas-dots">
            <span /><span /><span />
          </div>
          <div className="framer-canvas-meta">
            <span className="framer-canvas-site">{t('framer.hero.toolbar.site')}</span>
            <span className="framer-canvas-dot">·</span>
            <span>{t('framer.hero.toolbar.branch')}</span>
          </div>
          <div className="framer-canvas-actions">
            <span className="framer-canvas-pill-btn">{t('framer.hero.toolbar.invite')}</span>
            <span className="framer-canvas-pill-btn framer-canvas-pill-btn-dark">{t('framer.hero.toolbar.publish')}</span>
          </div>
        </div>

        <div className="framer-canvas-layout">
          <aside className="framer-canvas-pages">
            <div className="framer-canvas-pages-head">{t('framer.hero.toolbar.pages')}</div>
            {SLIDE_KEYS.map((key, i) => (
              <button
                key={key}
                type="button"
                className={`framer-canvas-page${activePage === i ? ' active' : ''}`}
                onClick={() => selectPage(i)}
              >
                {t(`framer.hero.sidebar.${key}`)}
              </button>
            ))}
          </aside>

          <div className="framer-canvas-main">
            <div className="framer-viewport-bar">
              {VIEWPORTS.map(v => (
                <button
                  key={v}
                  type="button"
                  className={`framer-viewport-tab${viewport === v ? ' active' : ''}`}
                  onClick={() => selectViewport(v)}
                >
                  <span>{t(`framer.hero.viewports.${v}.label`)}</span>
                  <small>{t(`framer.hero.viewports.${v}.size`)}</small>
                </button>
              ))}
            </div>

            <div className={`framer-viewport-frame framer-viewport-${viewport} framer-rec-frame`}>
              {viewport === 'agent' ? (
                <div className="framer-agent-panel">
                  <div className="framer-agent-panel-head">
                    <span>{t('framer.hero.agent.title')}</span>
                    <span className="framer-agent-model">{t('framer.hero.agent.model')}</span>
                  </div>
                  <div className="framer-agent-chat">
                    {agentPhase >= 1 && (
                      <div className="framer-agent-user framer-rec-fade-in">{t('framer.hero.agent.prompt')}</div>
                    )}
                    {agentPhase === 2 && (
                      <div className="framer-agent-thinking framer-rec-fade-in">
                        <span className="framer-agent-dot" />
                        {t('framer.hero.agent.thinking')}
                      </div>
                    )}
                    {agentPhase >= 3 && (
                      <div className="framer-agent-reply framer-rec-fade-in">{t('framer.hero.agent.reply')}</div>
                    )}
                    {agentPhase >= 4 && (
                      <div className="framer-agent-done framer-rec-fade-in">{t('framer.hero.agent.done')}</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="framer-canvas-preview framer-rec-content">
                  <DashboardPreview slide={slide} live />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="framer-rec-timeline" aria-hidden>
          <div className="framer-rec-track">
            <div className="framer-rec-progress" style={{ width: `${progress % 100}%` }} />
            <div className="framer-rec-playhead" style={{ left: `${progress % 100}%` }} />
          </div>
          <div className="framer-rec-timecodes">
            <span>0:00</span>
            <span>{formatRecTime(recSec)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
