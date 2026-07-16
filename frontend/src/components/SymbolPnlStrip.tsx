import { shortSymbol } from '../utils/symbolDisplay'

type SymbolPnlRow = {
  symbol: string
  pnl: number
  trades?: number
  win_rate?: number
}

type Props = {
  rows: SymbolPnlRow[]
  title?: string
  hint?: string
  emptyText?: string
}

function fmt(n: number) {
  const prefix = n >= 0 ? '+$' : '-$'
  return prefix + Math.abs(n).toFixed(2)
}

/** Compact ETH / XAU P&L strip for dashboard, trades, referrals. */
export default function SymbolPnlStrip({ rows, title, hint, emptyText }: Props) {
  if (!rows?.length) {
    return emptyText ? <p className="text-muted text-sm">{emptyText}</p> : null
  }
  return (
    <div className="symbol-pnl-strip">
      {(title || hint) && (
        <div className="symbol-pnl-strip-head">
          {title && <h4 className="text-sm-strong">{title}</h4>}
          {hint && <p className="text-muted text-xs">{hint}</p>}
        </div>
      )}
      <div className="symbol-pnl-strip-grid">
        {rows.map(row => {
          const sym = shortSymbol(row.symbol)
          const positive = row.pnl >= 0
          return (
            <div key={sym} className={`symbol-pnl-card ${positive ? 'up' : 'down'}`}>
              <div className="symbol-pnl-card-top">
                <span className="badge badge-gray">{sym}</span>
                <span className={positive ? 'text-green text-md-strong' : 'text-red text-md-strong'}>
                  {fmt(row.pnl)}
                </span>
              </div>
              {(row.trades != null || row.win_rate != null) && (
                <div className="symbol-pnl-card-meta text-muted text-xs">
                  {[
                    row.trades != null ? String(row.trades) : null,
                    row.win_rate != null ? `${row.win_rate}%` : null,
                  ].filter(Boolean).join(' · ')}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
