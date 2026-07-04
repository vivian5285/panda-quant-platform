import { Fragment, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import TradeLogDetailPanel, { resolveDetail } from '../../../components/TradeLogDetailPanel'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

export default function AdminSystemTab() {
  const {
    t, locale, webhookPayload, setWebhookPayload, runWebhookTest,
    online, monitor, signalLogs, riskAlerts, loginRecords, auditLogs,
    tradeLogs, exportTradeLogsCsv, orders, formatOrderUser, startupAudit, setTab,
    adminPwdDraft, setAdminPwdDraft, changeAdminPassword,
    platformPublicSettings, platformPublicDraft, setPlatformPublicDraft, savePlatformPublicSettings,
    webhookSettings, webhookSecretDraft, setWebhookSecretDraft, saveWebhookSettings, clearWebhookSettings,
  } = useAdmin()
  const [expandedLog, setExpandedLog] = useState<number | null>(null)

  const allExchanges = platformPublicSettings?.all_exchanges || ['binance', 'okx', 'gate', 'deepcoin']
  const exchangeLabelKeys: Record<string, string> = {
    binance: 'api.exchangeBinance',
    okx: 'api.exchangeOkx',
    gate: 'api.exchangeGate',
    deepcoin: 'api.exchangeDeepcoin',
  }

  const toggleExchange = (id: string) => {
    const cur = platformPublicDraft?.enabled_exchanges || ['binance']
    const next = cur.includes(id)
      ? cur.filter((x: string) => x !== id)
      : [...cur, id]
    if (next.length === 0) return
    setPlatformPublicDraft({ ...platformPublicDraft, enabled_exchanges: next })
  }

  const audits = startupAudit?.audits || []
  const failures = startupAudit?.failures || []
  const secWarnings = startupAudit?.security_warnings || []
  const infraNotes = startupAudit?.infra_notes || []
  const productionReady = startupAudit?.production_ready
  const hasDepositInfraNote = infraNotes.some((n: string) => n.includes('收款地址') || n.includes('二维码'))

  return (
    <>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="panel-title-sm mb-md">{t('admin.platformPublicSettingsTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.platformPublicSettingsHint')}</p>
        <form onSubmit={savePlatformPublicSettings} className="form-stack">
          <div>
            <p className="text-sm-strong section-mb-xs">{t('admin.enabledExchangesTitle')}</p>
            <p className="text-muted text-xs section-mb-sm">{t('admin.enabledExchangesHint')}</p>
            <p className="text-muted text-xs section-mb-sm">{t('admin.enabledExchangesTradingHint')}</p>
            <div className="platform-exchange-toggles">
              {allExchanges.map((id: string) => (
                <label key={id} className="platform-exchange-toggle">
                  <input
                    type="checkbox"
                    checked={(platformPublicDraft?.enabled_exchanges || []).includes(id)}
                    onChange={() => toggleExchange(id)}
                  />
                  <span>{t(exchangeLabelKeys[id] as any) || id}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="form-field section-mt-sm">
            <label className="form-label">{t('admin.supportTelegramTitle')}</label>
            <input
              className="input"
              placeholder={t('admin.supportTelegramPh')}
              value={platformPublicDraft?.support_telegram || ''}
              onChange={e => setPlatformPublicDraft({ ...platformPublicDraft, support_telegram: e.target.value })}
            />
            <p className="text-muted form-hint-sm">{t('admin.supportTelegramHint')}</p>
          </div>
          <button className="btn btn-primary btn-sm" type="submit">{t('common.save')}</button>
        </form>
      </GlassCard>

      <div className="grid-2-col-gap section-mb-lg">
        <GlassCard className="p-6">
          <h3 className="panel-title-sm mb-md">{t('admin.platformSettingsLinkTitle')}</h3>
          <p className="text-muted text-sm section-mb-sm">{t('admin.platformSettingsLinkHint')}</p>
          <div className="flex-gap-sm flex-wrap">
            <button className="btn btn-primary btn-sm" type="button" onClick={() => setTab('addresses')}>{t('admin.tabAddresses')}</button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setTab('addresses', 'rpc')}>{t('admin.walletHub.sections.rpc')}</button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setTab('addresses', 'dingtalk')}>{t('admin.walletHub.sections.dingtalk')}</button>
          </div>
        </GlassCard>
        <GlassCard className="p-6">
          <h3 className="panel-title-sm mb-md">{t('admin.adminPasswordTitle')}</h3>
          <p className="text-muted text-sm section-mb-sm">{t('admin.adminPasswordHint')}</p>
          <form onSubmit={changeAdminPassword} className="form-stack">
            <input className="input" type="password" autoComplete="current-password" placeholder={t('admin.currentPasswordPh')}
              value={adminPwdDraft.current} onChange={e => setAdminPwdDraft((d: { current: string; next: string; confirm: string }) => ({ ...d, current: e.target.value }))} required />
            <input className="input" type="password" autoComplete="new-password" placeholder={t('admin.newPasswordPh')}
              value={adminPwdDraft.next} onChange={e => setAdminPwdDraft((d: { current: string; next: string; confirm: string }) => ({ ...d, next: e.target.value }))} required />
            <input className="input" type="password" autoComplete="new-password" placeholder={t('admin.confirmPasswordPh')}
              value={adminPwdDraft.confirm} onChange={e => setAdminPwdDraft((d: { current: string; next: string; confirm: string }) => ({ ...d, confirm: e.target.value }))} required />
            <button className="btn btn-primary btn-sm" type="submit">{t('admin.changePassword')}</button>
          </form>
        </GlassCard>
      </div>
      {productionReady === false && (
        <GlassCard className="p-6 section-mb-lg production-checklist-card">
          <h3 className="card-heading">{t('admin.productionChecklistTitle')}</h3>
          <p className="text-muted text-sm section-mb-sm">{t('admin.productionChecklistHint')}</p>
          <ul className="production-checklist-list">
            {secWarnings.map((w: string, i: number) => (
              <li key={`chk-sec-${i}`} className="text-sm text-red">⚠ {w}</li>
            ))}
          </ul>
          <p className="text-muted text-xs section-mt-sm">{t('admin.productionStrictNote')}</p>
        </GlassCard>
      )}
      {hasDepositInfraNote && (
        <GlassCard className="p-4 section-mb-lg">
          <p className="text-sm section-mb-sm">{t('admin.depositInfraHint')}</p>
          <button className="btn btn-primary btn-sm" type="button" onClick={() => setTab('addresses')}>
            {t('admin.tabAddresses')}
          </button>
        </GlassCard>
      )}
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.startupAuditTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.startupAuditHint')}</p>
        <div className="admin-health-list section-mb-sm">
          <div><span>{t('admin.activeSupervisors')}</span><strong>{startupAudit?.active_supervisors ?? monitor?.active_supervisors ?? 0}</strong></div>
          <div><span>{t('admin.startupWithPosition')}</span><strong>{audits.filter((a: any) => a.has_position).length}</strong></div>
          <div><span>{t('admin.startupMonitoring')}</span><strong>{audits.filter((a: any) => a.monitoring).length}</strong></div>
          <div><span>{t('admin.startupFailures')}</span><strong className={failures.length ? 'text-red' : ''}>{failures.length}</strong></div>
        </div>
        {(secWarnings.length > 0 || infraNotes.length > 0) && (
          <div className="section-mb-sm">
            {secWarnings.map((w: string, i: number) => (
              <div key={`sec-${i}`} className="text-sm text-red section-mb-xs">⚠ {w}</div>
            ))}
            {infraNotes.map((n: string, i: number) => (
              <div key={`infra-${i}`} className="text-sm text-muted section-mb-xs">· {n}</div>
            ))}
          </div>
        )}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('common.user')}</th>
                <th>{t('trades.side')}</th>
                <th>{t('admin.cols.qty')}</th>
                <th>{t('admin.startupAligned')}</th>
                <th>{t('admin.startupMonitoring')}</th>
              </tr>
            </thead>
            <tbody>
              {audits.length === 0 && <tr><td colSpan={5} className="empty-cell">{t('common.noData')}</td></tr>}
              {audits.map((a: any) => (
                <tr key={a.user_id}>
                  <td>{a.uid || `#${a.user_id}`}</td>
                  <td>{a.has_position ? a.side : '—'}</td>
                  <td>{a.has_position ? a.qty : '—'}</td>
                  <td>{a.has_position ? (a.direction_aligned ? t('common.yes') : t('common.no')) : '—'}</td>
                  <td>{a.monitoring ? t('common.yes') : t('common.no')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg webhook-settings-card">
        <h3 className="panel-title-sm mb-md">{t('admin.webhookSettingsTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.webhookSettingsHint')}</p>
        <p className={`text-xs section-mb-sm ${webhookSettings?.configured && !webhookSettings?.insecure ? 'text-green' : 'text-red'}`}>
          {webhookSettings?.configured
            ? webhookSettings.insecure
              ? t('admin.webhookSecretInsecure')
              : `${t('admin.webhookSecretConfigured')}${webhookSettings.secret_preview ? ` · ${webhookSettings.secret_preview}` : ''}${webhookSettings.source ? ` (${webhookSettings.source === 'runtime' ? t('admin.depositSourceRuntime') : t('admin.depositSourceEnv')})` : ''}`
            : t('admin.webhookSecretMissing')}
        </p>
        {webhookSettings?.webhook_url && (
          <div className="section-mb-sm">
            <p className="text-sm-strong section-mb-xs">{t('admin.webhookUrlTitle')}</p>
            <code className="webhook-url-display">{webhookSettings.webhook_url}</code>
            <p className="text-muted form-hint-sm">{t('admin.webhookUrlHint')}</p>
          </div>
        )}
        <form onSubmit={saveWebhookSettings} className="form-stack section-mb-md">
          <div className="form-field">
            <label className="form-label">{t('admin.webhookSecretLabel')}</label>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={t('admin.webhookSecretPh')}
              value={webhookSecretDraft}
              onChange={e => setWebhookSecretDraft(e.target.value)}
            />
            <p className="text-muted form-hint-sm">{t('admin.webhookSecretFieldHint', { min: webhookSettings?.min_length || 12 })}</p>
          </div>
          <div className="flex-gap-sm flex-wrap">
            <button className="btn btn-primary btn-sm" type="submit" disabled={!webhookSecretDraft.trim()}>{t('common.save')}</button>
            {webhookSettings?.configured && (
              <button className="btn btn-ghost btn-sm" type="button" onClick={clearWebhookSettings}>{t('admin.webhookSecretClear')}</button>
            )}
          </div>
        </form>
        <div className="webhook-tv-guide">
          <p className="text-sm-strong section-mb-xs">{t('admin.webhookTvGuideTitle')}</p>
          <p className="text-muted text-xs section-mb-sm">{t('admin.webhookTvGuideHint')}</p>
          <ul className="webhook-tv-field-list text-xs">
            <li><strong>LONG / SHORT</strong> — {t('admin.webhookTvFieldEntry')}</li>
            <li><strong>CLOSE_TP3</strong> — {t('admin.webhookTvFieldTp3')}</li>
            <li><strong>CLOSE_PROTECT</strong> — {t('admin.webhookTvFieldProtect')}</li>
          </ul>
          <pre className="webhook-tv-sample input-mono text-xs section-mt-sm">{`{
  "action": "LONG",
  "secret": "<${t('admin.webhookTvSampleSecret')}>",
  "price": 3500,
  "regime": 1,
  "atr": 12.5,
  "tv_tp1": 3600,
  "tv_tp2": 3700,
  "tv_tp3": 3800
}`}</pre>
        </div>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.webhookTestTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.webhookTestHint')}</p>
        <textarea className="input input-mono section-mb-sm" rows={8} value={webhookPayload} onChange={e => setWebhookPayload(e.target.value)} />
        <button className="btn btn-primary btn-sm" type="button" onClick={runWebhookTest}>{t('admin.webhookTestRun')}</button>
      </GlassCard>
      <div className="stat-grid">
        <StatCard label={t('admin.onlineUsers')} value={String(online?.recent_logins_15m || 0)} />
        <StatCard label={t('admin.activeSupervisors')} value={String(monitor?.active_supervisors || 0)} />
        <StatCard label={t('admin.webhookStatus')} value={monitor?.webhook_status || '—'} />
        <StatCard label={t('admin.binanceLatency')} value={monitor?.binance_latency_ms > 0 ? `${monitor.binance_latency_ms}ms` : '—'} />
        <StatCard label={t('admin.webhookTotal')} value={String(monitor?.webhook_received_total || 0)} />
        <StatCard label={t('admin.queueDepth')} value={String(monitor?.queue_depth ?? 0)} />
        <StatCard label={t('admin.redis')} value={monitor?.redis_connected ? t('common.statusOk') : t('common.none')} />
        <StatCard label={t('admin.webhookLast')} value={monitor?.webhook_last_received_at ? localeDate(monitor.webhook_last_received_at, locale) : '—'} />
      </div>
      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="table-toolbar table-toolbar-flush"><h3 className="card-heading">{t('admin.webhookReceiveLogs')}</h3></div>
        <table className="data-table">
          <thead><tr><th>{t('common.time')}</th><th>{t('trades.signal')}</th><th>{t('admin.cols.source')}</th><th>{t('admin.execUsersCovered')}</th><th>{t('admin.execFailed')}</th><th>{t('common.status')}</th></tr></thead>
          <tbody>
            {signalLogs.length === 0 && <tr><td colSpan={6} className="empty-cell">{t('common.noData')}</td></tr>}
            {signalLogs.slice(0, 30).map((log: any) => (
              <tr key={log.id}>
                <td className="text-xs">{localeDate(log.created_at, locale)}</td>
                <td>{log.action}</td>
                <td>{log.source}</td>
                <td>{log.dispatched_count ?? 0}</td>
                <td>{log.error_count ?? 0}</td>
                <td><span className="badge badge-gray">{log.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.riskAlerts')}</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>{t('common.time')}</th><th>{t('admin.cols.type')}</th><th>{t('admin.cols.detail')}</th></tr></thead>
            <tbody>
              {riskAlerts.length === 0 && <tr><td colSpan={3} className="empty-cell">{t('admin.noRiskAlerts')}</td></tr>}
              {riskAlerts.slice(0, 20).map((r: any, i: number) => (
                <tr key={i}><td>{localeDate(r.created_at || r.timestamp, locale)}</td><td>{r.alert_type || r.type}</td><td>{r.message || r.title}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.loginRecords')}</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>{t('common.user')}</th><th>{t('admin.cols.ip')}</th><th>{t('admin.device')}</th><th>{t('common.time')}</th></tr></thead>
            <tbody>
              {loginRecords.length === 0 && <tr><td colSpan={4} className="empty-cell">{t('admin.noLoginRecords')}</td></tr>}
              {loginRecords.slice(0, 30).map((r: any) => (
                <tr key={r.id}><td>{r.user_id || r.uid}</td><td>{r.ip_address || r.ip}</td><td>{r.user_agent?.slice(0, 40) || '—'}</td><td>{localeDate(r.created_at, locale)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="card-heading">{t('admin.auditLogs')}</h3>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>{t('common.action')}</th><th>{t('common.user')}</th><th>{t('admin.cols.ip')}</th><th>{t('common.time')}</th></tr></thead>
          <tbody>{auditLogs.slice(0, 30).map((l: any) => <tr key={l.id}><td>{l.action}</td><td>{l.user_id}</td><td>{l.ip_address}</td><td>{localeDate(l.created_at, locale)}</td></tr>)}</tbody></table></div>
      </GlassCard>
      <GlassCard className="p-0 table-wrap section-mb-lg">
        <div className="table-toolbar table-toolbar-between table-toolbar-flush">
          <h3 className="card-heading">{t('admin.allTradeLogs')}</h3>
          <button className="btn btn-ghost btn-sm" type="button" onClick={exportTradeLogsCsv}>{t('admin.exportCsv')}</button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('common.time')}</th><th>{t('admin.cols.owner')}</th><th>{t('admin.cols.type')}</th>
              <th>{t('admin.cols.detail')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tradeLogs.length === 0 && <tr><td colSpan={5} className="empty-cell">{t('common.noData')}</td></tr>}
            {tradeLogs.slice(0, 50).map((l: any) => {
              const d = resolveDetail(l)
              const isOpen = expandedLog === l.id
              const verified = d.live_verified === true
              return (
                <Fragment key={l.id}>
                  <tr className="trades-row" onClick={() => setExpandedLog(isOpen ? null : l.id)}>
                    <td className="text-xs">{localeDate(l.created_at, locale)}</td>
                    <td>{l.user_uid || `#${l.user_id}`}</td>
                    <td>
                      <span className={`badge ${verified ? 'badge-green' : 'badge-gray'}`}>{l.event_type}</span>
                    </td>
                    <td className="text-sm cell-max-md">{l.message}</td>
                    <td className="trades-expand-icon">{isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</td>
                  </tr>
                  {isOpen && (
                    <tr className="trades-detail-row">
                      <td colSpan={5}>
                        <div className="trades-detail-panel">
                          <p><strong>{t('tradeLog.logDetail')}</strong></p>
                          <TradeLogDetailPanel log={l} />
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </GlassCard>
      <GlassCard className="p-0 table-wrap">
        <h3 className="card-heading p-6 mb-0">{t('admin.allOrders')}</h3>
        <table className="data-table"><thead><tr><th>{t('admin.cols.id')}</th><th>{t('admin.cols.owner')}</th><th>{t('trades.side')}</th><th>{t('trades.pnl')}</th><th>{t('common.status')}</th></tr></thead>
          <tbody>{orders.slice(0, 50).map((o: any) => <tr key={o.id}><td>{o.id}</td><td>{formatOrderUser(o)}</td><td>{o.side}</td><td>{o.realized_pnl}</td><td>{o.status}</td></tr>)}</tbody></table>
      </GlassCard>
    </>
  )
}
