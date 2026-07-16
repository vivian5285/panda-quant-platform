import StatCard from '../../../components/StatCard'
import GlassCard from '../../../components/GlassCard'
import TabBar from '../../../components/TabBar'
import TradeLogDetailPanel from '../../../components/TradeLogDetailPanel'
import { adminApi } from '../../../api'
import { toast } from '../../../store/toast'
import { localeDate } from '../../../i18n'
import { useAdmin } from '../AdminContext'

export default function AdminUsersTab() {
  const {
    t, locale, users, abnormalUsers, selectedUserIds, batchNotifyTitle, setBatchNotifyTitle,
    batchNotifyMessage, setBatchNotifyMessage, userSearch, setUserSearch,
    userApiFilter, setUserApiFilter, userPauseFilter, setUserPauseFilter,
    userFlagFilter, setUserFlagFilter, selectedUserId, userDetail, userDetailLoading, userDetailError,
    userTrades, userLogs,
    userDetailTab, setUserDetailTab, userReferralStats, userPrincipalHistory, userTradingCtrl, linkedExchangeAccounts, userSubAccountFilings,
    load, loadUserDetail, closeUserDetail, exportUsersCsv, toggleUserSelect, toggleSelectAllUsers,
    runBatchNotify, runBatchPause, forceUserPause, forceCloseUser, setUserRisk, toggleSettlementDefer, toggleReferralOverride,
    exportUserLogsCsv, setUserLogs,
  } = useAdmin()

  if (selectedUserId && (userDetailLoading || (!userDetail && !userDetailError))) {
    return (
      <GlassCard className="p-8"><p className="text-muted">{t('common.loading')}</p></GlassCard>
    )
  }

  if (selectedUserId && userDetailError && !userDetail) {
    return (
      <div>
        <button className="btn btn-ghost btn-sm section-mb-sm" onClick={closeUserDetail}>{t('admin.backToList')}</button>
        <GlassCard className="p-8">
          <p className="text-red section-mb-sm">{userDetailError}</p>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => loadUserDetail(selectedUserId)}>
            {t('admin.accountsRefresh')}
          </button>
        </GlassCard>
      </div>
    )
  }

  if (selectedUserId && userDetail) {
    return (
      <div>
        <button className="btn btn-ghost btn-sm section-mb-sm" onClick={closeUserDetail}>{t('admin.backToList')}</button>
        <GlassCard className="p-6 section-mb-sm">
          <h3 className="text-md-strong mb-sm">{t('admin.userDetail')} · {userDetail.profile?.uid}</h3>
          <div className="stat-grid section-mb-sm">
            <StatCard label={t('dashboard.balance')} value={`$${userDetail.dashboard?.balance?.toFixed(2) ?? '0'}`} />
            <StatCard label={t('dashboard.tradeCyclePnl')} value={`$${userDetail.dashboard?.trade_cycle_pnl?.toFixed(2) ?? '0'}`} />
            <StatCard label={t('dashboard.equityCyclePnl')} value={`$${userDetail.dashboard?.cycle_pnl?.toFixed(2) ?? '0'}`} />
            <StatCard label={t('admin.tradeCount')} value={String(userDetail.trade_count ?? 0)} />
            <StatCard label={t('admin.logCount')} value={String(userDetail.log_count ?? 0)} />
          </div>
          <div className="info-grid-auto text-sm">
            <div><span className="text-muted">{t('common.email')}:</span> {userDetail.profile?.email || t('common.none')}</div>
            <div><span className="text-muted">{t('common.phone')}:</span> {userDetail.profile?.phone || t('common.none')}</div>
            <div><span className="text-muted">{t('admin.cols.api')}:</span> {userDetail.profile?.api_status}</div>
            <div><span className="text-muted">{t('admin.exchangeAccountMode')}:</span> {userDetail.profile?.api_account_mode === 'sub' ? t('admin.accountModeSub') : t('admin.accountModeMaster')}</div>
            {userDetail.profile?.exchange_uid && (
              <div><span className="text-muted">{t('admin.exchangeUid')}:</span> {userDetail.profile.exchange_uid}</div>
            )}
            {userDetail.profile?.master_exchange_uid && userDetail.profile?.api_account_mode === 'sub' && (
              <div><span className="text-muted">{t('admin.masterExchangeUid')}:</span> {userDetail.profile.master_exchange_uid}</div>
            )}
            <div><span className="text-muted">{t('admin.apiKeyMask')}:</span> {userDetail.api_key_mask || t('common.none')}</div>
            <div><span className="text-muted">{t('admin.cols.cumulativePnl')}:</span> ${userDetail.cumulative_pnl?.toFixed(2) ?? '0'}</div>
            <div><span className="text-muted">{t('admin.cols.execSuccessRate')}:</span> {userDetail.execution_success_rate != null ? `${userDetail.execution_success_rate}%` : '—'}</div>
            <div><span className="text-muted">{t('admin.supervisorActive')}:</span> {userDetail.supervisor_active ? t('common.yes') : t('common.none')}</div>
            <div><span className="text-muted">{t('dashboard.principal')}:</span> ${userDetail.profile?.initial_principal?.toFixed(2) ?? '0'}</div>
            {userDetail.risk_flag && (
              <div className="text-red"><span className="text-muted">{t('admin.flagged')}:</span> {t(`admin.flagReason.${userDetail.risk_flag_reason}` as any) || userDetail.risk_flag_reason}</div>
            )}
            {linkedExchangeAccounts?.accounts?.length > 0 && (
              <div className="section-mt-sm">
                <p className="text-sm-strong section-mb-sm">{t('admin.linkedExchangeAccounts')} ({linkedExchangeAccounts.master_uid})</p>
                <ul className="text-sm">
                  {linkedExchangeAccounts.accounts.map((a: any) => (
                    <li key={`${a.user_id}-${a.exchange_uid}`}>
                      {a.platform_uid} · {a.exchange_uid} · {a.account_mode === 'sub' ? t('admin.accountModeSub') : t('admin.accountModeMaster')}
                      {!a.is_active ? ` · ${t('admin.flagged')}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {linkedExchangeAccounts && !linkedExchangeAccounts.accounts?.length && userDetail.profile?.exchange_uid && (
              <div className="text-muted text-sm">{t('admin.linkedAccountsEmpty')}</div>
            )}
            {userSubAccountFilings?.length > 0 && (
              <div className="section-mt-sm">
                <p className="text-sm-strong section-mb-sm">{t('admin.subAccountFilingsTitle')}</p>
                <ul className="text-sm compliance-filing-list">
                  {userSubAccountFilings.map((f: any) => (
                    <li key={f.id} className="compliance-filing-item">
                      <span className="mono-cell">{f.sub_exchange_uid}</span>
                      {f.sub_label ? ` · ${f.sub_label}` : ''}
                      <span className="text-muted text-xs"> · {f.exchange}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {userTradingCtrl?.referral_blocked && !userTradingCtrl?.referral_invite_override && (
              <div className="section-mt-md p-4 settlement-defer-panel">
                <p className="text-sm-strong section-mb-xs">{t('admin.referralOverrideTitle')}</p>
                <p className="text-sm text-muted section-mb-sm">{t('admin.referralOverrideHint')}</p>
                <p className="text-sm text-red section-mb-sm">
                  {userTradingCtrl?.referral_block_reason === 'downline_credit_default'
                    ? t('referrals.downlineCreditDefaultBannerBody')
                    : t('referrals.creditDefaultBannerBody')}
                </p>
                <input
                  className="input section-mb-sm"
                  placeholder={t('admin.referralOverrideNotePh')}
                  id="referral-override-note"
                />
                <button
                  className="btn btn-primary btn-sm"
                  type="button"
                  onClick={() => {
                    const el = document.getElementById('referral-override-note') as HTMLInputElement | null
                    toggleReferralOverride(true, el?.value || '')
                  }}
                >
                  {t('admin.referralOverrideAllow')}
                </button>
              </div>
            )}
            {userTradingCtrl?.referral_invite_override && (
              <div className="section-mt-sm">
                <span className="badge badge-green">{t('admin.referralOverrideAllow')}</span>
                {userTradingCtrl?.referral_override_note && (
                  <p className="text-sm text-muted section-mt-xs">{userTradingCtrl.referral_override_note}</p>
                )}
                <button className="btn btn-ghost btn-sm section-mt-sm" type="button" onClick={() => toggleReferralOverride(false)}>
                  {t('admin.referralOverrideRevoke')}
                </button>
              </div>
            )}
            {userTradingCtrl?.settlement_blocked && (
              <div className="section-mt-md p-4 settlement-defer-panel">
                <p className="text-sm text-muted section-mb-sm">{t('admin.settlementDeferHint')}</p>
                {userTradingCtrl?.settlement_fee_deferred ? (
                  <>
                    <span className="badge badge-green">{t('admin.settlementDeferAllowed')}</span>
                    <button className="btn btn-ghost btn-sm section-mt-sm" type="button" onClick={() => toggleSettlementDefer(false)}>
                      {t('admin.settlementDeferRevoke')}
                    </button>
                  </>
                ) : (
                  <button className="btn btn-primary btn-sm" type="button" onClick={() => toggleSettlementDefer(true)}>
                    {t('admin.settlementDeferAllow')}
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="flex-gap-sm section-mt-md">
            {!userTradingCtrl?.trading_paused ? (
              <button className="btn btn-danger btn-sm" onClick={() => forceUserPause(true)}>{t('admin.forcePause')}</button>
            ) : (
              <button className="btn btn-primary btn-sm" onClick={() => forceUserPause(false)}>{t('admin.forceResume')}</button>
            )}
            <button className="btn btn-danger btn-sm" onClick={forceCloseUser}>{t('admin.forceClose')}</button>
            <label className="trades-filter ml-sm">
              <span className="text-muted">{t('risk.levelTitle')}</span>
              <select value={userTradingCtrl?.risk_level || 'balanced'} onChange={e => setUserRisk(e.target.value)}>
                <option value="conservative">{t('risk.levels.conservative')}</option>
                <option value="balanced">{t('risk.levels.balanced')}</option>
                <option value="aggressive">{t('risk.levels.aggressive')}</option>
              </select>
            </label>
          </div>
        </GlassCard>
        <TabBar
          tabs={[
            { key: 'overview', label: t('dashboard.title') },
            { key: 'trades', label: t('admin.userTrades') },
            { key: 'logs', label: t('admin.userLogs') },
            { key: 'referrals', label: t('admin.referralStats') },
            { key: 'principal', label: t('admin.principalHistory') },
          ]}
          active={userDetailTab}
          onChange={k => setUserDetailTab(k as typeof userDetailTab)}
        />
        {userDetailTab === 'overview' && (() => {
          const op = userDetail.dashboard?.open_position
          const list = op?.all_positions?.length ? op.all_positions : (op?.has_position ? [op] : [])
          if (!list.length) return null
          return (
            <GlassCard className="p-4 section-mt-md">
              <p className="text-md-strong mb-sm">{t('dashboard.currentPosition')}</p>
              {list.map((pos: any, idx: number) => (
                <div key={`${pos.symbol || 'p'}-${idx}`} className="stat-grid stat-grid-flush section-mb-sm">
                  <div className="stat-tile">
                    <p className="text-muted text-xs">{t('common.symbol')}</p>
                    <p className="text-md-strong">{pos.symbol || 'ETHUSDT'}</p>
                  </div>
                  <div className="stat-tile">
                    <p className="text-muted text-xs">{t('dashboard.direction')}</p>
                    <p className="text-md-strong">{pos.side}</p>
                  </div>
                  <div className="stat-tile">
                    <p className="text-muted text-xs">{t('dashboard.qty')}</p>
                    <p className="text-md-strong">{pos.qty}</p>
                  </div>
                  <div className="stat-tile">
                    <p className="text-muted text-xs">{t('dashboard.entry')}</p>
                    <p className="text-md-strong">${pos.entry_price?.toFixed?.(2) ?? pos.entry_price}</p>
                  </div>
                  <div className="stat-tile">
                    <p className="text-muted text-xs">{t('dashboard.floatingPnl')}</p>
                    <p className={(pos.unrealized_pnl || 0) >= 0 ? 'text-green text-md-strong' : 'text-red text-md-strong'}>
                      ${Number(pos.unrealized_pnl || 0).toFixed(2)}
                    </p>
                  </div>
                </div>
              ))}
            </GlassCard>
          )
        })()}
        {userDetailTab === 'trades' && (
          <GlassCard className="p-0 table-wrap section-mt-md">
            <table className="data-table">
              <thead><tr><th>{t('admin.cols.id')}</th><th>{t('trades.symbol')}</th><th>{t('trades.side')}</th><th>{t('trades.qty')}</th><th>{t('trades.entry')}</th><th>{t('trades.pnl')}</th><th>{t('common.status')}</th></tr></thead>
              <tbody>
                {userTrades.map((tr: any) => (
                  <tr key={tr.id}>
                    <td>{tr.id}</td><td>{tr.symbol || 'ETHUSDT'}</td><td>{tr.side}</td><td>{tr.quantity}</td><td>{tr.entry_price}</td>
                    <td className={tr.realized_pnl >= 0 ? 'text-green' : ''}>{tr.realized_pnl?.toFixed(2)}</td><td>{tr.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GlassCard>
        )}
        {userDetailTab === 'logs' && (
          <div className="section-mt-md">
            <div className="table-toolbar table-toolbar-between">
              <span className="text-muted text-sm">{t('admin.userLogs')}</span>
              <div className="flex-gap-sm">
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => {
                  if (!selectedUserId) return
                  adminApi.syncUserExchangeLogs(selectedUserId).then(res => {
                    toast.success(t('trades.syncOk', { n: res?.synced ?? 0 }))
                    adminApi.userLogs(selectedUserId).then(setUserLogs)
                  }).catch(() => toast.error(t('trades.syncFail')))
                }}>{t('admin.syncUserBinance')}</button>
                <button className="btn btn-ghost btn-sm" type="button" onClick={exportUserLogsCsv}>{t('admin.exportUserLogs')}</button>
              </div>
            </div>
            <div className="log-list-stack">
              {userLogs.map((log: any) => (
                <GlassCard key={log.id} className="p-4 trade-log-card">
                  <div className="trade-log-card-head-static">
                    <span className="badge badge-gray badge-spaced">{log.event_type}</span>
                    <span className="text-sm">{log.message}</span>
                    <p className="text-muted text-xs mt-xs">{localeDate(log.created_at, locale)}</p>
                  </div>
                  <TradeLogDetailPanel log={log} compact />
                </GlassCard>
              ))}
            </div>
          </div>
        )}
        {userDetailTab === 'referrals' && userReferralStats && (
          <div className="section-mt-md">
            <div className="stat-grid section-mb-sm">
              <StatCard label={t('admin.referralL1')} value={String(userReferralStats.l1_count ?? 0)} />
              <StatCard label={t('admin.referralL2')} value={String(userReferralStats.l2_count ?? 0)} />
              <StatCard label={t('admin.totalEarned')} value={`$${userReferralStats.total_earned?.toFixed(2) ?? '0'}`} />
              <StatCard label={t('admin.settledEarned')} value={`$${userReferralStats.settled_earned?.toFixed(2) ?? '0'}`} />
              <StatCard label={t('admin.pendingEarned')} value={`$${userReferralStats.pending_earned?.toFixed(2) ?? '0'}`} />
              <StatCard label={t('admin.rewardBalance')} value={`$${userReferralStats.reward_balance?.toFixed(2) ?? '0'}`} />
            </div>
            {userReferralStats.referrer && (
              <p className="text-muted text-sm section-mb-sm">
                {t('admin.referredBy')}: {userReferralStats.referrer.display_name} ({userReferralStats.referrer.uid})
              </p>
            )}
            <GlassCard className="p-0 table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>L</th><th>{t('common.user')}</th><th>{t('admin.cols.amount')}</th><th>{t('common.status')}</th><th>{t('admin.cols.settlement')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(userReferralStats.rewards || []).map((r: any) => (
                    <tr key={r.id}>
                      <td>L{r.level}</td>
                      <td>{r.source_display_name} ({r.source_uid})</td>
                      <td>${r.reward_amount?.toFixed(2)}</td>
                      <td>{r.status}</td>
                      <td>#{r.settlement_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </GlassCard>
          </div>
        )}
        {userDetailTab === 'principal' && (
          <GlassCard className="p-0 table-wrap section-mt-md">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('common.time')}</th>
                  <th>{t('admin.principalAmount')}</th>
                  <th>{t('admin.principalTradePnl')}</th>
                  <th>{t('admin.principalEquityDelta')}</th>
                  <th>{t('admin.principalType')}</th>
                  <th>{t('admin.principalNote')}</th>
                </tr>
              </thead>
              <tbody>
                {userPrincipalHistory.length === 0 ? (
                  <tr><td colSpan={6} className="empty-cell">{t('common.noData')}</td></tr>
                ) : userPrincipalHistory.map((s: any) => (
                  <tr key={s.id}>
                    <td>{localeDate(s.created_at, locale)}</td>
                    <td>${(s.live_equity ?? s.amount)?.toFixed(2)}</td>
                    <td className={(s.trade_pnl_cycle ?? 0) >= 0 ? 'text-green' : 'text-red'}>
                      ${(s.trade_pnl_cycle ?? 0).toFixed(2)}
                    </td>
                    <td className={(s.equity_delta ?? 0) >= 0 ? 'text-green' : 'text-red'}>
                      ${(s.equity_delta ?? 0).toFixed(2)}
                    </td>
                    <td>{s.snapshot_type}</td>
                    <td className="cell-ellipsis" title={s.note}>{s.note || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GlassCard>
        )}
      </div>
    )
  }

  return (
    <>
      {abnormalUsers.length > 0 && (
        <GlassCard className="p-4 section-mb-sm admin-alert-banner">
          <span>{t('admin.abnormalUsersHint', { n: abnormalUsers.length })}</span>
        </GlassCard>
      )}
      {selectedUserIds.length > 0 && (
        <GlassCard className="p-4 section-mb-sm">
          <div className="flex-gap-md flex-wrap admin-batch-bar">
            <span className="text-sm">{t('admin.batchSelected', { n: selectedUserIds.length })}</span>
            <input className="input" placeholder={t('admin.batchNotifyTitle')} value={batchNotifyTitle} onChange={e => setBatchNotifyTitle(e.target.value)} />
            <input className="input" placeholder={t('admin.batchNotifyMessage')} value={batchNotifyMessage} onChange={e => setBatchNotifyMessage(e.target.value)} />
            <button className="btn btn-primary btn-sm" type="button" onClick={runBatchNotify}>{t('admin.batchNotify')}</button>
            <button className="btn btn-danger btn-sm" type="button" onClick={() => runBatchPause(true)}>{t('admin.batchPause')}</button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => runBatchPause(false)}>{t('admin.batchResume')}</button>
          </div>
        </GlassCard>
      )}
      <GlassCard className="p-0 table-wrap">
        <div className="table-toolbar form-stack p-4">
          <input className="input" placeholder={t('admin.userSearchPh')} value={userSearch} onChange={e => setUserSearch(e.target.value)} />
          <select className="input" value={userApiFilter} onChange={e => setUserApiFilter(e.target.value)}>
            <option value="">{t('admin.allApiStatus')}</option>
            <option value="active">active</option>
            <option value="none">none</option>
            <option value="error">error</option>
          </select>
          <select className="input" value={userPauseFilter} onChange={e => setUserPauseFilter(e.target.value)}>
            <option value="">{t('admin.allPauseStatus')}</option>
            <option value="active">{t('admin.notPaused')}</option>
            <option value="paused">{t('admin.userPaused')}</option>
          </select>
          <select className="input" value={userFlagFilter} onChange={e => setUserFlagFilter(e.target.value)}>
            <option value="">{t('admin.allRiskFlags')}</option>
            <option value="flagged">{t('admin.flaggedOnly')}</option>
            <option value="normal">{t('admin.normalOnly')}</option>
          </select>
          <button className="btn btn-ghost btn-sm" type="button" onClick={load}>{t('admin.refresh')}</button>
          <button className="btn btn-ghost btn-sm" type="button" onClick={exportUsersCsv}>{t('admin.exportCsv')}</button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th><input type="checkbox" checked={users.length > 0 && selectedUserIds.length === users.length} onChange={toggleSelectAllUsers} aria-label="select all" /></th>
              <th>{t('admin.cols.uid')}</th><th>{t('admin.emailPhone')}</th>
              <th>{t('admin.cols.registeredAt')}</th>
              <th>{t('admin.cols.api')}</th>
              <th>{t('admin.cols.paused')}</th>
              <th>{t('admin.cols.cumulativePnl')}</th>
              <th>{t('admin.cols.execSuccessRate')}</th>
              <th>{t('nav.risk')}</th>
              <th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u: any) => (
              <tr key={u.id} className={u.risk_flag ? 'row-flagged' : undefined}>
                <td><input type="checkbox" checked={selectedUserIds.includes(u.id)} onChange={() => toggleUserSelect(u.id)} /></td>
                <td><span className="badge badge-gray">{u.uid}</span></td>
                <td>{u.email || u.phone || t('common.none')}</td>
                <td className="text-xs">{u.created_at ? localeDate(u.created_at, locale) : '—'}</td>
                <td><span className={`badge ${u.api_status === 'active' ? 'badge-green' : 'badge-gray'}`}>{u.api_status}</span></td>
                <td><span className={`badge ${u.trading_paused ? 'badge-gray' : 'badge-green'}`}>{u.trading_paused ? t('admin.userPaused') : t('admin.notPaused')}</span></td>
                <td className={(u.cumulative_pnl || 0) >= 0 ? 'text-green' : 'text-red'}>${(u.cumulative_pnl ?? 0).toFixed(2)}</td>
                <td>{u.execution_success_rate != null ? `${u.execution_success_rate}%` : '—'}</td>
                <td className="text-xs">{u.risk_level || '—'}{u.risk_flag ? ` · ${t('admin.flagged')}` : ''}</td>
                <td className="table-actions">
                  <button className="btn btn-primary btn-xs" onClick={() => loadUserDetail(u.id)}>{t('admin.viewUser')}</button>
                  <button className="btn btn-ghost btn-xs" onClick={() => adminApi.toggleUser(u.id).then(load)}>
                    {u.is_active ? t('common.disable') : t('common.enable')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </>
  )
}
