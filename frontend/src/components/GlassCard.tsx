import { motion } from 'framer-motion'
import { ReactNode } from 'react'

interface Props {
  children: ReactNode
  className?: string
  delay?: number
  onClick?: () => void
  style?: React.CSSProperties
}

export default function GlassCard({ children, className = '', delay = 0, onClick, style }: Props) {
  return (
    <motion.div
      className={`glass ${className}`}
      style={style}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      onClick={onClick}
    >
      {children}
    </motion.div>
  )
}
