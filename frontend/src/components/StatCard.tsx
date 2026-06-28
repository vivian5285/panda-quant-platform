import GlassCard from './GlassCard'

interface Props {
  label: string
  value: string
  change?: string
  positive?: boolean
  delay?: number
}

export default function StatCard({ label, value, change, positive, delay = 0 }: Props) {
  return (
    <GlassCard delay={delay} className="p-6">
      <p className="text-muted" style={{ fontSize: 13, marginBottom: 8 }}>{label}</p>
      <p className="stat-value">{value}</p>
      {change && (
        <p className={positive ? 'text-green' : 'text-red'} style={{ fontSize: 13, marginTop: 6 }}>
          {change}
        </p>
      )}
    </GlassCard>
  )
}
