import { ReactNode } from 'react'

interface Props {
  title: string
  subtitle?: string
  kicker?: string
  action?: ReactNode
}

export default function PageHeader({ title, subtitle, kicker, action }: Props) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        {kicker && <p className="framer-kicker page-kicker">{kicker}</p>}
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  )
}
