import { adminApi } from '../../api'
import type { AdminTabKey } from '../../components/AdminLayout'

export type UserListFilters = {
  q?: string
  api_status?: string
  trading_paused?: boolean
  risk_level?: string
  risk_flag?: boolean
}

export type AdminTabSetters = {
  setOverview: (v: any) => void
  setUsers: (v: any[]) => void
  setSettlements: (v: any[]) => void
  setDepositAddrs: (v: any[]) => void
  setWithdrawals: (v: any[]) => void
  setAlerts: (v: any[]) => void
  setMonitor: (v: any) => void
  setAuditLogs: (v: any[]) => void
  setOrders: (v: any[]) => void
  setStrategies: (v: any[]) => void
  setTradeLogs: (v: any[]) => void
  setOnline: (v: any) => void
  setLoginRecords: (v: any[]) => void
  setGlobalControl: (v: any) => void
  setRiskDraft: (v: string) => void
  setRiskAlerts: (v: any[]) => void
  setSignalTemplates: (v: any[]) => void
  setSignalLogs: (v: any[]) => void
  setReferralOverview: (v: any) => void
  setWithdrawThresholds: (v: any) => void
  setThresholdDraft: (v: { auto_max_usd: string; review_min_usd: string }) => void
  setPlatformAnalytics: (v: any) => void
  setStartupAudit?: (v: any) => void
}

export async function loadUsersList(filters: UserListFilters): Promise<any[]> {
  const rows = await adminApi.users({
    q: filters.q,
    api_status: filters.api_status,
    trading_paused: filters.trading_paused,
    risk_level: filters.risk_level,
    risk_flag: filters.risk_flag,
  })
  return rows
}

/** Fetch only APIs needed for the active admin tab. */
export async function loadAdminTab(
  tab: AdminTabKey,
  setters: AdminTabSetters,
  opts: {
    userFilters?: UserListFilters
    auditSearch?: string
    analyticsDays?: number
  } = {},
): Promise<void> {
  const { userFilters, auditSearch = '', analyticsDays = 14 } = opts

  switch (tab) {
    case 'home': {
      const [overview, orders, online, monitor, riskAlerts, startupAudit] = await Promise.all([
        adminApi.overview(),
        adminApi.allOrders().catch(() => []),
        adminApi.onlineStats().catch(() => null),
        adminApi.systemMonitor().catch(() => null),
        adminApi.riskAlerts().catch(() => []),
        adminApi.startupAudit().catch(() => null),
      ])
      setters.setOverview(overview)
      setters.setOrders(orders)
      setters.setOnline(online)
      setters.setMonitor(monitor)
      setters.setRiskAlerts(riskAlerts)
      setters.setStartupAudit?.(startupAudit)
      break
    }
    case 'users': {
      if (userFilters) {
        const users = await loadUsersList(userFilters)
        setters.setUsers(users)
      }
      break
    }
    case 'finance': {
      const [overview, settlements] = await Promise.all([
        adminApi.overview(),
        adminApi.settlements(),
      ])
      setters.setOverview(overview)
      setters.setSettlements(settlements)
      break
    }
    case 'settlements': {
      setters.setSettlements(await adminApi.settlements())
      break
    }
    case 'referrals': {
      setters.setReferralOverview(
        await adminApi.referralsOverview().catch(() => null),
      )
      break
    }
    case 'signals': {
      const [signalTemplates, signalLogs, strategies] = await Promise.all([
        adminApi.signalTemplates().catch(() => []),
        adminApi.signalDispatchLogs(50).catch(() => []),
        adminApi.strategies().catch(() => []),
      ])
      setters.setSignalTemplates(signalTemplates)
      setters.setSignalLogs(signalLogs)
      setters.setStrategies(strategies)
      break
    }
    case 'execution': {
      const [monitor, orders, signalLogs] = await Promise.all([
        adminApi.systemMonitor().catch(() => null),
        adminApi.allOrders().catch(() => []),
        adminApi.signalDispatchLogs(50).catch(() => []),
      ])
      setters.setMonitor(monitor)
      setters.setOrders(orders)
      setters.setSignalLogs(signalLogs)
      break
    }
    case 'risk': {
      const [globalControl, alerts] = await Promise.all([
        adminApi.globalTradingControl(),
        adminApi.alerts(),
      ])
      setters.setGlobalControl(globalControl)
      setters.setRiskDraft(String(globalControl?.global_risk_multiplier ?? 1))
      setters.setAlerts(alerts)
      break
    }
    case 'analytics': {
      const [platformAnalytics, monitor, online, settlements] = await Promise.all([
        adminApi.platformAnalytics(analyticsDays).catch(() => null),
        adminApi.systemMonitor().catch(() => null),
        adminApi.onlineStats().catch(() => null),
        adminApi.settlements().catch(() => []),
      ])
      setters.setPlatformAnalytics(platformAnalytics)
      setters.setMonitor(monitor)
      setters.setOnline(online)
      setters.setSettlements(settlements)
      break
    }
    case 'audit': {
      setters.setAuditLogs(
        await adminApi.auditLogs({ q: auditSearch.trim() || undefined, limit: 200 }).catch(() => []),
      )
      break
    }
    case 'withdrawals':
    case 'addresses': {
      const [withdrawals, settings] = await Promise.all([
        adminApi.withdrawals(),
        adminApi.withdrawSettings().catch(() => null),
      ])
      setters.setWithdrawals(withdrawals)
      if (settings) {
        setters.setWithdrawThresholds(settings)
        setters.setThresholdDraft({
          auto_max_usd: String(settings.auto_max_usd ?? 100),
          review_min_usd: String(settings.review_min_usd ?? 500),
        })
      }
      if (tab === 'addresses') {
        setters.setDepositAddrs(await adminApi.depositAddresses())
      }
      break
    }
    case 'system': {
      const [
        monitor,
        loginRecords,
        riskAlerts,
        auditLogs,
        tradeLogs,
        signalLogs,
        orders,
        startupAudit,
      ] = await Promise.all([
        adminApi.systemMonitor().catch(() => null),
        adminApi.loginRecords().catch(() => []),
        adminApi.riskAlerts().catch(() => []),
        adminApi.auditLogs({ limit: 200 }).catch(() => []),
        adminApi.allTradeLogs(200).catch(() => []),
        adminApi.signalDispatchLogs(30).catch(() => []),
        adminApi.allOrders().catch(() => []),
        adminApi.startupAudit().catch(() => null),
      ])
      setters.setMonitor(monitor)
      setters.setLoginRecords(loginRecords)
      setters.setRiskAlerts(riskAlerts)
      setters.setAuditLogs(auditLogs)
      setters.setTradeLogs(tradeLogs)
      setters.setSignalLogs(signalLogs)
      setters.setOrders(orders)
      setters.setStartupAudit?.(startupAudit)
      break
    }
    default:
      break
  }
}
