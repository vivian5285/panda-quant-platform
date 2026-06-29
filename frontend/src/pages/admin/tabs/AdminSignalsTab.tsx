import GlassCard from '../../../components/GlassCard'
import { adminApi } from '../../../api'
import { toast } from '../../../store/toast'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

export default function AdminSignalsTab() {
  const {
    t, locale, newTemplate, setNewTemplate, editTemplate, setEditTemplate,
    signalTemplates, signalLogs, strategies,
    saveSignalTemplate, saveTemplateEdit, testTemplate, reviewStrategy,
    exportStrategiesCsv, load, setTab, loadDispatchResults,
  } = useAdmin()

  return (
    <div>
      <GlassCard className="p-4 section-mb-md">
        <p className="text-muted text-sm">{t('admin.tvMappingHint')}</p>
      </GlassCard>
      <GlassCard className="p-6 section-mb-md">
        <h3 className="card-heading">{t('admin.newTemplate')}</h3>
        <form onSubmit={saveSignalTemplate} className="form-stack">
          <input className="input" placeholder={t('admin.templateName')} value={newTemplate.name}
            onChange={e => setNewTemplate({ ...newTemplate, name: e.target.value })} required />
          <textarea className="input input-mono" rows={6} placeholder={t('admin.templatePayload')} value={newTemplate.payload}
            onChange={e => setNewTemplate({ ...newTemplate, payload: e.target.value })} />
          <button className="btn btn-primary btn-sm" type="submit">{t('common.add')}</button>
        </form>
      </GlassCard>
      {editTemplate && (
        <GlassCard className="p-6 section-mb-md">
          <h3 className="card-heading">{t('admin.editTemplate')} #{editTemplate.id}</h3>
          <div className="form-stack">
            <input className="input" value={editTemplate.name} onChange={e => setEditTemplate({ ...editTemplate, name: e.target.value })} />
            <input className="input" value={editTemplate.description} onChange={e => setEditTemplate({ ...editTemplate, description: e.target.value })} />
            <textarea className="input input-mono" rows={8} value={editTemplate.payloadText} onChange={e => setEditTemplate({ ...editTemplate, payloadText: e.target.value })} />
            <div className="flex-gap-sm">
              <button className="btn btn-primary btn-sm" type="button" onClick={saveTemplateEdit}>{t('common.save')}</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setEditTemplate(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </GlassCard>
      )}
      <GlassCard className="p-0 table-wrap section-mb-md">
        <div className="table-toolbar table-toolbar-flush"><h3 className="card-heading">{t('admin.signalTemplates')}</h3></div>
        <table className="data-table">
          <tbody>
            {signalTemplates.length === 0 && <tr><td colSpan={4} className="empty-cell">{t('common.noData')}</td></tr>}
            {signalTemplates.map((tpl: any) => (
              <tr key={tpl.id}>
                <td>{tpl.id}</td>
                <td>{tpl.name}<br /><span className="text-muted text-xs">{tpl.description}</span></td>
                <td><span className={`badge ${tpl.enabled ? 'badge-green' : 'badge-gray'}`}>{tpl.enabled ? t('common.enable') : t('common.disable')}</span></td>
                <td className="table-actions">
                  <button className="btn btn-primary btn-xs" type="button" onClick={() => testTemplate(tpl.id)}>{t('admin.testSend')}</button>
                  <button className="btn btn-ghost btn-xs" type="button" onClick={() => setEditTemplate({
                    id: tpl.id,
                    name: tpl.name,
                    description: tpl.description || '',
                    payloadText: JSON.stringify(tpl.payload || {}, null, 2),
                  })}>{t('admin.editTemplate')}</button>
                  <button className="btn btn-ghost btn-xs" type="button" onClick={() => adminApi.updateSignalTemplate(tpl.id, { enabled: !tpl.enabled }).then(load)}>{t('common.toggle')}</button>
                  <button className="btn btn-ghost btn-xs" type="button" onClick={() => adminApi.deleteSignalTemplate(tpl.id).then(() => { toast.success(t('admin.templateDeleted')); load() })}>{t('common.delete')}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-0 table-wrap section-mb-md">
        <div className="table-toolbar table-toolbar-flush"><h3 className="card-heading">{t('admin.signalHistory')}</h3></div>
        <table className="data-table">
          <thead><tr><th>{t('common.time')}</th><th>{t('trades.signal')}</th><th>{t('common.status')}</th><th>{t('admin.execUsersCovered')}</th><th>{t('admin.execFailed')}</th><th>{t('admin.cols.detail')}</th><th>{t('common.action')}</th></tr></thead>
          <tbody>
            {signalLogs.length === 0 && <tr><td colSpan={7} className="empty-cell">{t('common.noData')}</td></tr>}
            {signalLogs.map((log: any) => (
              <tr key={log.id}>
                <td className="text-xs">{localeDate(log.created_at, locale)}</td>
                <td>{log.action}</td>
                <td><span className="badge badge-gray">{log.status}</span></td>
                <td>{log.dispatched_count ?? 0}</td>
                <td>{log.error_count ?? 0}</td>
                <td className="text-sm">{log.source} · {log.payload?.strategy_id || '—'}</td>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost btn-xs"
                    onClick={() => { setTab('execution'); loadDispatchResults(log.id) }}
                  >
                    {t('admin.viewDispatchDetail')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-0 table-wrap">
        <div className="table-toolbar">
          <h3 className="card-heading panel-title-sm">{t('admin.tabStrategies')}</h3>
          <button className="btn btn-ghost btn-sm" type="button" onClick={exportStrategiesCsv}>{t('admin.exportCsv')}</button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('admin.cols.id')}</th><th>{t('admin.cols.strategyName')}</th><th>{t('admin.cols.strategyType')}</th>
              <th>{t('admin.cols.owner')}</th><th>{t('admin.cols.sharpe')}</th><th>{t('admin.cols.winRate')}</th>
              <th>{t('common.status')}</th><th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {strategies.length === 0 && (
              <tr><td colSpan={8} className="empty-cell">{t('common.noData')}</td></tr>
            )}
            {strategies.map((s: any) => (
              <tr key={s.id}>
                <td>{s.id}</td>
                <td>{s.name}</td>
                <td><span className="badge badge-gray">{s.strategy_type}</span></td>
                <td>{s.user_uid || `#${s.user_id}`}</td>
                <td>{s.sharpe?.toFixed(2) ?? '—'}</td>
                <td>{s.win_rate != null ? `${s.win_rate}%` : '—'}</td>
                <td><span className={`badge ${s.status === 'active' ? 'badge-green' : 'badge-gray'}`}>{s.status}</span></td>
                <td className="table-actions">
                  {s.status !== 'active' && (
                    <button className="btn btn-primary btn-xs" type="button" onClick={() => reviewStrategy(s.id, 'approve')}>{t('common.approve')}</button>
                  )}
                  {s.status === 'active' && (
                    <button className="btn btn-ghost btn-xs" type="button" onClick={() => reviewStrategy(s.id, 'pause')}>{t('common.disable')}</button>
                  )}
                  <button className="btn btn-ghost btn-xs" type="button" onClick={() => reviewStrategy(s.id, 'reject')}>{t('common.reject')}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  )
}
