import { useState } from 'react'
import {
  Folder,
  Compass,
  Terminal,
  TrendingUp,
  LayoutDashboard,
  Settings,
  MessageSquare,
} from 'lucide-react'
import { useI18n } from '../../../i18n'
import GeminiLogo from '../../GeminiLogo'

const DOCK_APPS = [
  { id: 'finder', Icon: Folder, active: false },
  { id: 'safari', Icon: Compass, active: false },
  { id: 'terminal', Icon: Terminal, active: false },
  { id: 'gemini', Icon: null, active: true },
  { id: 'trading', Icon: TrendingUp, active: false },
  { id: 'dashboard', Icon: LayoutDashboard, active: false },
  { id: 'slack', Icon: MessageSquare, active: false },
  { id: 'settings', Icon: Settings, active: false },
] as const

export default function FramerMacDock() {
  const t = useI18n(s => s.t)
  const [hovered, setHovered] = useState<string | null>(null)

  return (
    <div className="framer-dock-wrap" aria-hidden>
      <div className="framer-dock">
        {DOCK_APPS.map(app => {
          const isHover = hovered === app.id
          const scale = isHover ? 1.28 : app.active ? 1.12 : 1
          return (
            <button
              key={app.id}
              type="button"
              className={`framer-dock-icon${app.active ? ' active' : ''}${isHover ? ' hover' : ''}`}
              style={{ transform: `scale(${scale}) translateY(${isHover ? -8 : app.active ? -4 : 0}px)` }}
              onMouseEnter={() => setHovered(app.id)}
              onMouseLeave={() => setHovered(null)}
              title={t(`framer.hero.dock.${app.id}`)}
            >
              <span className="framer-dock-icon-inner">
                {app.id === 'gemini' ? (
                  <GeminiLogo size={28} />
                ) : (
                  app.Icon && <app.Icon size={22} strokeWidth={1.75} />
                )}
              </span>
              <span className="framer-dock-reflection" />
              {app.active && <span className="framer-dock-dot" />}
            </button>
          )
        })}
      </div>
    </div>
  )
}
