import { useId } from 'react'

type Size = 'sm' | 'md' | 'lg' | number
export type GeminiLogoVariant = 'constellation' | 'monogram'

const SIZE_MAP = { sm: 24, md: 28, lg: 36 } as const

/** 4-point sparkle star (Castor / Pollux) */
function sparklePath(cx: number, cy: number, outerR: number, innerR = outerR * 0.38): string {
  const pts: [number, number][] = []
  for (let i = 0; i < 8; i++) {
    const a = (i * Math.PI) / 4 - Math.PI / 2
    const r = i % 2 === 0 ? outerR : innerR
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
  }
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(' ') + ' Z'
}

const FLOW_NODES = [
  { cx: 13.2, cy: 10.8, r: 0.75 },
  { cx: 16.0, cy: 13.6, r: 0.55 },
  { cx: 18.4, cy: 16.2, r: 0.65 },
] as const

const STAR_CASTOR = { cx: 10.2, cy: 12.8, r: 2.6 }
const STAR_POLLUX = { cx: 21.8, cy: 19.2, r: 3.0 }

function ConstellationMark({ uid }: { uid: string }) {
  const grad = `${uid}-grad`
  const glow = `${uid}-glow`
  const flow = `${uid}-flow`

  return (
    <>
      <defs>
        <linearGradient id={grad} x1="6" y1="6" x2="26" y2="26" gradientUnits="userSpaceOnUse">
          <stop stopColor="#60a5fa" />
          <stop offset="0.45" stopColor="#3B82F6" />
          <stop offset="1" stopColor="#8B5CF6" />
        </linearGradient>
        <linearGradient id={flow} x1="10" y1="10" x2="22" y2="20" gradientUnits="userSpaceOnUse">
          <stop stopColor="#3B82F6" stopOpacity="0.35" />
          <stop offset="0.5" stopColor="#6366f1" stopOpacity="0.85" />
          <stop offset="1" stopColor="#8B5CF6" stopOpacity="0.55" />
        </linearGradient>
        <filter id={glow} x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="0.9" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Decision flow — curved line + neural nodes */}
      <path
        d="M 10.2 12.8 C 12.5 9.2, 15.8 10.5, 17.2 13.8 S 20.2 18.6, 21.8 19.2"
        fill="none"
        stroke={`url(#${flow})`}
        strokeWidth="0.65"
        strokeLinecap="round"
        className="gemini-logo-flow"
      />
      {FLOW_NODES.map((n, i) => (
        <circle
          key={i}
          cx={n.cx}
          cy={n.cy}
          r={n.r}
          fill={`url(#${grad})`}
          opacity={0.85}
          filter={`url(#${glow})`}
        />
      ))}

      {/* Castor & Pollux */}
      <path
        d={sparklePath(STAR_CASTOR.cx, STAR_CASTOR.cy, STAR_CASTOR.r)}
        fill={`url(#${grad})`}
        filter={`url(#${glow})`}
        className="gemini-logo-star"
      />
      <path
        d={sparklePath(STAR_POLLUX.cx, STAR_POLLUX.cy, STAR_POLLUX.r)}
        fill={`url(#${grad})`}
        filter={`url(#${glow})`}
        className="gemini-logo-star gemini-logo-star-bright"
      />
    </>
  )
}

function MonogramMark({ uid }: { uid: string }) {
  const grad = `${uid}-g`
  const glow = `${uid}-gl`

  return (
    <>
      <defs>
        <linearGradient id={grad} x1="8" y1="6" x2="24" y2="26" gradientUnits="userSpaceOnUse">
          <stop stopColor="#3B82F6" />
          <stop offset="1" stopColor="#8B5CF6" />
        </linearGradient>
        <filter id={glow} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="0.7" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path
        d="M 16 7.5 A 8.5 8.5 0 1 0 16 24.5 A 8.5 8.5 0 0 0 16 7.5 M 16 11.5 A 5 5 0 1 1 16 21.5 A 5 5 0 0 1 16 11.5 M 16 16.5 H 21.5"
        fill="none"
        stroke={`url(#${grad})`}
        strokeWidth="1.65"
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${glow})`}
      />
      <path
        d={sparklePath(12.2, 12.4, 1.35)}
        fill={`url(#${grad})`}
        opacity={0.95}
      />
      <path
        d={sparklePath(14.8, 15.2, 1.05)}
        fill={`url(#${grad})`}
        opacity={0.75}
      />
    </>
  )
}

/** GEMINI AI — twin-star constellation + decision flow (Concept 1) or G monogram (Concept 2) */
export default function GeminiLogo({
  size = 'md',
  variant = 'constellation',
  className = '',
  showTile = true,
}: {
  size?: Size | number
  variant?: GeminiLogoVariant
  className?: string
  /** Rounded tile background; set false for inline/wordmark contexts */
  showTile?: boolean
}) {
  const uid = useId().replace(/:/g, '')
  const px = typeof size === 'number' ? size : SIZE_MAP[size]

  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`gemini-logo gemini-logo-${variant} ${className}`}
      aria-label="GEMINI AI"
    >
      {showTile && <rect width="32" height="32" rx="8" className="gemini-logo-bg" />}
      {variant === 'monogram' ? <MonogramMark uid={uid} /> : <ConstellationMark uid={uid} />}
    </svg>
  )
}

function drawSparkle(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  outerR: number,
  fill: CanvasGradient | string,
) {
  const innerR = outerR * 0.38
  ctx.beginPath()
  for (let i = 0; i < 8; i++) {
    const a = (i * Math.PI) / 4 - Math.PI / 2
    const r = i % 2 === 0 ? outerR : innerR
    const x = cx + r * Math.cos(a)
    const y = cy + r * Math.sin(a)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.closePath()
  ctx.fillStyle = fill
  ctx.fill()
}

/** Canvas helper for invite poster */
export function drawGeminiLogoCanvas(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  box: number,
) {
  const r = box * 0.22
  const half = box / 2
  const x = cx - half
  const y = cy - half
  const scale = box / 32

  ctx.save()
  roundRect(ctx, x, y, box, box, r)
  ctx.fillStyle = '#000000'
  ctx.fill()

  const grad = ctx.createLinearGradient(x, y, x + box, y + box)
  grad.addColorStop(0, '#60a5fa')
  grad.addColorStop(0.45, '#3B82F6')
  grad.addColorStop(1, '#8B5CF6')

  ctx.strokeStyle = grad
  ctx.lineWidth = 0.65 * scale
  ctx.globalAlpha = 0.75
  ctx.beginPath()
  ctx.moveTo(x + 10.2 * scale, y + 12.8 * scale)
  ctx.bezierCurveTo(
    x + 12.5 * scale, y + 9.2 * scale,
    x + 15.8 * scale, y + 10.5 * scale,
    x + 17.2 * scale, y + 13.8 * scale,
  )
  ctx.bezierCurveTo(
    x + 18.6 * scale, y + 16.2 * scale,
    x + 20.2 * scale, y + 18.6 * scale,
    x + 21.8 * scale, y + 19.2 * scale,
  )
  ctx.stroke()

  FLOW_NODES.forEach(n => {
    ctx.globalAlpha = 0.85
    ctx.beginPath()
    ctx.arc(x + n.cx * scale, y + n.cy * scale, n.r * scale, 0, Math.PI * 2)
    ctx.fillStyle = grad
    ctx.fill()
  })

  ctx.globalAlpha = 1
  drawSparkle(ctx, x + STAR_CASTOR.cx * scale, y + STAR_CASTOR.cy * scale, STAR_CASTOR.r * scale, grad)
  drawSparkle(ctx, x + STAR_POLLUX.cx * scale, y + STAR_POLLUX.cy * scale, STAR_POLLUX.r * scale, grad)
  ctx.restore()
}

function roundRect(ctx: CanvasRenderingContext2D, rx: number, ry: number, w: number, h: number, rad: number) {
  ctx.beginPath()
  ctx.moveTo(rx + rad, ry)
  ctx.arcTo(rx + w, ry, rx + w, ry + h, rad)
  ctx.arcTo(rx + w, ry + h, rx, ry + h, rad)
  ctx.arcTo(rx, ry + h, rx, ry, rad)
  ctx.arcTo(rx, ry, rx + w, ry, rad)
  ctx.closePath()
}
