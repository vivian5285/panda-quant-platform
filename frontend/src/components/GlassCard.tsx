import { motion } from 'framer-motion'
import { ReactNode } from 'react'

interface Props {
  children: ReactNode
  className?: string
  green?: boolean
  delay?: number
  onClick?: () => void
  style?: React.CSSProperties
}

export default function GlassCard({ children, className = '', green, delay = 0, onClick, style }: Props) {
  return (
    <motion.div
      className={`glass ${green ? 'glass-green' : ''} ${className}`}
      style={style}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      whileHover={{ y: -2 }}
      onClick={onClick}
    >
      {children}
    </motion.div>
  )
}
