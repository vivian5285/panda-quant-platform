import { useMemo, useState } from 'react'
import GlassCard from '../../../components/GlassCard'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

type AuditSubTab = 'ops' | 'webhook'

function webhookStatusBadgeClass(status: string) {
  if (status === 'dispatched') return 'badge badge-green'
  if (status === 'failed' || status === 'rejected') return 'badge badge-red'
  if (status === 'duplicate') return 'badge badge-yellow'
  if (status === 'processing' || status === 'accepted') return 'badge badge-blue'
  return 'badge badge-gray'
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="mono-cell text-xs" style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 320, overflow: 'auto' }}>
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

export default function AdminAuditTab() {
  const {
    t, locale, auditSearch, setAuditSearch, auditLogs, load, exportAuditCsv,
    webhookLogs, webhookSearch, setWebhookSearch, webhookStatusFilter, setWebhookStatusFilter,
    selectedWebhookId, webhookDetail, webhookDetailLoading,
    loadWebhookDetail, closeWebhookDetail, exportWebhookCsv, webhookEventStatusLabel,
  } = useAdmin()

  const [subTab, setSubTab] = useState<AuditSubTab>('ops')

  const filteredWebhookLogs = useMemo(() => {
    const q = webhookSearch.trim().toLowerCase()
    return webhookLogs.filter((l: any) => {
      if (webhookStatusFilter && l.event_status !== webhookStatusFilter) return false
      if (!q) return true
      const hay = [
        l.action,
        l.client_ip,
        l.fingerprint,
        l.error_message,
        l.response_status,
        JSON.stringify(l.tv_summary || {}),
      ].join(' ').toLowerCase()
      return hay.includes(q)
    })
  }, [webhookLogs, webhookSearch, webhookStatusFilter])

  const dispatchResultStatusLabel = (status: string) => {
    const map: Record<string, string> = {
      ok: t('admin.dispatchStatus.ok'),
      error: t('admin.dispatchStatus.error'),
      skipped: t('admin.dispatchStatus.skipped'),
      risk_blocked: t('admin.dispatchStatus.riskBlocked'),
    }
    return map[status] || status
  }

  return (
    <div>
      <div className="flex-gap-sm section-mb-md">
        <button
          type="button"
          className={`btn btn-sm ${subTab === 'ops' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setSubTab('ops')}
        >
          {t('admin.auditSubTabOps')}
        </button>
        <button
          type="button"
          className={`btn btn-sm ${subTab === 'webhook' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setSubTab('webhook')}
        >
          {t('admin.auditSubTabWebhook')}
        </button>
      </div>

      {subTab === 'ops' && (
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
      )}

      {subTab === 'webhook' && (
        <>
          <p className="text-muted text-sm section-mb-sm">{t('admin.webhookLogHint')}</p>
          <GlassCard className="p-0 table-wrap section-mb-md">
            <div className="table-toolbar form-stack p-4">
              <input
                className="input"
                placeholder={t('admin.webhookSearchPh')}
                value={webhookSearch}
                onChange={e => setWebhookSearch(e.target.value)}
              />
              <select className="input input-sm" value={webhookStatusFilter} onChange={e => setWebhookStatusFilter(e.target.value)}>
                <option value="">{t('admin.filterAll')}</option>
                <option value="dispatched">{webhookEventStatusLabel('dispatched')}</option>
                <option value="accepted">{webhookEventStatusLabel('accepted')}</option>
                <option value="processing">{webhookEventStatusLabel('processing')}</option>
                <option value="failed">{webhookEventStatusLabel('failed')}</option>
                <option value="rejected">{webhookEventStatusLabel('rejected')}</option>
                <option value="duplicate">{webhookEventStatusLabel('duplicate')}</option>
              </select>
              <button className="btn btn-ghost btn-sm" type="button" onClick={load}>{t('admin.refresh')}</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={exportWebhookCsv}>{t('admin.exportCsv')}</button>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('common.time')}</th>
                  <th>{t('admin.webhookCols.status')}</th>
                  <th>{t('common.action')}</th>
                  <th>{t('admin.webhookCols.tvSummary')}</th>
                  <th>{t('admin.cols.ip')}</th>
                  <th>{t('admin.webhookCols.latency')}</th>
                  <th>{t('admin.webhookCols.dispatch')}</th>
                  <th>{t('common.action')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredWebhookLogs.length === 0 && (
                  <tr><td colSpan={8} className="empty-cell">{t('common.noData')}</td></tr>
                )}
                {filteredWebhookLogs.map((l: any) => {
                  const tv = l.tv_summary || {}
                  const tvBrief = [tv.strategy_id, tv.symbol, tv.regime != null ? `R${tv.regime}` : '', tv.price != null ? `@${tv.price}` : '']
                    .filter(Boolean).join(' · ') || '—'
                  return (
                    <tr key={l.id} className={selectedWebhookId === l.id ? 'row-active' : undefined}>
                      <td className="text-xs">{localeDate(l.created_at, locale)}</td>
                      <td>
                        <span className={webhookStatusBadgeClass(l.event_status)}>
                          {webhookEventStatusLabel(l.event_status)}
                        </span>
                        {l.error_message ? (
                          <div className="text-muted text-xs" title={l.error_message}>{l.error_message.slice(0, 40)}</div>
                        ) : null}
                      </td>
                      <td>{l.action || '—'}</td>
                      <td className="text-xs cell-ellipsis" style={{ maxWidth: 220 }} title={JSON.stringify(tv)}>{tvBrief}</td>
                      <td>{l.client_ip || '—'}</td>
                      <td>{l.latency_ms != null ? `${l.latency_ms}ms` : '—'}</td>
                      <td>{l.dispatch_log_id ? `#${l.dispatch_log_id}` : '—'}</td>
                      <td>
                        <button type="button" className="btn btn-ghost btn-xs" onClick={() => loadWebhookDetail(l.id)}>
                          {t('admin.viewWebhookDetail')}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </GlassCard>

          {selectedWebhookId && (
            <GlassCard className="p-4 section-mb-md">
              <div className="flex-between-wrap section-mb-md">
                <div>
                  <h3 className="card-heading">{t('admin.webhookDetailTitle')}</h3>
                  <p className="text-muted text-sm">
                    #{selectedWebhookId}
                    {webhookDetail?.action ? ` · ${webhookDetail.action}` : ''}
                    {webhookDetail?.created_at ? ` · ${localeDate(webhookDetail.created_at, locale)}` : ''}
                  </p>
                </div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={closeWebhookDetail}>
                  {t('common.cancel')}
                </button>
              </div>

              {webhookDetailLoading ? (
                <p className="text-muted">{t('common.loading')}</p>
              ) : !webhookDetail ? (
                <p className="text-muted">{t('common.noData')}</p>
              ) : (
                <div className="form-stack">
                  <div className="stat-grid">
                    <div><span className="text-muted text-xs">{t('admin.webhookCols.status')}</span><div><span className={webhookStatusBadgeClass(webhookDetail.event_status)}>{webhookEventStatusLabel(webhookDetail.event_status)}</span></div></div>
                    <div><span className="text-muted text-xs">{t('admin.webhookCols.httpStatus')}</span><div>{webhookDetail.http_status ?? '—'}</div></div>
                    <div><span className="text-muted text-xs">{t('admin.cols.ip')}</span><div>{webhookDetail.client_ip || '—'}</div></div>
                    <div><span className="text-muted text-xs">{t('admin.webhookCols.latency')}</span><div>{webhookDetail.latency_ms != null ? `${webhookDetail.latency_ms}ms` : '—'}</div></div>
                    <div><span className="text-muted text-xs">{t('admin.webhookCols.fingerprint')}</span><div className="mono-cell text-xs">{webhookDetail.fingerprint || '—'}</div></div>
                    <div><span className="text-muted text-xs">{t('admin.webhookCols.dispatch')}</span><div>{webhookDetail.dispatch_log_id ? `#${webhookDetail.dispatch_log_id}` : '—'}</div></div>
                  </div>

                  {webhookDetail.error_message && (
                    <div className="alert alert-error text-sm">{webhookDetail.error_message}</div>
                  )}

                  <div>
                    <h4 className="panel-title-sm section-mb-sm">{t('admin.webhookTvSummary')}</h4>
                    <JsonBlock data={webhookDetail.tv_summary || {}} />
                  </div>

                  <div>
                    <h4 className="panel-title-sm section-mb-sm">{t('admin.webhookPayload')}</h4>
                    <JsonBlock data={webhookDetail.payload || {}} />
                  </div>

                  {webhookDetail.dispatch && (
                    <div>
                      <h4 className="panel-title-sm section-mb-sm">{t('admin.webhookDispatch')}</h4>
                      <JsonBlock data={webhookDetail.dispatch} />
                      {webhookDetail.dispatch_payload && (
                        <div className="section-mt-sm">
                          <p className="text-muted text-xs section-mb-sm">{t('admin.webhookDispatchPayload')}</p>
                          <JsonBlock data={webhookDetail.dispatch_payload} />
                        </div>
                      )}
                    </div>
                  )}

                  {(webhookDetail.user_results?.length ?? 0) > 0 && (
                    <div>
                      <h4 className="panel-title-sm section-mb-sm">{t('admin.webhookUserResults')}</h4>
                      <div className="table-wrap">
                        <table className="data-table data-table-sm">
                          <thead>
                            <tr>
                              <th>{t('admin.cols.uid')}</th>
                              <th>{t('common.user')}</th>
                              <th>{t('common.status')}</th>
                              <th>{t('admin.cols.detail')}</th>
                              <th>{t('admin.cols.slippage')}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {webhookDetail.user_results.map((r: any) => (
                              <tr key={r.id ?? `${r.user_id}-${r.status}`}>
                                <td>{r.user_uid || `#${r.user_id}`}</td>
                                <td>{r.user_email || r.user_nickname || '—'}</td>
                                <td>{dispatchResultStatusLabel(r.status)}</td>
                                <td className="text-xs">{r.reason || '—'}</td>
                                <td>{r.slippage != null ? r.slippage.toFixed(4) : '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </GlassCard>
          )}
        </>
      )}
    </div>
  )
}
