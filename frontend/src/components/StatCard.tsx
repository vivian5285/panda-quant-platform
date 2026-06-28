import GlassCard from './GlassCard'
import CountUp from './ui/CountUp'

interface CountUpConfig {
  end: number
  prefix?: string
  suffix?: string
  decimals?: number
  /** Format as +$ / -$ PnL */
  pnl?: boolean
}

interface Props {
  label: string
  value?: string
  countUp?: CountUpConfig
  change?: string
  positive?: boolean
  delay?: number
}

function pnlParts(n: number) {
  const sign = n >= 0 ? '+$' : '-$'
  return { prefix: sign, end: Math.abs(n) }
}

export default function StatCard({ label, value, countUp, change, positive, delay = 0 }: Props) {
  let display: React.ReactNode = value

  if (countUp) {
    const { end, suffix = '', decimals = 0, pnl } = countUp
    let prefix = countUp.prefix ?? ''
    let animEnd = end
    if (pnl) {
      const p = pnlParts(end)
      prefix = p.prefix
      animEnd = p.end
    }
    display = (
      <CountUp
        end={animEnd}
        prefix={prefix}
        suffix={suffix}
        decimals={decimals}
        className="stat-value"
      />
    )
  }

  return (
    <GlassCard delay={delay} className="p-6 stat-card-hover">
      <p className="text-muted" style={{ fontSize: 13, marginBottom: 8 }}>{label}</p>
      <p className="stat-value">{display}</p>
      {change && (
        <p className={positive ? 'text-green' : 'text-red'} style={{ fontSize: 13, marginTop: 6 }}>
          {change}
        </p>
      )}
    </GlassCard>
  )
}
