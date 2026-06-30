import { useEffect, useState } from 'react'
import { ShieldAlert, PauseCircle, PlayCircle, Bell } from 'lucide-react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import SettlementGateBanner from '../components/SettlementGateBanner'
import RippleButton from '../components/ui/RippleButton'
import ConfirmModal from '../components/ui/ConfirmModal'
import { userApi } from '../api'
import { useI18n, localeDate } from '../i18n'
import { toast } from '../store/toast'

type Control = {
  trading_paused: boolean
  settlement_blocked?: boolean
  settlement_fee_deferred?: boolean
  effective_paused?: boolean
  pending_settlement?: {
    id: number
    user_payable: number
    payment_status: string
  } | null
  risk_level: string
  risk_multiplier: number
  api_status: string
  global_paused: boolean
}

const RISK_LEVELS = ['conservative', 'balanced', 'aggressive'] as const

export default function RiskControl() {
  const { t, locale } = useI18n()
  const [ctrl, setCtrl] = useState<Control | null>(null)
  const [lastSignalAt, setLastSignalAt] = useState<string | null>(null)
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [pauseConfirmOpen, setPauseConfirmOpen] = useState(false)

  const load = () => {
    userApi.tradingControl().then(setCtrl).catch(() => {})
    userApi.signals().then(s => setLastSignalAt(s?.last_signal_at ?? null)).catch(() => {})
    userApi.logs().then(rows => {
      const risk = rows.filter((l: any) =>
        ['ERROR', 'ADJUST', 'SIGNAL', 'SETTLEMENT'].includes(l.event_type) ||
        l.message?.includes('风控') || l.message?.includes('暂停') || l.message?.includes('结算'),
      )
      setLogs(risk.slice(0, 20))
    })
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  const setRisk = async (risk_level: string) => {
    setLoading(true)
    try {
      setCtrl(await userApi.updateTradingControl({ risk_level }))
      toast.success(t('risk.levelUpdated'))
    } catch {
      toast.error(t('risk.updateFail'))
    } finally {
      setLoading(false)
    }
  }

  const applyPause = async () => {
    setLoading(true)
    try {
      setCtrl(await userApi.updateTradingControl({ trading_paused: true }))
      toast.success(t('risk.paused'))
      setPauseConfirmOpen(false)
      load()
    } catch {
      toast.error(t('risk.updateFail'))
    } finally {
      setLoading(false)
    }
  }

  const resumeTrading = async () => {
    if (ctrl?.settlement_blocked && !ctrl?.settlement_fee_deferred) {
      toast.error(t('risk.resumeBlockedSettlement'))
      return
    }
    setLoading(true)
    try {
      setCtrl(await userApi.updateTradingControl({ trading_paused: false }))
      toast.success(t('risk.resumed'))
      load()
    } catch {
      toast.error(t('risk.updateFail'))
    } finally {
      setLoading(false)
    }
  }

  const statusLabel = () => {
    if (ctrl?.settlement_blocked && !ctrl?.settlement_fee_deferred) return t('risk.statusSettlementPaused')
    if (ctrl?.trading_paused) return t('risk.statusPaused')
    return t('risk.statusActive')
  }

  const effectivelyPaused = ctrl?.effective_paused ?? ctrl?.trading_paused
  const canResume = !ctrl?.global_paused && !(ctrl?.settlement_blocked && !ctrl?.settlement_fee_deferred)
  const canPause = !ctrl?.global_paused

  return (
    <Layout>
      <PageHeader title={t('risk.title')} subtitle={t('risk.subtitle')} />

      {ctrl?.global_paused && (
        <GlassCard className="p-4 risk-alert-banner">
          <ShieldAlert size={18} />
          <span>{t('risk.globalPausedHint')}</span>
        </GlassCard>
      )}

      <SettlementGateBanner
        blocked={ctrl?.settlement_blocked}
        deferred={ctrl?.settlement_fee_deferred}
        settlement={ctrl?.pending_settlement}
      />

      <div className="stat-grid risk-stat-grid">
        <StatCard label={t('risk.apiHealth')} value={ctrl?.api_status || '—'} />
        <StatCard label={t('risk.myStatus')} value={statusLabel()} />
        <StatCard label={t('risk.multiplier')} value={`${ctrl?.risk_multiplier ?? 1}×`} />
        <StatCard
          label={t('risk.lastExecution')}
          value={lastSignalAt ? localeDate(lastSignalAt, locale) : t('common.none')}
        />
      </div>

      <GlassCard className="p-6 section-mb-lg risk-toggle-card">
        <div className="risk-toggle-head">
          <div>
            <h3 className="card-heading">{t('risk.controlTitle')}</h3>
            <p className="text-muted text-sm mb-0">{t('risk.controlHint')}</p>
          </div>
          <span className={`badge risk-status-badge ${effectivelyPaused ? 'badge-gray' : 'badge-green'}`}>
            {statusLabel()}
          </span>
        </div>
        {ctrl?.settlement_blocked && !ctrl?.settlement_fee_deferred && (
          <p className="text-muted text-sm section-mt-sm">{t('risk.settlementBlockedHint')}</p>
        )}
        <div className="risk-toggle-actions">
          <RippleButton
            className="btn btn-primary risk-toggle-btn"
            disabled={loading || !effectivelyPaused || !canResume}
            onClick={resumeTrading}
          >
            <PlayCircle size={20} />
            <span>
              <strong>{t('risk.startTrading')}</strong>
              <small>{t('risk.startTradingHint')}</small>
            </span>
          </RippleButton>
          <RippleButton
            className="btn btn-danger risk-toggle-btn"
            disabled={loading || effectivelyPaused || !canPause}
            onClick={() => setPauseConfirmOpen(true)}
          >
            <PauseCircle size={20} />
            <span>
              <strong>{t('risk.pauseTrading')}</strong>
              <small>{t('risk.pauseTradingHint')}</small>
            </span>
          </RippleButton>
        </div>
        {!canPause && ctrl?.global_paused && (
          <p className="text-muted text-xs section-mt-sm">{t('risk.globalPausedHint')}</p>
        )}
      </GlassCard>

      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('risk.levelTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('risk.levelHint')}</p>
        <div className="risk-level-grid">
          {RISK_LEVELS.map(level => (
            <button
              key={level}
              type="button"
              className={`risk-level-btn${ctrl?.risk_level === level ? ' active' : ''}`}
              disabled={loading}
              onClick={() => setRisk(level)}
            >
              <strong>{t(`risk.levels.${level}`)}</strong>
              <span className="text-muted">{t(`risk.levelsDesc.${level}`)}</span>
            </button>
          ))}
        </div>
      </GlassCard>

      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('risk.alertSettings')}</h3>
        <p className="text-muted text-sm mb-md">{t('risk.alertSettingsHint')}</p>
        <Link to="/profile" className="btn btn-ghost">
          <Bell size={16} /> {t('risk.alertSettingsLink')}
        </Link>
      </GlassCard>

      <GlassCard className="p-6">
        <h3 className="card-heading">{t('risk.eventLog')}</h3>
        <div className="risk-log-list">
          {logs.length === 0 && <p className="text-muted">{t('risk.noEvents')}</p>}
          {logs.map(log => (
            <div key={log.id} className="list-row-divider risk-log-item">
              <span className="badge badge-gray">{log.event_type}</span>
              <span className="risk-log-msg">{log.message}</span>
              <p className="text-muted risk-log-time">{localeDate(log.created_at, locale)}</p>
            </div>
          ))}
        </div>
      </GlassCard>

      <ConfirmModal
        open={pauseConfirmOpen}
        title={t('risk.pauseConfirmTitle')}
        message={t('risk.pauseConfirm')}
        confirmLabel={t('risk.pauseConfirmAction')}
        variant="danger"
        loading={loading}
        onConfirm={applyPause}
        onCancel={() => !loading && setPauseConfirmOpen(false)}
      />
    </Layout>
  )
}
