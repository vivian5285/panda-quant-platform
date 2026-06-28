interface Props {
  className?: string
  lines?: number
  height?: number
}

export default function Skeleton({ className = '', lines = 1, height = 16 }: Props) {
  if (lines === 1) {
    return <div className={`skeleton ${className}`} style={{ height }} />
  }
  return (
    <div className={className}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height, marginBottom: i < lines - 1 ? 10 : 0, width: i === lines - 1 ? '70%' : '100%' }} />
      ))}
    </div>
  )
}
