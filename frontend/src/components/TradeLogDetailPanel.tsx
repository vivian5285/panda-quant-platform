import { useMemo, useState } from 'react'
import { useI18n } from '../i18n'

export type TradeLogDetail = {
  id?: number
  event_type?: string
  message?: string
  detail_json?: string
  detail?: Record<string, unknown>
  trade_id?: number
  created_at?: string
}

function resolveDetail(log: TradeLogDetail): Record<string, unknown> {
  if (log.detail && Object.keys(log.detail).length) return log.detail
  if (!log.detail_json) return {}
  try {
    return JSON.parse(log.detail_json) as Record<string, unknown>
  } catch {
    return {}
  }
}

function fmtVal(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? '✓' : '✗'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/\.?0+$/, '')
  if (Array.isArray(v)) return v.length ? JSON.stringify(v) : '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

const HIGHLIGHT_KEYS = [
  'live_verified', 'verified_at', 'source', 'side', 'qty', 'entry', 'exit_price', 'pnl',
  'realized_pnl', 'price', 'aligned', 'healed', 'skipped', 'before_summary', 'after_summary',
  'live_audit', 'regime', 'tv_tps', 'slippage', 'funding_fee', 'reason', 'scan',
]

export default function TradeLogDetailPanel({ log, compact = false }: { log: TradeLogDetail; compact?: boolean }) {
  const t = useI18n(s => s.t)
  const [showRaw, setShowRaw] = useState(false)
  const detail = useMemo(() => resolveDetail(log), [log])

  const highlights = HIGHLIGHT_KEYS.filter(k => detail[k] != null)
  const liveVerified = detail.live_verified === true

  if (!Object.keys(detail).length) {
    return <p className="text-muted text-xs">{t('tradeLog.noDetail')}</p>
  }

  return (
    <div className={`trade-log-detail ${compact ? 'trade-log-detail-compact' : ''}`}>
      <div className="trade-log-detail-head">
        {liveVerified && <span className="badge badge-green">{t('tradeLog.liveVerified')}</span>}
        {detail.verified_at != null && (
          <span className="text-muted text-xs">{t('tradeLog.verifiedAt')}: {fmtVal(detail.verified_at)}</span>
        )}
        {detail.source != null && (
          <span className="text-muted text-xs">{t('tradeLog.source')}: {fmtVal(detail.source)}</span>
        )}
      </div>
      {highlights.length > 0 && (
        <div className="trades-detail-grid trade-log-detail-grid">
          {highlights.map(k => (
            <span key={k}>
              <strong>{t(`tradeLog.fields.${k}`)}:</strong>{' '}
              {k === 'live_audit' || k === 'scan' ? (
                <code className="text-xs">{fmtVal(detail[k])}</code>
              ) : (
                fmtVal(detail[k])
              )}
            </span>
          ))}
        </div>
      )}
      <button
        type="button"
        className="btn btn-ghost btn-xs trade-log-raw-toggle"
        onClick={() => setShowRaw(v => !v)}
      >
        {showRaw ? t('tradeLog.hideRaw') : t('tradeLog.showRaw')}
      </button>
      {showRaw && (
        <pre className="trade-log-raw-json">{JSON.stringify(detail, null, 2)}</pre>
      )}
    </div>
  )
}

export { resolveDetail }
