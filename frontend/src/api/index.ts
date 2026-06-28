import api from './client'

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
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

    if (hadToken && !isAuthRoute && (status === 401 || status === 403)) {
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
}

export const userApi = {
  dashboard: () => api.get('/users/dashboard').then(r => r.data),
  trades: () => api.get('/users/trades').then(r => r.data),
  logs: () => api.get('/users/logs').then(r => r.data),
  verifyApi: (api_key: string, api_secret: string) =>
    api.post('/users/bind-api/verify', { api_key, api_secret }).then(r => r.data),
  apiStatus: () => api.get('/users/api-status').then(r => r.data),
  bindApi: (api_key: string, api_secret: string) =>
    api.post('/users/bind-api', { api_key, api_secret }).then(r => r.data),
  principalHistory: () => api.get('/users/principal-history').then(r => r.data),
  profile: () => api.get('/users/profile').then(r => r.data),
}

export const referralApi = {
  summary: () => api.get('/referrals').then(r => r.data),
  invite: () => api.get('/referrals/invite').then(r => r.data),
  settlements: () => api.get('/settlements').then(r => r.data),
}

export const walletApi = {
  depositAddresses: () => api.get('/deposit-addresses').then(r => r.data),
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
  users: () => api.get('/admin/users').then(r => r.data),
  toggleUser: (id: number) => api.post(`/admin/users/${id}/toggle`).then(r => r.data),
  settlements: () => api.get('/admin/settlements').then(r => r.data),
  runWeekly: () => api.post('/admin/settlements/run-weekly').then(r => r.data),
  runSettlement: () => api.post('/admin/settlements/run').then(r => r.data),
  confirmSettlement: (id: number) => api.post(`/admin/settlements/${id}/confirm`).then(r => r.data),
  rejectSettlement: (id: number) => api.post(`/admin/settlements/${id}/reject`).then(r => r.data),
  depositAddresses: () => api.get('/admin/deposit-addresses').then(r => r.data),
  addDepositAddress: (data: { chain: string; address: string; label?: string; sort_order?: number }) =>
    api.post('/admin/deposit-addresses', data).then(r => r.data),
  toggleDepositAddress: (id: number) => api.post(`/admin/deposit-addresses/${id}/toggle`).then(r => r.data),
  deleteDepositAddress: (id: number) => api.delete(`/admin/deposit-addresses/${id}`).then(r => r.data),
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
}
