import GlassCard from '../../../components/GlassCard'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

export default function AdminAuditTab() {
  const {
    t, locale, auditSearch, setAuditSearch, auditLogs, load, exportAuditCsv,
  } = useAdmin()

  return (
    <GlassCard className="p-0 table-wrap">
      <div className="table-toolbar form-stack p-4">
        <input className="input" placeholder={t('admin.auditSearchPh')} value={auditSearch}
          onChange={e => setAuditSearch(e.target.value)} />
        <button className="btn btn-ghost btn-sm" type="button" onClick={load}>{t('admin.refresh')}</button>
        <button className="btn btn-ghost btn-sm" type="button" onClick={exportAuditCsv}>{t('admin.exportCsv')}</button>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>{t('common.action')}</th><th>{t('common.user')}</th><th>{t('admin.cols.actor')}</th><th>{t('admin.cols.type')}</th>
            <th>{t('admin.cols.resource')}</th><th>{t('admin.cols.ip')}</th><th>{t('common.time')}</th>
          </tr>
        </thead>
        <tbody>
          {auditLogs.length === 0 && <tr><td colSpan={7} className="empty-cell">{t('common.noData')}</td></tr>}
          {auditLogs.map((l: any) => (
            <tr key={l.id}>
              <td>{l.action}</td>
              <td>{l.user_id ?? '—'}</td>
              <td>{l.actor_id ?? '—'}</td>
              <td>{l.resource_type ?? '—'}</td>
              <td className="text-xs">
                {l.resource_id ?? '—'}
                {l.detail ? (
                  <div className="text-muted" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {JSON.stringify(l.detail)}
                  </div>
                ) : null}
              </td>
              <td>{l.ip_address}</td>
              <td>{localeDate(l.created_at, locale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </GlassCard>
  )
}
