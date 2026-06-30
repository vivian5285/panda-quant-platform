import { useI18n, localeDate } from '../../../i18n'

export type BalanceRow = {
  chain: string
  address?: string
  configured?: boolean
  usdt?: number | null
  native?: number | null
  native_symbol?: string
  rpc_ready?: boolean
  error?: string | null
  gas_topup_hint?: string | null
  native_low?: boolean
  uses_hot_wallet?: boolean
  label?: string
  is_active?: boolean
}

function fmtUsdt(v: number | null | undefined) {
  if (v == null) return '—'
  return `$${v.toFixed(2)}`
}

function fmtNative(v: number | null | undefined, sym?: string) {
  if (v == null) return '—'
  const n = v >= 1 ? v.toFixed(4) : v.toFixed(6)
  return sym ? `${n} ${sym}` : n
}

export default function WalletBalanceTable({
  rows,
  showAddress = true,
  showRpc = true,
  showLabel = false,
}: {
  rows: BalanceRow[]
  showAddress?: boolean
  showRpc?: boolean
  showLabel?: boolean
}) {
  const { t } = useI18n()

  if (!rows.length) {
    return <p className="text-muted text-sm">{t('admin.walletHub.noRows')}</p>
  }

  return (
    <div className="table-wrap">
      <table className="data-table data-table-sm">
        <thead>
          <tr>
            <th>{t('common.chain')}</th>
            {showLabel && <th>{t('common.label')}</th>}
            {showAddress && <th>{t('common.address')}</th>}
            <th>{t('admin.walletHub.cols.usdt')}</th>
            <th>{t('admin.walletHub.cols.native')}</th>
            {showRpc && <th>{t('admin.walletHub.cols.rpc')}</th>}
            <th>{t('admin.walletHub.cols.gasHint')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={`${row.chain}-${row.address || row.label || ''}`}>
              <td><span className="badge badge-green">{row.chain}</span></td>
              {showLabel && <td>{row.label || '—'}{row.is_active === false && <span className="text-muted text-xs"> ({t('common.no')})</span>}</td>}
              {showAddress && (
                <td className="mono-cell cell-ellipsis" title={row.address}>
                  {row.address ? `${row.address.slice(0, 10)}…${row.address.slice(-6)}` : (
                    <span className="text-muted">{t('admin.walletHub.notConfigured')}</span>
                  )}
                </td>
              )}
              <td>{fmtUsdt(row.usdt)}</td>
              <td>
                <span className={row.native_low ? 'text-red' : undefined} title={row.native_low ? t('admin.walletHub.nativeLow') : undefined}>
                  {fmtNative(row.native, row.native_symbol)}
                </span>
                {row.uses_hot_wallet && (
                  <div className="text-muted text-xs">{t('admin.walletHub.usesHotWallet')}</div>
                )}
                {row.error && <div className="text-muted text-xs" title={row.error}>{row.error.slice(0, 40)}</div>}
              </td>
              {showRpc && (
                <td>
                  {row.rpc_ready == null ? '—' : (
                    <span className={`badge ${row.rpc_ready ? 'badge-green' : 'badge-gray'}`}>
                      {row.rpc_ready ? t('admin.walletHub.rpcOk') : t('admin.walletHub.rpcFail')}
                    </span>
                  )}
                </td>
              )}
              <td className="text-muted text-xs">{row.gas_topup_hint || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function WalletTotalsBar({ overview }: { overview: any }) {
  const { t } = useI18n()
  const totals = overview?.totals || {}
  return (
    <div className="stat-grid section-mb-md">
      <div className="panel-muted-lg p-4">
        <p className="text-muted text-xs">{t('admin.walletHub.totals.coldUsdt')}</p>
        <p className="text-lg font-semibold">${(totals.cold_usdt ?? 0).toFixed(2)}</p>
      </div>
      <div className="panel-muted-lg p-4">
        <p className="text-muted text-xs">{t('admin.walletHub.totals.hotUsdt')}</p>
        <p className="text-lg font-semibold">${(totals.hot_usdt ?? 0).toFixed(2)}</p>
      </div>
      <div className="panel-muted-lg p-4">
        <p className="text-muted text-xs">{t('admin.walletHub.totals.platformUsdt')}</p>
        <p className="text-lg font-semibold">${(totals.platform_usdt ?? 0).toFixed(2)}</p>
      </div>
      <div className="panel-muted-lg p-4">
        <p className="text-muted text-xs">{t('admin.walletHub.totals.hdUsers')}</p>
        <p className="text-lg font-semibold">{overview?.hd_deposit?.users_with_addresses ?? 0}</p>
      </div>
    </div>
  )
}

export function WalletUpdatedAt({ overview, loading, onRefresh }: { overview: any; loading?: boolean; onRefresh: () => void }) {
  const { t, locale } = useI18n()
  return (
    <div className="flex-between-wrap section-mb-sm">
      <p className="text-muted text-xs">
        {overview?.updated_at
          ? t('admin.walletHub.lastUpdated', { time: localeDate(overview.updated_at, locale) })
          : t('admin.walletHub.notLoaded')}
      </p>
      <button className="btn btn-ghost btn-sm" type="button" onClick={onRefresh} disabled={loading}>
        {loading ? t('common.loading') : t('admin.walletHub.refreshBalances')}
      </button>
    </div>
  )
}
