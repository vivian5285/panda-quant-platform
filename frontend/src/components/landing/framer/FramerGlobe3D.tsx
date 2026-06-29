import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'
import { useI18n } from '../../../i18n'

const NODES = [
  { id: 'sf', lng: -122.4, lat: 37.8, region: 'na' },
  { id: 'ny', lng: -74.0, lat: 40.7, region: 'na' },
  { id: 'sp', lng: -46.6, lat: -23.5, region: 'sa' },
  { id: 'ldn', lng: -0.1, lat: 51.5, region: 'eu' },
  { id: 'fra', lng: 8.7, lat: 50.1, region: 'eu' },
  { id: 'dxb', lng: 55.3, lat: 25.2, region: 'me' },
  { id: 'sg', lng: 103.8, lat: 1.3, region: 'as' },
  { id: 'hk', lng: 114.2, lat: 22.3, region: 'as' },
  { id: 'tky', lng: 139.7, lat: 35.7, region: 'as' },
  { id: 'syd', lng: 151.2, lat: -33.9, region: 'oc' },
  { id: 'jnb', lng: 28.0, lat: -26.2, region: 'af' },
] as const

const LAND: [number, number][] = [
  ...Array.from({ length: 22 }, (_, i) => [-125 + i * 4, 38 + Math.sin(i * 0.5) * 6] as [number, number]),
  ...Array.from({ length: 16 }, (_, i) => [-82 + i * 3, 28 + Math.cos(i * 0.4) * 5] as [number, number]),
  ...Array.from({ length: 14 }, (_, i) => [-55 + i * 2.5, -8 - Math.sin(i * 0.35) * 12] as [number, number]),
  ...Array.from({ length: 18 }, (_, i) => [-8 + i * 2, 48 + Math.sin(i * 0.3) * 4] as [number, number]),
  ...Array.from({ length: 10 }, (_, i) => [10 + i * 3, 35 + Math.cos(i * 0.5) * 8] as [number, number]),
  ...Array.from({ length: 12 }, (_, i) => [25 + i * 4, -2 - i * 2.5] as [number, number]),
  ...Array.from({ length: 20 }, (_, i) => [55 + i * 2.5, 18 + Math.sin(i * 0.45) * 10] as [number, number]),
  ...Array.from({ length: 16 }, (_, i) => [95 + i * 3, 28 + Math.cos(i * 0.4) * 12] as [number, number]),
  ...Array.from({ length: 14 }, (_, i) => [115 + i * 2.5, 22 - i * 1.5] as [number, number]),
  ...Array.from({ length: 10 }, (_, i) => [135 + i * 2, 32 + Math.sin(i) * 6] as [number, number]),
  ...Array.from({ length: 8 }, (_, i) => [150 + i * 1.5, -32 + Math.cos(i) * 4] as [number, number]),
]

type Vec3 = { x: number; y: number; z: number }

function latLngToVec(lat: number, lng: number, r: number): Vec3 {
  const phi = ((90 - lat) * Math.PI) / 180
  const theta = ((lng + 180) * Math.PI) / 180
  return {
    x: -r * Math.sin(phi) * Math.cos(theta),
    y: r * Math.cos(phi),
    z: r * Math.sin(phi) * Math.sin(theta),
  }
}

function rotY(p: Vec3, a: number): Vec3 {
  const c = Math.cos(a)
  const s = Math.sin(a)
  return { x: p.x * c + p.z * s, y: p.y, z: -p.x * s + p.z * c }
}

function rotX(p: Vec3, a: number): Vec3 {
  const c = Math.cos(a)
  const s = Math.sin(a)
  return { x: p.x, y: p.y * c - p.z * s, z: p.y * s + p.z * c }
}

export default function FramerGlobe3D() {
  const t = useI18n(s => s.t)
  const reduceMotion = useReducedMotion()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rotRef = useRef(0)
  const [active, setActive] = useState(0)

  useEffect(() => {
    if (reduceMotion) return
    const timer = setInterval(() => setActive(i => (i + 1) % NODES.length), 2400)
    return () => clearInterval(timer)
  }, [reduceMotion])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf = 0
    let running = true
    const tilt = 0.32
    const radius = 1

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const rect = canvas.getBoundingClientRect()
      canvas.width = rect.width * dpr
      canvas.height = rect.height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const draw = () => {
      if (!running) return
      const w = canvas.getBoundingClientRect().width
      const h = canvas.getBoundingClientRect().height
      const cx = w / 2
      const cy = h / 2
      const scale = Math.min(w, h) * 0.36
      const rot = rotRef.current

      ctx.clearRect(0, 0, w, h)

      const glow = ctx.createRadialGradient(cx, cy, scale * 0.5, cx, cy, scale * 1.15)
      glow.addColorStop(0, 'rgba(0, 122, 255, 0.12)')
      glow.addColorStop(0.55, 'rgba(0, 122, 255, 0.04)')
      glow.addColorStop(1, 'rgba(0, 122, 255, 0)')
      ctx.fillStyle = glow
      ctx.beginPath()
      ctx.arc(cx, cy, scale * 1.12, 0, Math.PI * 2)
      ctx.fill()

      const sphere = ctx.createRadialGradient(cx - scale * 0.2, cy - scale * 0.25, scale * 0.1, cx, cy, scale)
      sphere.addColorStop(0, 'rgba(30, 35, 50, 0.95)')
      sphere.addColorStop(0.7, 'rgba(12, 14, 22, 0.98)')
      sphere.addColorStop(1, 'rgba(4, 6, 12, 1)')
      ctx.fillStyle = sphere
      ctx.beginPath()
      ctx.arc(cx, cy, scale, 0, Math.PI * 2)
      ctx.fill()

      const lines: { lat: number; lng: number; isLat: boolean }[] = []
      for (let lat = -60; lat <= 60; lat += 30) lines.push({ lat, lng: 0, isLat: true })
      for (let lng = -180; lng < 180; lng += 30) lines.push({ lat: 0, lng, isLat: false })

      ctx.strokeStyle = 'rgba(255,255,255,0.04)'
      ctx.lineWidth = 0.6
      for (const line of lines) {
        ctx.beginPath()
        let started = false
        for (let i = 0; i <= 36; i++) {
          const lat = line.isLat ? line.lat : -90 + (i / 36) * 180
          const lng = line.isLat ? -180 + (i / 36) * 360 : line.lng
          let p = latLngToVec(lat, lng, radius)
          p = rotY(p, rot)
          p = rotX(p, tilt)
          if (p.z < -0.05) {
            started = false
            continue
          }
          const sx = cx + p.x * scale
          const sy = cy - p.y * scale
          if (!started) {
            ctx.moveTo(sx, sy)
            started = true
          } else ctx.lineTo(sx, sy)
        }
        ctx.stroke()
      }

      const landPts = LAND.map(([lng, lat]) => {
        let p = latLngToVec(lat, lng, radius)
        p = rotY(p, rot)
        p = rotX(p, tilt)
        return { ...p, sx: cx + p.x * scale, sy: cy - p.y * scale }
      }).sort((a, b) => a.z - b.z)

      for (const p of landPts) {
        if (p.z < 0) continue
        const alpha = 0.08 + (p.z / radius) * 0.22
        ctx.fillStyle = `rgba(200, 210, 230, ${alpha})`
        ctx.beginPath()
        ctx.arc(p.sx, p.sy, 1.2 + (p.z / radius) * 0.8, 0, Math.PI * 2)
        ctx.fill()
      }

      const nodePts = NODES.map((n, i) => {
        let p = latLngToVec(n.lat, n.lng, radius)
        p = rotY(p, rot)
        p = rotX(p, tilt)
        return { ...p, sx: cx + p.x * scale, sy: cy - p.y * scale, i, id: n.id, region: n.region }
      }).sort((a, b) => a.z - b.z)

      for (const p of nodePts) {
        if (p.z < 0.05) continue
        const lit = p.i === active
        const warm = p.i === (active - 1 + NODES.length) % NODES.length
        const depth = p.z / radius

        if (lit && !reduceMotion) {
          const pulse = scale * (0.08 + depth * 0.06)
          const g = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, pulse * 3)
          g.addColorStop(0, 'rgba(0, 122, 255, 0.55)')
          g.addColorStop(1, 'rgba(0, 122, 255, 0)')
          ctx.fillStyle = g
          ctx.beginPath()
          ctx.arc(p.sx, p.sy, pulse * 3, 0, Math.PI * 2)
          ctx.fill()
        }

        ctx.fillStyle = lit ? '#007aff' : warm ? '#3b82f6' : `rgba(255,255,255,${0.25 + depth * 0.35})`
        ctx.beginPath()
        ctx.arc(p.sx, p.sy, lit ? 4.5 + depth : warm ? 3.5 : 2.5, 0, Math.PI * 2)
        ctx.fill()

        if (lit) {
          ctx.strokeStyle = 'rgba(0, 122, 255, 0.5)'
          ctx.lineWidth = 1
          ctx.beginPath()
          ctx.arc(p.sx, p.sy, 8 + depth * 4, 0, Math.PI * 2)
          ctx.stroke()
        }
      }

      ctx.strokeStyle = 'rgba(0, 122, 255, 0.15)'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.arc(cx, cy, scale, 0, Math.PI * 2)
      ctx.stroke()

      if (!reduceMotion) rotRef.current += 0.004
      raf = requestAnimationFrame(draw)
    }

    raf = requestAnimationFrame(draw)

    return () => {
      running = false
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
    }
  }, [active, reduceMotion])

  const cur = NODES[active]

  return (
    <section id="global" className="framer-global-map-layout">
      <aside className="framer-global-map-copy">
        <p className="framer-kicker">{t('framer.globalMap.kicker')}</p>
        <h2>{t('framer.globalMap.title')}</h2>
        <p className="framer-global-map-desc">{t('framer.globalMap.subtitle')}</p>
        <div className="framer-global-map-stats">
          <div>
            <strong>{NODES.length}+</strong>
            <span>{t('framer.globalMap.nodes')}</span>
          </div>
          <div>
            <strong>24/7</strong>
            <span>{t('framer.globalMap.uptime')}</span>
          </div>
          <div className="framer-global-map-live">
            <span className="framer-global-map-live-dot" />
            {t('framer.globalMap.live')}
          </div>
        </div>
      </aside>

      <div className="framer-global-map-frame glass framer-globe-frame">
        <div className="framer-globe-grid-bg" aria-hidden />
        <canvas ref={canvasRef} className="framer-globe-canvas" aria-hidden />
        <div className="framer-global-map-label">
          <span className="framer-global-map-label-dot" />
          <span>{t(`framer.globalMap.cities.${cur.id}`)}</span>
          <span className="framer-global-map-label-region">{t(`framer.globalMap.regions.${cur.region}`)}</span>
        </div>
      </div>
    </section>
  )
}
