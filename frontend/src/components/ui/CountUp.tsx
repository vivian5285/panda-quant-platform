import { useEffect, useRef, useState } from 'react'

interface Props {
  end: number
  duration?: number
  decimals?: number
  prefix?: string
  suffix?: string
  className?: string
}

export default function CountUp({ end, duration = 1.8, decimals = 0, prefix = '', suffix = '', className = '' }: Props) {
  const [val, setVal] = useState(0)
  const started = useRef(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el || started.current) return

    const obs = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting || started.current) return
      started.current = true
      const t0 = performance.now()
      const tick = (now: number) => {
        const p = Math.min((now - t0) / (duration * 1000), 1)
        const eased = 1 - (1 - p) ** 3
        setVal(end * eased)
        if (p < 1) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    }, { threshold: 0.3 })

    obs.observe(el)
    return () => obs.disconnect()
  }, [end, duration])

  const formatted = val.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })

  return (
    <span ref={ref} className={className}>
      {prefix}{formatted}{suffix}
    </span>
  )
}
