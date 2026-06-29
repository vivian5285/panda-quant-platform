import GlassCard from '../../../components/GlassCard'
import { adminApi } from '../../../api'
import { toast } from '../../../store/toast'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

export default function AdminRiskTab() {
  const {
    t, locale, globalControl, setAdminConfirm, riskDraft, setRiskDraft,
    setGlobalControl, alerts, load,
  } = useAdmin()

  return (
    <div>
      <GlassCard className="p-6 section-mb-md">
        <h3 className="card-heading">{t('admin.globalPauseTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.globalPauseHint')}</p>
        <p className="text-md-strong section-mb-sm">
          {globalControl?.global_trading_paused ? t('admin.globalPaused') : t('admin.globalActive')}
        </p>
        <div className="flex-gap-md">
          {!globalControl?.global_trading_paused ? (
            <button className="btn btn-danger" onClick={() => setAdminConfirm({ type: 'globalPause' })}>{t('admin.pauseGlobal')}</button>
          ) : (
            <button className="btn btn-primary" onClick={() => setAdminConfirm({ type: 'globalResume' })}>{t('admin.resumeGlobal')}</button>
          )}
        </div>
      </GlassCard>

      <GlassCard className="p-6 section-mb-md">
        <h3 className="card-heading">{t('admin.globalRiskTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.globalRiskHint')}</p>
        <div className="flex-gap-md">
          <input className="input" type="number" step="0.1" min="0.1" max="3" value={riskDraft}
            onChange={e => setRiskDraft(e.target.value)} style={{ maxWidth: 120 }} />
          <button className="btn btn-primary btn-sm" type="button" onClick={() => {
            adminApi.setGlobalRiskMultiplier(parseFloat(riskDraft)).then(gc => {
              setGlobalControl(gc)
              toast.success(t('admin.globalRiskSaved'))
            })
          }}>{t('common.save')}</button>
          <span className="text-muted text-sm">× {globalControl?.global_risk_multiplier ?? 1}</span>
        </div>
      </GlassCard>

      <p className="text-muted text-sm mb-md">{t('admin.dingtalkHint')}</p>
      <div className="section-mb-sm">
        <button className="btn btn-ghost btn-sm" onClick={() => adminApi.readAllAlerts().then(() => { toast.success(t('admin.allRead')); load() })}>
          {t('common.markAllRead')}
        </button>
      </div>
      <GlassCard className="p-0 table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>{t('common.time')}</th><th>{t('admin.cols.level')}</th><th>{t('admin.cols.type')}</th><th>{t('admin.cols.detail')}</th><th>{t('common.action')}</th></tr>
          </thead>
          <tbody>
            {alerts.length === 0 && (
              <tr><td colSpan={5} className="empty-cell">{t('admin.noAlerts')}</td></tr>
            )}
            {alerts.map((a: any) => (
              <tr key={a.id} className={a.is_read ? 'row-read' : undefined}>
                <td className="text-xs">{localeDate(a.created_at, locale)}</td>
                <td>
                  <span className={`badge ${a.severity === 'critical' ? 'badge-red' : a.severity === 'warning' ? 'badge-gray' : 'badge-green'}`}>
                    {a.severity}
                  </span>
                </td>
                <td className="text-xs">{a.alert_type}</td>
                <td className="text-sm cell-max-sm">{a.title} — {a.message}</td>
                <td>
                  {!a.is_read && (
                    <button className="btn btn-ghost btn-xs" onClick={() => adminApi.readAlert(a.id).then(load)}>{t('common.markRead')}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  )
}
