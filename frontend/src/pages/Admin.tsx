import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AdminLayout, { AdminTabKey } from '../components/AdminLayout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { adminApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n, localeDate } from '../i18n'
import { useTheme } from '../store/theme'
import { CHART } from '../theme/chartColors'
import { useAdminMonitorWebSocket } from '../hooks/useAdminMonitorWebSocket'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import ConfirmModal from '../components/ui/ConfirmModal'
import { downloadCsv } from '../utils/exportCsv'
import { toast } from '../store/toast'
import { AdminProvider } from './admin/AdminContext'
import AdminTabRouter from './admin/AdminTabRouter'
import { loadAdminTab, type AdminTabSetters, type UserListFilters } from './admin/adminTabLoaders'

type AdminConfirm =
  | { type: 'globalPause' }
  | { type: 'globalResume' }
  | { type: 'userPause' }
  | { type: 'forceClose' }

export default function Admin() {
  const token = useAuth(s => s.token)
  const { t, locale } = useI18n()
  const [overview, setOverview] = useState<any>(null)
  const [users, setUsers] = useState<any[]>([])
  const [settlements, setSettlements] = useState<any[]>([])
  const [depositAddrs, setDepositAddrs] = useState<any[]>([])
  const [withdrawals, setWithdrawals] = useState<any[]>([])
  const [alerts, setAlerts] = useState<any[]>([])
  const [searchParams, setSearchParams] = useSearchParams()
  const VALID_TABS: AdminTabKey[] = [
    'home', 'users', 'signals', 'execution', 'risk', 'analytics', 'audit',
    'finance', 'settlements', 'withdrawals', 'referrals', 'addresses', 'system',
  ]
  const rawTab = searchParams.get('tab') || 'home'
  const tab = (VALID_TABS.includes(rawTab as AdminTabKey) ? rawTab : 'home') as AdminTabKey
  const setTab = (k: AdminTabKey) => {
    closeUserDetail()
    setSearchParams({ tab: k })
  }
  const [monitor, setMonitor] = useState<any>(null)
  const [globalControl, setGlobalControl] = useState<{ global_trading_paused: boolean; global_risk_multiplier?: number } | null>(null)
  const [userSearch, setUserSearch] = useState('')
  const debouncedUserSearch = useDebouncedValue(userSearch, 400)
  const [userApiFilter, setUserApiFilter] = useState('')
  const [userPauseFilter, setUserPauseFilter] = useState('')
  const [userFlagFilter, setUserFlagFilter] = useState('')
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([])
  const [batchNotifyTitle, setBatchNotifyTitle] = useState('')
  const [batchNotifyMessage, setBatchNotifyMessage] = useState('')
  const [webhookPayload, setWebhookPayload] = useState('{\n  "strategy_id": "gemini_eth_v3",\n  "action": "LONG",\n  "regime": 1,\n  "price": 3500\n}')
  const [selectedDispatchId, setSelectedDispatchId] = useState<number | null>(null)
  const [dispatchUserResults, setDispatchUserResults] = useState<any[]>([])
  const [dispatchResultsLoading, setDispatchResultsLoading] = useState(false)
  const [auditSearch, setAuditSearch] = useState('')
  const [riskDraft, setRiskDraft] = useState('1.0')
  const [auditLogs, setAuditLogs] = useState<any[]>([])
  const [orders, setOrders] = useState<any[]>([])
  const [strategies, setStrategies] = useState<any[]>([])
  const [tradeLogs, setTradeLogs] = useState<any[]>([])
  const [online, setOnline] = useState<any>(null)
  const [loginRecords, setLoginRecords] = useState<any[]>([])
  const [riskAlerts, setRiskAlerts] = useState<any[]>([])
  const [newAddr, setNewAddr] = useState({ chain: 'TRC20', address: '', label: '' })
  const [editingAddr, setEditingAddr] = useState<any>(null)
  const [withdrawThresholds, setWithdrawThresholds] = useState<{
    auto_max_usd: number
    review_min_usd: number
    min_usd: number
    payout_auto_enabled?: boolean
    payout_configured_chains?: string[]
  } | null>(null)
  const [thresholdDraft, setThresholdDraft] = useState({ auto_max_usd: '100', review_min_usd: '500' })
  const [payoutSettings, setPayoutSettings] = useState<{ auto_enabled: boolean; chains: Record<string, boolean> } | null>(null)
  const [payoutKeyDraft, setPayoutKeyDraft] = useState<Record<string, string>>({})
  const [payoutAutoDraft, setPayoutAutoDraft] = useState(false)
  const [completeTx, setCompleteTx] = useState<Record<number, string>>({})
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
  const [userDetail, setUserDetail] = useState<any>(null)
  const [userTrades, setUserTrades] = useState<any[]>([])
  const [userLogs, setUserLogs] = useState<any[]>([])
  const [userDetailTab, setUserDetailTab] = useState<'overview' | 'trades' | 'logs' | 'referrals' | 'principal'>('overview')
  const [userReferralStats, setUserReferralStats] = useState<any>(null)
  const [userPrincipalHistory, setUserPrincipalHistory] = useState<any[]>([])
  const [referralOverview, setReferralOverview] = useState<any>(null)
  const [signalTemplates, setSignalTemplates] = useState<any[]>([])
  const [signalLogs, setSignalLogs] = useState<any[]>([])
  const [userTradingCtrl, setUserTradingCtrl] = useState<any>(null)
  const [newTemplate, setNewTemplate] = useState({ name: '', description: '', payload: '{\n  "strategy_id": "gemini_eth_v3",\n  "action": "LONG",\n  "regime": 1,\n  "price": 3500\n}' })
  const [editTemplate, setEditTemplate] = useState<any>(null)
  const [platformAnalytics, setPlatformAnalytics] = useState<any>(null)
  const [startupAudit, setStartupAudit] = useState<any>(null)
  const [adminConfirm, setAdminConfirm] = useState<AdminConfirm | null>(null)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const loadUserDetail = (id: number) => {
    if (tab !== 'users') setSearchParams({ tab: 'users' })
    setSelectedUserId(id)
    setUserDetailTab('overview')
    adminApi.userDetail(id).then(setUserDetail)
    adminApi.userTrades(id).then(setUserTrades)
    adminApi.userLogs(id).then(setUserLogs)
    adminApi.userTradingControl(id).then(setUserTradingCtrl).catch(() => setUserTradingCtrl(null))
    adminApi.userReferralStats(id).then(setUserReferralStats).catch(() => setUserReferralStats(null))
    adminApi.userPrincipalHistory(id).then(setUserPrincipalHistory).catch(() => setUserPrincipalHistory([]))
  }

  const closeUserDetail = () => {
    setSelectedUserId(null)
    setUserDetail(null)
    setUserTrades([])
    setUserLogs([])
    setUserReferralStats(null)
    setUserPrincipalHistory([])
  }

  const tabSetters: AdminTabSetters = useMemo(() => ({
    setOverview,
    setUsers,
    setSettlements,
    setDepositAddrs,
    setWithdrawals,
    setAlerts,
    setMonitor,
    setAuditLogs,
    setOrders,
    setStrategies,
    setTradeLogs,
    setOnline,
    setLoginRecords,
    setGlobalControl,
    setRiskDraft,
    setRiskAlerts,
    setSignalTemplates,
    setSignalLogs,
    setReferralOverview,
    setWithdrawThresholds,
    setThresholdDraft,
    setPayoutSettings,
    setPayoutKeyDraft,
    setPlatformAnalytics,
    setStartupAudit,
  }), [])

  const userListFilters = useMemo((): UserListFilters => ({
    q: debouncedUserSearch.trim() || undefined,
    api_status: userApiFilter || undefined,
    trading_paused: userPauseFilter === 'paused' ? true : userPauseFilter === 'active' ? false : undefined,
    risk_flag: userFlagFilter === 'flagged' ? true : userFlagFilter === 'normal' ? false : undefined,
  }), [debouncedUserSearch, userApiFilter, userPauseFilter, userFlagFilter])

  const refreshTab = useCallback(async (targetTab: AdminTabKey = tab) => {
    await loadAdminTab(targetTab, tabSetters, {
      userFilters: targetTab === 'users' ? userListFilters : undefined,
      auditSearch,
    })
  }, [tab, tabSetters, userListFilters, auditSearch])

  const refreshTabRef = useRef(refreshTab)
  refreshTabRef.current = refreshTab

  const load = useCallback(() => {
    refreshTabRef.current()
  }, [])

  useEffect(() => {
    if (!token) return
    refreshTab()
    const ms = tab === 'execution' ? 15000 : 30000
    const timer = setInterval(() => refreshTabRef.current(), ms)
    return () => clearInterval(timer)
  }, [token, tab, refreshTab])

  useEffect(() => {
    if (!token || tab !== 'users') return
    loadAdminTab('users', tabSetters, { userFilters: userListFilters }).catch(() => {})
  }, [token, tab, userListFilters, tabSetters])

  useEffect(() => {
    if (!token || tab !== 'audit') return
    const debounce = setTimeout(() => {
      loadAdminTab('audit', tabSetters, { auditSearch }).catch(() => {})
    }, 400)
    return () => clearTimeout(debounce)
  }, [token, tab, auditSearch, tabSetters])

  useEffect(() => {
    if (payoutSettings) setPayoutAutoDraft(!!payoutSettings.auto_enabled)
  }, [payoutSettings])

  const onAdminWs = useCallback((raw: unknown) => {
    const data = raw as { type?: string; orders?: any[]; signal_logs?: any[]; monitor?: any }
    if (data?.type !== 'admin_tick') return
    if (data.orders) setOrders(data.orders)
    if (data.signal_logs) setSignalLogs(data.signal_logs)
    if (data.monitor) setMonitor((prev: any) => ({ ...(prev || {}), ...data.monitor }))
  }, [])

  useAdminMonitorWebSocket(onAdminWs, tab === 'execution' && !!token)

  const runSettlement = async () => {
    const res = await adminApi.runSettlement()
    toast.success(t('admin.settlementCreated', { n: res.created }))
    load()
  }

  const confirm = async (id: number) => {
    await adminApi.confirmSettlement(id)
    toast.success(t('admin.settlementConfirmed', { id }))
    load()
  }

  const addAddr = async (e: React.FormEvent) => {
    e.preventDefault()
    await adminApi.addDepositAddress(newAddr)
    setNewAddr({ chain: 'TRC20', address: '', label: '' })
    toast.success(t('admin.addrAdded'))
    load()
  }

  const saveEditingAddr = async () => {
    if (!editingAddr?.id) return
    try {
      await adminApi.updateDepositAddress(editingAddr.id, {
        chain: editingAddr.chain,
        address: editingAddr.address,
        label: editingAddr.label,
        is_active: editingAddr.is_active,
      })
      toast.success(t('admin.addrUpdated'))
      setEditingAddr(null)
      load()
    } catch {
      toast.error(t('admin.addrUpdateFail'))
    }
  }

  const uploadAddrQr = async (id: number, file: File) => {
    try {
      const updated = await adminApi.uploadDepositAddressQr(id, file)
      toast.success(t('admin.qrUploaded'))
      setEditingAddr((prev: any) => (prev?.id === id ? updated : prev))
      load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('admin.qrUploadFail'))
    }
  }

  const removeAddrQr = async (id: number) => {
    try {
      const updated = await adminApi.deleteDepositAddressQr(id)
      toast.success(t('admin.qrRemoved'))
      setEditingAddr((prev: any) => (prev?.id === id ? updated : prev))
      load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('admin.qrRemoveFail'))
    }
  }

  const saveWithdrawThresholds = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const res = await adminApi.updateWithdrawSettings(
        parseFloat(thresholdDraft.auto_max_usd),
        parseFloat(thresholdDraft.review_min_usd),
      )
      setWithdrawThresholds(res)
      toast.success(t('admin.withdrawSettingsSaved'))
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('admin.withdrawSettingsFail'))
    }
  }

  const savePayoutSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const private_keys: Record<string, string> = {}
      for (const [chain, val] of Object.entries(payoutKeyDraft)) {
        if (val?.trim()) private_keys[chain] = val.trim()
      }
      const res = await adminApi.updatePayoutSettings({
        auto_enabled: payoutAutoDraft,
        private_keys: Object.keys(private_keys).length ? private_keys : undefined,
      })
      setPayoutSettings(res)
      setPayoutKeyDraft({})
      toast.success(t('admin.payoutKeysSaved'))
      load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('admin.payoutKeysFail'))
    }
  }

  const completeWd = async (id: number) => {
    const tx = completeTx[id]
    if (!tx) return
    await adminApi.completeWithdrawal(id, tx)
    toast.success(t('admin.withdrawCompleted', { id }))
    load()
  }

  const applyGlobalPause = async (pause: boolean) => {
    setConfirmLoading(true)
    try {
      setGlobalControl(await adminApi.setGlobalTradingPause(pause))
      toast.success(pause ? t('admin.globalPaused') : t('admin.globalActive'))
      setAdminConfirm(null)
      load()
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    } finally {
      setConfirmLoading(false)
    }
  }

  const applyUserPause = async () => {
    if (!selectedUserId) return
    setConfirmLoading(true)
    try {
      setUserTradingCtrl(await adminApi.userTradingControl(selectedUserId, { trading_paused: true }))
      toast.success(t('risk.paused'))
      setAdminConfirm(null)
    } catch {
      toast.error(t('risk.updateFail'))
    } finally {
      setConfirmLoading(false)
    }
  }

  const applyForceClose = async () => {
    if (!selectedUserId) return
    setConfirmLoading(true)
    try {
      await adminApi.forceCloseUser(selectedUserId)
      toast.success(t('admin.forceCloseDone'))
      setAdminConfirm(null)
      loadUserDetail(selectedUserId)
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    } finally {
      setConfirmLoading(false)
    }
  }

  const runAdminConfirm = () => {
    if (!adminConfirm) return
    if (adminConfirm.type === 'globalPause') applyGlobalPause(true)
    else if (adminConfirm.type === 'globalResume') applyGlobalPause(false)
    else if (adminConfirm.type === 'userPause') applyUserPause()
    else if (adminConfirm.type === 'forceClose') applyForceClose()
  }

  const adminConfirmMeta = adminConfirm ? ({
    globalPause: {
      title: t('admin.pauseGlobal'),
      message: t('admin.pauseGlobalConfirm'),
      confirmLabel: t('admin.pauseGlobal'),
      variant: 'danger' as const,
      confirmPhrase: t('admin.pauseGlobalPhrase'),
    },
    globalResume: {
      title: t('admin.resumeGlobal'),
      message: t('admin.resumeGlobalConfirm'),
      confirmLabel: t('admin.resumeGlobal'),
      variant: 'primary' as const,
    },
    userPause: {
      title: t('admin.forcePause'),
      message: t('admin.forcePauseConfirm'),
      confirmLabel: t('admin.forcePause'),
      variant: 'danger' as const,
    },
    forceClose: {
      title: t('admin.forceClose'),
      message: t('admin.forceCloseConfirm'),
      confirmLabel: t('admin.forceClose'),
      variant: 'danger' as const,
    },
  })[adminConfirm.type] : null

  const forceUserPause = async (pause: boolean) => {
    if (!selectedUserId) return
    if (pause) {
      setAdminConfirm({ type: 'userPause' })
      return
    }
    try {
      setUserTradingCtrl(await adminApi.userTradingControl(selectedUserId, { trading_paused: false }))
      toast.success(t('risk.resumed'))
    } catch {
      toast.error(t('risk.updateFail'))
    }
  }

  const forceCloseUser = () => {
    if (!selectedUserId) return
    setAdminConfirm({ type: 'forceClose' })
  }

  const setUserRisk = async (risk_level: string) => {
    if (!selectedUserId) return
    try {
      setUserTradingCtrl(await adminApi.userTradingControl(selectedUserId, { risk_level }))
      toast.success(t('risk.levelUpdated'))
    } catch {
      toast.error(t('risk.updateFail'))
    }
  }

  const saveTemplateEdit = async () => {
    if (!editTemplate) return
    try {
      await adminApi.updateSignalTemplate(editTemplate.id, {
        name: editTemplate.name,
        description: editTemplate.description,
        payload: JSON.parse(editTemplate.payloadText),
      })
      setEditTemplate(null)
      toast.success(t('admin.templateSaved'))
      load()
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    }
  }

  const exportAuditCsv = () => downloadCsv('audit-logs', auditLogs.map(l => ({
    action: l.action,
    user_id: l.user_id,
    actor_id: l.actor_id,
    resource_type: l.resource_type,
    resource_id: l.resource_id,
    detail: l.detail ? JSON.stringify(l.detail) : '',
    ip: l.ip_address,
    time: localeDate(l.created_at, locale),
  })))

  const saveSignalTemplate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const payload = JSON.parse(newTemplate.payload)
      await adminApi.createSignalTemplate({ name: newTemplate.name, description: newTemplate.description, payload })
      toast.success(t('admin.templateSaved'))
      setNewTemplate({ name: '', description: '', payload: '{\n  "action": "LONG",\n  "regime": 1,\n  "price": 3500\n}' })
      load()
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    }
  }

  const testTemplate = async (id: number) => {
    try {
      const res = await adminApi.testSignalTemplate(id)
      toast.success(`${t('admin.testSent')} · ${res.dispatched ?? 0}`)
      load()
      if (res.dispatch_id) {
        setTab('execution')
        loadDispatchResults(res.dispatch_id)
      }
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    }
  }

  const reviewStrategy = async (id: number, action: 'approve' | 'reject' | 'pause') => {
    try {
      await adminApi.reviewStrategy(id, action)
      toast.success(action === 'approve' ? t('admin.strategyApproved', { id }) : t('admin.strategyRejected', { id }))
      load()
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    }
  }

  const exportUsersCsv = () => {
    const rows = selectedUserIds.length
      ? users.filter(u => selectedUserIds.includes(u.id))
      : users
    downloadCsv('users', rows.map(u => ({
      uid: u.uid, email: u.email, phone: u.phone, nickname: u.nickname, role: u.role,
      api_status: u.api_status, is_active: u.is_active, trading_paused: u.trading_paused,
      risk_level: u.risk_level, created_at: u.created_at, cumulative_pnl: u.cumulative_pnl,
      execution_success_rate: u.execution_success_rate, risk_flag: u.risk_flag,
    })))
  }

  const toggleUserSelect = (id: number) => {
    setSelectedUserIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const toggleSelectAllUsers = () => {
    if (selectedUserIds.length === users.length) setSelectedUserIds([])
    else setSelectedUserIds(users.map(u => u.id))
  }

  const runBatchNotify = async () => {
    if (!selectedUserIds.length || !batchNotifyTitle.trim() || !batchNotifyMessage.trim()) return
    try {
      const res = await adminApi.batchNotifyUsers(selectedUserIds, batchNotifyTitle.trim(), batchNotifyMessage.trim())
      toast.success(t('admin.batchNotifySent', { n: res.sent }))
      setBatchNotifyTitle('')
      setBatchNotifyMessage('')
      setSelectedUserIds([])
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    }
  }

  const runBatchPause = async (paused: boolean) => {
    if (!selectedUserIds.length) return
    try {
      await adminApi.batchTradingControl(selectedUserIds, { trading_paused: paused })
      toast.success(paused ? t('admin.batchPaused') : t('admin.batchResumed'))
      setSelectedUserIds([])
      load()
    } catch {
      toast.error(t('admin.strategyReviewFail'))
    }
  }

  const runWebhookTest = async () => {
    try {
      const payload = JSON.parse(webhookPayload)
      const res = await adminApi.webhookTest(payload)
      toast.success(t('admin.webhookTestOk', { n: res.dispatched, e: res.errors }))
      setTab('execution')
      if (res.dispatch_id) loadDispatchResults(res.dispatch_id)
      load()
    } catch {
      toast.error(t('admin.webhookTestFail'))
    }
  }

  const loadDispatchResults = (dispatchId: number) => {
    setSelectedDispatchId(dispatchId)
    setDispatchResultsLoading(true)
    adminApi.signalDispatchResults(dispatchId)
      .then(setDispatchUserResults)
      .catch(() => setDispatchUserResults([]))
      .finally(() => setDispatchResultsLoading(false))
  }

  const dispatchResultStatusLabel = (status: string) => {
    const map: Record<string, string> = {
      ok: t('admin.dispatchStatus.ok'),
      error: t('admin.dispatchStatus.error'),
      skipped: t('admin.dispatchStatus.skipped'),
      risk_blocked: t('admin.dispatchStatus.riskBlocked'),
    }
    return map[status] || status
  }

  const renderDispatchUserResults = () => {
    if (!selectedDispatchId) return null
    const log = signalLogs.find(l => l.id === selectedDispatchId)
    return (
      <GlassCard className="p-0 table-wrap section-mb-md">
        <div className="table-toolbar table-toolbar-between table-toolbar-flush p-4">
          <div>
            <h3 className="card-heading">{t('admin.dispatchUserResults')}</h3>
            <p className="text-muted text-sm">
              #{selectedDispatchId} · {log?.action || '—'} · {log ? localeDate(log.created_at, locale) : ''}
            </p>
          </div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setSelectedDispatchId(null); setDispatchUserResults([]) }}>
            {t('common.cancel')}
          </button>
        </div>
        {dispatchResultsLoading ? (
          <p className="text-muted p-6">{t('common.loading')}</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('admin.cols.uid')}</th>
                <th>{t('common.user')}</th>
                <th>{t('common.status')}</th>
                <th>{t('admin.cols.slippage')}</th>
                <th>{t('admin.cols.latency')}</th>
                <th>{t('admin.cols.detail')}</th>
              </tr>
            </thead>
            <tbody>
              {dispatchUserResults.length === 0 && (
                <tr><td colSpan={6} className="empty-cell">{t('common.noData')}</td></tr>
              )}
              {dispatchUserResults.map(r => (
                <tr key={r.id}>
                  <td><span className="badge badge-gray">{r.user_uid || `#${r.user_id}`}</span></td>
                  <td className="text-sm">{r.user_email || r.user_nickname || `#${r.user_id}`}</td>
                  <td>
                    <span className={`badge ${r.status === 'ok' ? 'badge-green' : r.status === 'error' ? 'badge-red' : 'badge-gray'}`}>
                      {dispatchResultStatusLabel(r.status)}
                    </span>
                    {r.reason && <span className="text-muted text-xs"> · {r.reason}</span>}
                  </td>
                  <td>{r.slippage != null ? r.slippage.toFixed(4) : '—'}</td>
                  <td>{r.latency_ms != null ? `${r.latency_ms}ms` : '—'}</td>
                  <td className="text-sm cell-max-md">{r.error_message || (r.trade_id ? `trade #${r.trade_id}` : '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </GlassCard>
    )
  }

  const latestSignal = signalLogs[0]
  const abnormalUsers = users.filter(u => u.risk_flag)

  const exportSettlementsCsv = () => downloadCsv('settlements', settlements.map(s => ({
    id: s.id, user_id: s.user_id, cycle_days: s.cycle_days, net_profit: s.net_profit,
    platform_fee: s.platform_fee, user_payable: s.user_payable, payment_status: s.payment_status,
  })))

  const exportStrategiesCsv = () => downloadCsv('strategies', strategies.map(s => ({
    id: s.id, user_uid: s.user_uid, name: s.name, strategy_type: s.strategy_type, status: s.status,
    sharpe: s.sharpe, win_rate: s.win_rate, total_pnl: s.total_pnl,
  })))

  const exportTradeLogsCsv = () => downloadCsv('trade-logs', tradeLogs.map(l => ({
    id: l.id, user_uid: l.user_uid, event_type: l.event_type, message: l.message,
    trade_id: l.trade_id, created_at: l.created_at,
  })))

  const exportUserLogsCsv = () => downloadCsv(`user-${selectedUserId}-logs`, userLogs.map(l => ({
    id: l.id, event_type: l.event_type, message: l.message, trade_id: l.trade_id, created_at: l.created_at,
  })))

  const formatOrderUser = (o: any) => o.user_uid || `#${o.user_id}`

  const payStatus = (s: string) => t(`admin.payStatus.${s}`) || s
  const wStatus = (s: string) => t(`admin.wStatus.${s}`) || s
  const confirmedRevenue = settlements
    .filter(s => s.payment_status === 'confirmed')
    .reduce((sum, s) => sum + (s.platform_fee || 0), 0)
  const pendingRevenue = settlements
    .filter(s => s.payment_status === 'paid' || s.payment_status === 'pending')
    .reduce((sum, s) => sum + (s.platform_fee || 0), 0)

  const execBarOption = useMemo(() => ({
    backgroundColor: 'transparent',
    grid: { top: 20, right: 16, bottom: 30, left: 44 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: platformAnalytics?.daily_series?.map((d: any) => d.date.slice(5)) || [],
      axisLabel: { fontSize: 10, color: CHART.axisLabel(isDark) },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark) },
    },
    series: [{
      name: t('admin.platformExecutions'),
      type: 'bar',
      data: platformAnalytics?.daily_series?.map((d: any) => d.executions) || [],
      itemStyle: { color: CHART.green, borderRadius: [4, 4, 0, 0] },
    }],
  }), [platformAnalytics, isDark, t])

  const breakdownPieOption = useMemo(() => {
    const b = platformAnalytics?.execution_breakdown || {}
    const data = [
      { name: t('admin.execSuccess'), value: b.success || 0 },
      { name: t('admin.execFailed'), value: b.failed || 0 },
      { name: t('admin.execRiskBlocked'), value: b.risk_blocked || 0 },
    ]
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: CHART.label(isDark), fontSize: 11 } },
      series: [{
        type: 'pie',
        radius: ['42%', '68%'],
        center: ['50%', '44%'],
        data,
        label: { color: CHART.label(isDark), fontSize: 11 },
        color: [CHART.green, CHART.red, '#f59e0b'],
      }],
    }
  }, [platformAnalytics, isDark, t])

  const errorsBarOption = useMemo(() => ({
    backgroundColor: 'transparent',
    grid: { top: 12, right: 16, bottom: 8, left: 120 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark) },
    },
    yAxis: {
      type: 'category',
      data: (platformAnalytics?.top_errors || []).map((e: any) => e.message).reverse(),
      axisLabel: { fontSize: 10, color: CHART.axisLabel(isDark), width: 110, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      data: (platformAnalytics?.top_errors || []).map((e: any) => e.count).reverse(),
      itemStyle: { color: CHART.red, borderRadius: [0, 4, 4, 0] },
    }],
  }), [platformAnalytics, isDark])

  const signalCoverageOption = useMemo(() => ({
    backgroundColor: 'transparent',
    grid: { top: 20, right: 16, bottom: 30, left: 44 },
    tooltip: { trigger: 'axis' },
    legend: { data: [t('admin.signalCount'), t('admin.usersDispatched')], textStyle: { color: CHART.label(isDark), fontSize: 11 } },
    xAxis: {
      type: 'category',
      data: platformAnalytics?.signal_coverage_series?.map((d: any) => d.date.slice(5)) || [],
      axisLabel: { fontSize: 10, color: CHART.axisLabel(isDark) },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART.splitLine(isDark) } },
      axisLabel: { color: CHART.axisLabel(isDark), fontSize: 10 },
    },
    series: [
      {
        name: t('admin.signalCount'),
        type: 'bar',
        data: platformAnalytics?.signal_coverage_series?.map((d: any) => d.signals) || [],
        itemStyle: { color: '#007aff' },
      },
      {
        name: t('admin.usersDispatched'),
        type: 'line',
        smooth: true,
        data: platformAnalytics?.signal_coverage_series?.map((d: any) => d.users_dispatched) || [],
        itemStyle: { color: '#32d74b' },
      },
    ],
  }), [platformAnalytics, isDark, t])

  const tabLabel = (k: AdminTabKey) => {
    const map: Record<AdminTabKey, string> = {
      home: t('admin.tabOverview'), users: t('admin.tabUsers'), signals: t('admin.tabSignals'),
      execution: t('admin.tabExecution'), risk: t('admin.tabRisk'), analytics: t('admin.tabAnalytics'),
      audit: t('admin.tabAudit'), finance: t('admin.tabFinance'), settlements: t('admin.tabSettlements'),
      referrals: t('admin.tabReferrals'),
      withdrawals: t('admin.tabWithdrawals'), addresses: t('admin.tabAddresses'), system: t('admin.tabSystem'),
    }
    return map[k] || t('admin.consoleBadge')
  }

  const adminValue = {
    t, locale, tab, setTab,
    overview, users, settlements, depositAddrs, withdrawals, alerts,
    monitor, globalControl, setGlobalControl,
    userSearch, setUserSearch, userApiFilter, setUserApiFilter,
    userPauseFilter, setUserPauseFilter, userFlagFilter, setUserFlagFilter,
    selectedUserIds, setSelectedUserIds, batchNotifyTitle, setBatchNotifyTitle,
    batchNotifyMessage, setBatchNotifyMessage,
    webhookPayload, setWebhookPayload,
    selectedDispatchId, setSelectedDispatchId, dispatchUserResults, dispatchResultsLoading,
    auditSearch, setAuditSearch,
    riskDraft, setRiskDraft,
    auditLogs, orders, strategies, tradeLogs, online, loginRecords, riskAlerts,
    newAddr, setNewAddr, editingAddr, setEditingAddr,
    withdrawThresholds, thresholdDraft, setThresholdDraft,
    payoutSettings, payoutKeyDraft, setPayoutKeyDraft, payoutAutoDraft, setPayoutAutoDraft,
    completeTx, setCompleteTx,
    selectedUserId, userDetail, userTrades, userLogs, setUserLogs,
    userDetailTab, setUserDetailTab,
    userReferralStats, userPrincipalHistory, referralOverview,
    signalTemplates, signalLogs, userTradingCtrl,
    newTemplate, setNewTemplate, editTemplate, setEditTemplate,
    platformAnalytics,
    startupAudit,
    load, loadUserDetail, closeUserDetail,
    runSettlement, confirm, addAddr, saveEditingAddr, uploadAddrQr, removeAddrQr, saveWithdrawThresholds, savePayoutSettings, completeWd,
    setAdminConfirm, forceUserPause, forceCloseUser, setUserRisk,
    saveTemplateEdit, exportAuditCsv, saveSignalTemplate, testTemplate, reviewStrategy,
    exportUsersCsv, toggleUserSelect, toggleSelectAllUsers, runBatchNotify, runBatchPause,
    runWebhookTest, loadDispatchResults, renderDispatchUserResults,
    exportSettlementsCsv, exportStrategiesCsv, exportTradeLogsCsv, exportUserLogsCsv,
    formatOrderUser, payStatus, wStatus, confirmedRevenue, pendingRevenue,
    execBarOption, breakdownPieOption, errorsBarOption, signalCoverageOption,
    tabLabel, abnormalUsers, latestSignal,
  }

  return (
    <AdminLayout>
      <AdminProvider value={adminValue}>
      <PageHeader
        title={t('admin.title')}
        subtitle={tabLabel(tab)}
        action={
          <div className="flex-gap-sm">
            <button className="btn btn-ghost btn-sm" type="button" onClick={load}>{t('admin.refresh')}</button>
            <button className="btn btn-primary btn-sm" type="button" onClick={runSettlement}>{t('admin.runSettlement')}</button>
          </div>
        }
      />

      <AdminTabRouter tab={tab} />

      {adminConfirmMeta && (
        <ConfirmModal
          open={!!adminConfirm}
          title={adminConfirmMeta.title}
          message={adminConfirmMeta.message}
          confirmLabel={adminConfirmMeta.confirmLabel}
          variant={adminConfirmMeta.variant}
          confirmPhrase={'confirmPhrase' in adminConfirmMeta ? adminConfirmMeta.confirmPhrase : undefined}
          loading={confirmLoading}
          onConfirm={runAdminConfirm}
          onCancel={() => !confirmLoading && setAdminConfirm(null)}
        />
      )}
      </AdminProvider>
    </AdminLayout>
  )
}
