import { motion } from 'framer-motion'
import { LucideIcon } from 'lucide-react'
import { ReactNode } from 'react'

interface Props {
  icon: LucideIcon
  title: string
  desc: string
  children?: ReactNode
  className?: string
  span?: 1 | 2
  delay?: number
}

export default function BentoCard({ icon: Icon, title, desc, children, className = '', span = 1, delay = 0 }: Props) {
  return (
    <motion.div
      className={`bento-card glass ${className}`}
      style={{ gridColumn: span === 2 ? 'span 2' : undefined }}
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.5, delay }}
      whileHover={{ y: -4, scale: 1.01 }}
    >
      <div className="bento-glow" aria-hidden />
      <div className="bento-icon"><Icon size={22} /></div>
      <h3>{title}</h3>
      <p>{desc}</p>
      {children}
    </motion.div>
  )
}
