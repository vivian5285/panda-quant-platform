import { ReactNode, useState } from 'react'

interface Props {
  children: ReactNode
  className?: string
  onClick?: () => void
  type?: 'button' | 'submit'
  disabled?: boolean
}

export default function RippleButton({ children, className = '', onClick, type = 'button', disabled }: Props) {
  const [ripples, setRipples] = useState<{ x: number; y: number; id: number }[]>([])

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const id = Date.now()
    setRipples(r => [...r, { x: e.clientX - rect.left, y: e.clientY - rect.top, id }])
    setTimeout(() => setRipples(r => r.filter(x => x.id !== id)), 600)
    onClick?.()
  }

  return (
    <button type={type} className={`ripple-btn ${className}`} onClick={handleClick} disabled={disabled}>
      {ripples.map(r => (
        <span key={r.id} className="ripple-wave" style={{ left: r.x, top: r.y }} />
      ))}
      {children}
    </button>
  )
}
