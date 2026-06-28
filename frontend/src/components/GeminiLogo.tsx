import { useId } from 'react'

type Size = 'sm' | 'md' | 'lg' | number

const SIZE_MAP = { sm: 24, md: 28, lg: 36 } as const

const CX = 16
const CY = 16
const INNER = 0.382

/** Twin pentagrams — back layer rotated, front layer base; black fill + blue edge glow */
const TWIN_LAYERS = [
  { outer: 10.8, rot: 36, ox: 0.65, oy: -0.55, fill: '#14141c', stroke: 0.7, glow: 0.55 },
  { outer: 10.8, rot: 0, ox: -0.45, oy: 0.4, fill: '#000000', stroke: 0.95, glow: 1 },
] as const

function starPoints(cx: number, cy: number, outerR: number, rotDeg: number): [number, number][] {
  const innerR = outerR * INNER
  const rot = (rotDeg * Math.PI) / 180
  const pts: [number, number][] = []
  for (let i = 0; i < 10; i++) {
    const a = rot - Math.PI / 2 + (i * Math.PI) / 5
    const r = i % 2 === 0 ? outerR : innerR
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
  }
  return pts
}

function starPathD(pts: [number, number][]): string {
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join(' ') + ' Z'
}

function drawTwinStar(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  scale: number,
  layer: (typeof TWIN_LAYERS)[number],
  grad: CanvasGradient | string,
) {
  const pts = starPoints(cx + layer.ox * scale, cy + layer.oy * scale, layer.outer * scale, layer.rot)

  ctx.save()
  ctx.shadowColor = 'rgba(59,130,246,0.85)'
  ctx.shadowBlur = 6 * scale * layer.glow
  ctx.strokeStyle = grad
  ctx.lineWidth = layer.stroke * scale * 1.6
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  ctx.globalAlpha = 0.35 * layer.glow
  ctx.beginPath()
  pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)))
  ctx.closePath()
  ctx.stroke()

  ctx.shadowBlur = 2.5 * scale * layer.glow
  ctx.globalAlpha = layer.glow
  ctx.lineWidth = layer.stroke * scale
  ctx.fillStyle = layer.fill
  ctx.beginPath()
  pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)))
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
  ctx.restore()
}

/** 双子星 · GEMINI AI — dual 3D pentagram mark */
export default function GeminiLogo({
  size = 'md',
  className = '',
}: {
  size?: Size | number
  className?: string
}) {
  const uid = useId().replace(/:/g, '')
  const px = typeof size === 'number' ? size : SIZE_MAP[size]
  const grad = `${uid}-edge`
  const glow = `${uid}-glow`
  const soft = `${uid}-soft`

  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`gemini-logo ${className}`}
      aria-label="GEMINI AI"
    >
      <rect width="32" height="32" rx="8" className="gemini-logo-bg" />
      <defs>
        <linearGradient id={grad} x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
          <stop stopColor="#e0f2fe" />
          <stop offset="0.35" stopColor="#60a5fa" />
          <stop offset="0.7" stopColor="#2563eb" />
          <stop offset="1" stopColor="#1e3a8a" />
        </linearGradient>
        <filter id={soft} x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="1.1" result="blur" />
          <feColorMatrix in="blur" type="matrix" values="0 0 0 0 0.23  0 0 0 0 0.51  0 0 0 0 0.96  0 0 0 0.75 0" />
        </filter>
        <filter id={glow} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="0.55" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {TWIN_LAYERS.map((layer, i) => {
        const pts = starPoints(CX + layer.ox, CY + layer.oy, layer.outer, layer.rot)
        const d = starPathD(pts)
        return (
          <g key={i}>
            <path
              d={d}
              fill="none"
              stroke={`url(#${grad})`}
              strokeWidth={layer.stroke * 1.75}
              strokeLinejoin="round"
              opacity={0.28 * layer.glow}
              filter={`url(#${soft})`}
            />
            <path
              d={d}
              fill={layer.fill}
              stroke={`url(#${grad})`}
              strokeWidth={layer.stroke}
              strokeLinejoin="round"
              strokeLinecap="round"
              filter={`url(#${glow})`}
            />
          </g>
        )
      })}
    </svg>
  )
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
  ctx.fillStyle = '#0a0a0a'
  ctx.fill()

  const grad = ctx.createLinearGradient(x, y, x + box, y + box)
  grad.addColorStop(0, '#e0f2fe')
  grad.addColorStop(0.35, '#60a5fa')
  grad.addColorStop(0.7, '#2563eb')
  grad.addColorStop(1, '#1e3a8a')

  TWIN_LAYERS.forEach(layer => drawTwinStar(ctx, cx, cy, scale, layer, grad))
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
