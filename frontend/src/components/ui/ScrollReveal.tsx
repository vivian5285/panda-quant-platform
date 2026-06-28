import { motion, useReducedMotion } from 'framer-motion'
import { ReactNode } from 'react'

interface Props {
  children: ReactNode
  className?: string
  delay?: number
  y?: number
  duration?: number
  blur?: number
  once?: boolean
}

export default function ScrollReveal({
  children,
  className = '',
  delay = 0,
  y = 40,
  duration = 0.65,
  blur = 0,
  once = true,
}: Props) {
  const reduce = useReducedMotion()

  if (reduce) {
    return <div className={className}>{children}</div>
  }

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y, filter: blur ? `blur(${blur}px)` : undefined }}
      whileInView={{ opacity: 1, y: 0, filter: blur ? 'blur(0px)' : undefined }}
      viewport={{ once, margin: '-72px' }}
      transition={{ duration, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  )
}
