import { Suspense, lazy } from 'react'
import type { AdminTabKey } from '../../components/AdminLayout'
import GlassCard from '../../components/GlassCard'
import { useI18n } from '../../i18n'

const TAB_LOADERS: Record<AdminTabKey, ReturnType<typeof lazy>> = {
  home: lazy(() => import('./tabs/AdminHomeTab')),
  users: lazy(() => import('./tabs/AdminUsersTab')),
  signals: lazy(() => import('./tabs/AdminSignalsTab')),
  execution: lazy(() => import('./tabs/AdminExecutionTab')),
  risk: lazy(() => import('./tabs/AdminRiskTab')),
  analytics: lazy(() => import('./tabs/AdminAnalyticsTab')),
  audit: lazy(() => import('./tabs/AdminAuditTab')),
  finance: lazy(() => import('./tabs/AdminFinanceTab')),
  settlements: lazy(() => import('./tabs/AdminSettlementsTab')),
  deposits: lazy(() => import('./tabs/AdminDepositsTab')),
  referrals: lazy(() => import('./tabs/AdminReferralsTab')),
  withdrawals: lazy(() => import('./tabs/AdminWithdrawalsTab')),
  addresses: lazy(() => import('./tabs/AdminAddressesTab')),
  system: lazy(() => import('./tabs/AdminSystemTab')),
}

function TabFallback() {
  const t = useI18n(s => s.t)
  return (
    <GlassCard className="p-8">
      <p className="text-muted">{t('common.loading')}</p>
    </GlassCard>
  )
}

export default function AdminTabRouter({ tab }: { tab: AdminTabKey }) {
  const TabPanel = TAB_LOADERS[tab] || TAB_LOADERS.home
  return (
    <Suspense fallback={<TabFallback />}>
      <TabPanel />
    </Suspense>
  )
}
