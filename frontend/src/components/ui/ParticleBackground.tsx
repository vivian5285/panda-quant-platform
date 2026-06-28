import { useEffect, useRef } from 'react'
import { useTheme } from '../../store/theme'

export default function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { theme } = useTheme()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let w = 0
    let h = 0
    let raf = 0
    let mx = 0
    let my = 0

    const stars = Array.from({ length: 120 }, () => ({
      x: Math.random(),
      y: Math.random(),
      r: Math.random() * 1.8 + 0.4,
      vx: (Math.random() - 0.5) * 0.0004,
      vy: (Math.random() - 0.5) * 0.0004,
      a: Math.random() * 0.5 + 0.2,
    }))

    const resize = () => {
      w = canvas.offsetWidth
      h = canvas.offsetHeight
      canvas.width = w * devicePixelRatio
      canvas.height = h * devicePixelRatio
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0)
    }

    const onMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect()
      mx = (e.clientX - rect.left) / rect.width
      my = (e.clientY - rect.top) / rect.height
    }

    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      const isDark = theme === 'dark'

      const grad = ctx.createRadialGradient(w * mx, h * my, 0, w * 0.5, h * 0.4, w * 0.7)
      grad.addColorStop(0, isDark ? 'rgba(59,130,246,0.12)' : 'rgba(59,130,246,0.08)')
      grad.addColorStop(0.5, isDark ? 'rgba(139,92,246,0.08)' : 'rgba(139,92,246,0.05)')
      grad.addColorStop(1, 'transparent')
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, w, h)

      for (const s of stars) {
        s.x += s.vx
        s.y += s.vy
        if (s.x < 0 || s.x > 1) s.vx *= -1
        if (s.y < 0 || s.y > 1) s.vy *= -1

        const px = s.x * w
        const py = s.y * h
        const dx = px - mx * w
        const dy = py - my * h
        const dist = Math.sqrt(dx * dx + dy * dy)
        const glow = Math.max(0, 1 - dist / 280)

        ctx.beginPath()
        ctx.arc(px, py, s.r + glow * 2, 0, Math.PI * 2)
        ctx.fillStyle = isDark
          ? `rgba(${100 + glow * 80}, ${200 + glow * 55}, 255, ${s.a + glow * 0.4})`
          : `rgba(59, 130, 246, ${s.a * 0.6 + glow * 0.3})`
        ctx.fill()
      }

      raf = requestAnimationFrame(draw)
    }

    resize()
    draw()
    window.addEventListener('resize', resize)
    window.addEventListener('mousemove', onMove)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', onMove)
    }
  }, [theme])

  return <canvas ref={canvasRef} className="particle-bg" aria-hidden />
}
