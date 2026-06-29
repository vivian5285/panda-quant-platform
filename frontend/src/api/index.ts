import api from './client'

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  const locale = localStorage.getItem('locale')
  config.headers['Accept-Language'] = locale === 'en' ? 'en' : 'zh-CN'
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
    config.headers['X-Access-Token'] = token
  }
  return config
})

let logoutTimer: ReturnType<typeof setTimeout> | null = null

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    const hadToken = !!localStorage.getItem('token')
    const url = err.config?.url || ''
    const isAuthRoute = url.includes('/auth/login') || url.includes('/auth/register')

    if (hadToken && !isAuthRoute && status === 401) {
      if (logoutTimer) clearTimeout(logoutTimer)
      logoutTimer = setTimeout(() => {
        if (!localStorage.getItem('token')) return
        localStorage.removeItem('token')
        localStorage.removeItem('uid')
        localStorage.removeItem('displayName')
        localStorage.removeItem('role')
        if (!window.location.pathname.includes('/login')) {
          window.location.href = '/login'
        }
      }, 300)
    }
    return Promise.reject(err)
  }
)

export default api

export const authApi = {
  login: (account: string, password: string) =>
    api.post('/auth/login', { account, password }).then(r => r.data),
  loginSms: (phone: string, code: string) =>
    api.post('/auth/sms/login', { phone, code }).then(r => r.data),
  loginEmail: (email: string, code: string) =>
    api.post('/auth/email/login', { email, code }).then(r => r.data),
  loginTotp: (challenge_token: string, code: string) =>
    api.post('/auth/login/totp', { challenge_token, code }).then(r => r.data),
  sendSms: (phone: string, purpose = 'login') =>
    api.post('/auth/sms/send', { phone, purpose }).then(r => r.data),
  sendEmail: (email: string, purpose = 'login') =>
    api.post('/auth/email/send', { email, purpose }).then(r => r.data),
  sendSecurityCodes: () => api.post('/auth/security/send-codes').then(r => r.data),
  register: (data: {
    email?: string; phone?: string; password: string; verification_code: string; referral_code?: string
  }) => api.post('/auth/register', data).then(r => r.data),
  me: () => api.get('/auth/me').then(r => r.data),
  updateNickname: (nickname: string) =>
    api.patch('/auth/profile/nickname', { nickname }).then(r => r.data),
  changePassword: (old_password: string, new_password: string, email_code: string, phone_code: string) =>
    api.post('/auth/password/change', { old_password, new_password, email_code, phone_code }).then(r => r.data),
  setWithdrawPassword: (withdraw_password: string, email_code: string, phone_code: string) =>
    api.post('/auth/withdraw-password', { withdraw_password, email_code, phone_code }).then(r => r.data),
  bindEmail: (email: string, email_code: string, phone_code?: string) =>
    api.post('/auth/bind-email', { email, email_code, phone_code }).then(r => r.data),
    bindPhone: (phone: string, phone_code: string, email_code?: string) =>
    api.post('/auth/bind-phone', { phone, phone_code, email_code }).then(r => r.data),
  oauthProviders: () => api.get('/auth/oauth/providers').then(r => r.data),
}

export type TradeQueryParams = { limit?: number; offset?: number; start?: string; end?: string }
export type LogQueryParams = TradeQueryParams & { sync_exchange?: boolean }

export const userApi = {
  dashboard: () => api.get('/users/dashboard').then(r => r.data),
  trades: (params?: TradeQueryParams) => api.get('/users/trades', { params }).then(r => r.data),
  logs: (params?: LogQueryParams) => api.get('/users/logs', { params }).then(r => r.data),
  syncExchangeLogs: (days = 90) => api.post('/users/sync-exchange-logs', null, { params: { days } }).then(r => r.data),
  analytics: (days = 90) => api.get('/users/analytics', { params: { days } }).then(r => r.data),
  signals: (limit = 100) => api.get('/users/signals', { params: { limit } }).then(r => r.data),
  verifyApi: (api_key: string, api_secret: string) =>
    api.post('/users/bind-api/verify', { api_key, api_secret }).then(r => r.data),
  apiStatus: () => api.get('/users/api-status').then(r => r.data),
  bindApi: (api_key: string, api_secret: string, email_code?: string, phone_code?: string) =>
    api.post('/users/bind-api', { api_key, api_secret, email_code, phone_code }).then(r => r.data),
  unbindApi: (email_code: string, phone_code: string) =>
    api.delete('/users/bind-api', { params: { email_code, phone_code } }).then(r => r.data),
  positions: () => api.get('/users/positions').then(r => r.data),
  principalHistory: () => api.get('/users/principal-history').then(r => r.data),
  profile: () => api.get('/users/profile').then(r => r.data),
  tradingControl: () => api.get('/users/trading-control').then(r => r.data),
  updateTradingControl: (data: { trading_paused?: boolean; risk_level?: string }) =>
    api.patch('/users/trading-control', data).then(r => r.data),
}

export const publicApi = {
  stats: () => api.get('/public/stats').then(r => r.data),
  marketTicker: () => api.get('/public/market-ticker').then(r => r.data),
}

export const strategyApi = {
  list: () => api.get('/strategies').then(r => r.data),
  create: (data: object) => api.post('/strategies', data).then(r => r.data),
  update: (id: number, data: object) => api.patch(`/strategies/${id}`, data).then(r => r.data),
  remove: (id: number) => api.delete(`/strategies/${id}`).then(r => r.data),
  versions: (id: number) => api.get(`/strategies/${id}/versions`).then(r => r.data),
}

export const notificationApi = {
  list: (unread_only?: boolean) => api.get('/notifications', { params: { unread_only } }).then(r => r.data),
  unreadCount: () => api.get('/notifications/unread-count').then(r => r.data),
  markRead: (id: number) => api.post(`/notifications/${id}/read`).then(r => r.data),
  markAllRead: () => api.post('/notifications/read-all').then(r => r.data),
}

export const settingsApi = {
  get: () => api.get('/settings').then(r => r.data),
  update: (data: object) => api.patch('/settings', data).then(r => r.data),
  totpSetup: () => api.post('/settings/totp/setup').then(r => r.data),
  totpEnable: (code: string) => api.post('/settings/totp/enable', { code }).then(r => r.data),
  totpDisable: (code: string) => api.post('/settings/totp/disable', { code }).then(r => r.data),
  apiKeys: () => api.get('/settings/api-keys').then(r => r.data),
  createApiKey: (name: string) => api.post('/settings/api-keys', { name }).then(r => r.data),
  revokeApiKey: (id: number) => api.delete(`/settings/api-keys/${id}`).then(r => r.data),
}

export const billingApi = {
  plans: () => api.get('/billing/plans').then(r => r.data),
  subscription: () => api.get('/billing/subscription').then(r => r.data),
  subscribe: (plan_code: string, payment_method?: string) => api.post('/billing/subscribe', { plan_code, payment_method }).then(r => r.data),
  payInvoice: (id: number, tx_hash: string) => api.post(`/billing/invoices/${id}/pay`, { tx_hash }).then(r => r.data),
  invoices: () => api.get('/billing/invoices').then(r => r.data),
}

export const referralApi = {
  summary: () => api.get('/referrals').then(r => r.data),
  invite: () => api.get('/referrals/invite').then(r => r.data),
  settlements: () => api.get('/settlements').then(r => r.data),
  tree: () => api.get('/referrals/tree').then(r => r.data),
  settlementPdf: (id: number) => api.get(`/settlements/${id}/pdf`, { responseType: 'blob' }).then(r => r.data),
}

export const walletApi = {
  depositAddresses: () => api.get('/deposit-addresses').then(r => r.data),
  depositAddressQrUrl: (id: number) => `/api/deposit-addresses/${id}/qr`,
  paySettlement: (id: number, chain: string, tx_hash: string, amount: number) =>
    api.post(`/settlements/${id}/pay`, { chain, tx_hash, amount }).then(r => r.data),
  rewardAccount: () => api.get('/reward-account').then(r => r.data),
  rewardLedger: () => api.get('/reward-ledger').then(r => r.data),
  withdrawSettings: () => api.get('/withdraw/settings').then(r => r.data),
  withdrawAddresses: () => api.get('/withdraw/addresses').then(r => r.data),
  addWithdrawAddress: (data: {
    chain: string; address: string; address_type?: string; source_name?: string;
    label?: string; memo?: string; is_default?: boolean;
    email_code: string; phone_code: string;
  }) => api.post('/withdraw/addresses', data).then(r => r.data),
  setDefaultAddress: (id: number) => api.post(`/withdraw/addresses/${id}/default`).then(r => r.data),
  deleteWithdrawAddress: (id: number, email_code: string, phone_code: string) =>
    api.delete(`/withdraw/addresses/${id}`, { params: { email_code, phone_code } }).then(r => r.data),
  feePreview: (chain: string, amount: number) =>
    api.get('/withdraw/fee-preview', { params: { chain, amount } }).then(r => r.data),
  withdraw: (amount: number, withdraw_password: string, email_code: string, phone_code: string, address_book_id?: number, chain?: string, address?: string) =>
    api.post('/withdraw', { amount, withdraw_password, email_code, phone_code, address_book_id, chain, address }).then(r => r.data),
  withdrawals: () => api.get('/withdrawals').then(r => r.data),
  lookupRecipient: (recipient: string) =>
    api.get('/transfer/lookup', { params: { recipient } }).then(r => r.data),
  transfer: (recipient: string, amount: number, note?: string) =>
    api.post('/transfer', { recipient, amount, note }).then(r => r.data),
  transfers: () => api.get('/transfers').then(r => r.data),
}

export const adminApi = {
  overview: () => api.get('/admin/overview').then(r => r.data),
  users: (params?: { q?: string; api_status?: string; trading_paused?: boolean; risk_level?: string; risk_flag?: boolean }) =>
    api.get('/admin/users', { params }).then(r => r.data),
  batchNotifyUsers: (user_ids: number[], title: string, message: string) =>
    api.post('/admin/users/batch-notify', { user_ids, title, message }).then(r => r.data),
  batchTradingControl: (user_ids: number[], data: { trading_paused?: boolean; risk_level?: string }) =>
    api.post('/admin/users/batch-trading-control', { user_ids, ...data }).then(r => r.data),
  userDetail: (id: number) => api.get(`/admin/users/${id}`).then(r => r.data),
  userTrades: (id: number, params?: TradeQueryParams) =>
    api.get(`/admin/users/${id}/trades`, { params: { limit: 200, ...params } }).then(r => r.data),
  userLogs: (id: number, params?: LogQueryParams) =>
    api.get(`/admin/users/${id}/logs`, { params: { limit: 200, ...params } }).then(r => r.data),
  userPrincipalHistory: (id: number) =>
    api.get(`/admin/users/${id}/principal-history`).then(r => r.data),
  userReferralStats: (id: number) =>
    api.get(`/admin/users/${id}/referral-stats`).then(r => r.data),
  referralsOverview: () => api.get('/admin/referrals/overview').then(r => r.data),
  syncUserExchangeLogs: (id: number, days = 90) =>
    api.post(`/admin/users/${id}/sync-exchange-logs`, null, { params: { days } }).then(r => r.data),
  toggleUser: (id: number) => api.post(`/admin/users/${id}/toggle`).then(r => r.data),
  settlements: () => api.get('/admin/settlements').then(r => r.data),
  runWeekly: () => api.post('/admin/settlements/run-weekly').then(r => r.data),
  runSettlement: () => api.post('/admin/settlements/run').then(r => r.data),
  confirmSettlement: (id: number) => api.post(`/admin/settlements/${id}/confirm`).then(r => r.data),
  rejectSettlement: (id: number) => api.post(`/admin/settlements/${id}/reject`).then(r => r.data),
  depositAddresses: () => api.get('/admin/deposit-addresses').then(r => r.data),
  addDepositAddress: (data: { chain: string; address: string; label?: string; sort_order?: number }) =>
    api.post('/admin/deposit-addresses', data).then(r => r.data),
  updateDepositAddress: (id: number, data: { chain?: string; address?: string; label?: string; sort_order?: number; is_active?: boolean }) =>
    api.patch(`/admin/deposit-addresses/${id}`, data).then(r => r.data),
  toggleDepositAddress: (id: number) => api.post(`/admin/deposit-addresses/${id}/toggle`).then(r => r.data),
  deleteDepositAddress: (id: number) => api.delete(`/admin/deposit-addresses/${id}`).then(r => r.data),
  uploadDepositAddressQr: (id: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post(`/admin/deposit-addresses/${id}/qr-image`, fd).then(r => r.data)
  },
  deleteDepositAddressQr: (id: number) => api.delete(`/admin/deposit-addresses/${id}/qr-image`).then(r => r.data),
  depositAddressQrUrl: (id: number) => `/api/deposit-addresses/${id}/qr`,
  withdrawSettings: () => api.get('/admin/withdraw/settings').then(r => r.data),
  updateWithdrawSettings: (auto_max_usd: number, review_min_usd: number) =>
    api.patch('/admin/withdraw/settings', { auto_max_usd, review_min_usd }).then(r => r.data),
  payoutSettings: () => api.get('/admin/payout/settings').then(r => r.data),
  updatePayoutSettings: (data: { auto_enabled?: boolean; private_keys?: Record<string, string> }) =>
    api.patch('/admin/payout/settings', data).then(r => r.data),
  withdrawals: () => api.get('/admin/withdrawals').then(r => r.data),
  approveWithdrawal: (id: number) => api.post(`/admin/withdrawals/${id}/approve`).then(r => r.data),
  completeWithdrawal: (id: number, tx_hash: string, admin_note?: string) =>
    api.post(`/admin/withdrawals/${id}/complete`, { tx_hash, admin_note }).then(r => r.data),
  rejectWithdrawal: (id: number, admin_note?: string) =>
    api.post(`/admin/withdrawals/${id}/reject`, { admin_note }).then(r => r.data),
  alerts: (unread_only?: boolean) =>
    api.get('/admin/alerts', { params: { unread_only: unread_only || false } }).then(r => r.data),
  readAlert: (id: number) => api.post(`/admin/alerts/${id}/read`).then(r => r.data),
  readAllAlerts: () => api.post('/admin/alerts/read-all').then(r => r.data),
  startupAudit: () => api.get('/admin/startup-audit').then(r => r.data),
  systemMonitor: () => api.get('/admin/system/monitor').then(r => r.data),
  auditLogs: (params?: { limit?: number; action?: string; user_id?: number; actor_id?: number; q?: string }) =>
    api.get('/admin/system/audit-logs', { params }).then(r => r.data),
  loginRecords: () => api.get('/admin/system/login-records').then(r => r.data),
  riskAlerts: () => api.get('/admin/system/risk-alerts').then(r => r.data),
  allOrders: () => api.get('/admin/system/orders').then(r => r.data),
  allTradeLogs: (limit = 200) => api.get('/admin/system/trade-logs', { params: { limit } }).then(r => r.data),
  onlineStats: () => api.get('/admin/system/online').then(r => r.data),
  globalTradingControl: () => api.get('/admin/system/trading-control').then(r => r.data),
  setGlobalTradingPause: (global_trading_paused: boolean, note?: string) =>
    api.patch('/admin/system/trading-control', { global_trading_paused, note }).then(r => r.data),
  setGlobalRiskMultiplier: (global_risk_multiplier: number) =>
    api.patch('/admin/system/trading-control', { global_risk_multiplier }).then(r => r.data),
  strategies: (status?: string) => api.get('/admin/strategies', { params: status ? { status } : {} }).then(r => r.data),
  reviewStrategy: (id: number, action: 'approve' | 'reject' | 'pause', note?: string) =>
    api.post(`/admin/strategies/${id}/review`, { action, note }).then(r => r.data),
  userTradingControl: (userId: number, data?: { trading_paused?: boolean; risk_level?: string }) =>
    data
      ? api.patch(`/admin/users/${userId}/trading-control`, data).then(r => r.data)
      : api.get(`/admin/users/${userId}/trading-control`).then(r => r.data),
  forceCloseUser: (userId: number) =>
    api.post(`/admin/users/${userId}/force-close`).then(r => r.data),
  signalTemplates: () => api.get('/admin/signal-templates').then(r => r.data),
  createSignalTemplate: (data: { name: string; description?: string; payload?: object; enabled?: boolean }) =>
    api.post('/admin/signal-templates', data).then(r => r.data),
  updateSignalTemplate: (id: number, data: object) =>
    api.patch(`/admin/signal-templates/${id}`, data).then(r => r.data),
  deleteSignalTemplate: (id: number) => api.delete(`/admin/signal-templates/${id}`).then(r => r.data),
  testSignalTemplate: (id: number) => api.post(`/admin/signal-templates/${id}/test`).then(r => r.data),
  signalDispatchLogs: (limit = 50) =>
    api.get('/admin/system/signal-dispatch-logs', { params: { limit } }).then(r => r.data),
  signalDispatchResults: (dispatchId: number) =>
    api.get(`/admin/system/signal-dispatch-logs/${dispatchId}/results`).then(r => r.data),
  platformAnalytics: (days = 14) =>
    api.get('/admin/system/analytics', { params: { days } }).then(r => r.data),
  webhookTest: (payload: object) =>
    api.post('/admin/system/webhook-test', { payload }).then(r => r.data),
}
