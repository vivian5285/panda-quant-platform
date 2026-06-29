import { useRef } from 'react'
import GlassCard from '../../../components/GlassCard'
import { adminApi } from '../../../api'
import { useAdmin } from '../AdminContext'

const PAYOUT_CHAINS = ['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON'] as const

export default function AdminAddressesTab() {
  const {
    t, withdrawThresholds, thresholdDraft, setThresholdDraft, saveWithdrawThresholds,
    newAddr, setNewAddr, addAddr, editingAddr, setEditingAddr, saveEditingAddr,
    depositAddrs, load, uploadAddrQr, removeAddrQr,
    payoutSettings, payoutKeyDraft, setPayoutKeyDraft, payoutAutoDraft, setPayoutAutoDraft, savePayoutSettings,
  } = useAdmin()
  const editQrRef = useRef<HTMLInputElement>(null)
  const rowQrRefs = useRef<Record<number, HTMLInputElement | null>>({})

  const onPickQr = (id: number, file: File | undefined) => {
    if (!file) return
    uploadAddrQr(id, file)
  }

  return (
    <div>
      <p className="text-muted text-sm section-mb-sm">{t('admin.addrHintPerf')}</p>
      <GlassCard className="p-6 section-mb-lg page-panel-narrow">
        <h3 className="panel-title-sm mb-md">{t('admin.withdrawThresholdTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.withdrawThresholdHint')}</p>
        <form onSubmit={saveWithdrawThresholds} className="form-stack">
          <div className="grid-2-col-gap">
            <label className="form-field">
              <span className="text-muted text-sm">{t('admin.instantMaxUsd')}</span>
              <input className="input" type="number" step="1" min="1"
                value={thresholdDraft.auto_max_usd}
                onChange={e => setThresholdDraft((d: any) => ({ ...d, auto_max_usd: e.target.value }))} required />
            </label>
            <label className="form-field">
              <span className="text-muted text-sm">{t('admin.reviewMinUsd')}</span>
              <input className="input" type="number" step="1" min="1"
                value={thresholdDraft.review_min_usd}
                onChange={e => setThresholdDraft((d: any) => ({ ...d, review_min_usd: e.target.value }))} required />
            </label>
          </div>
          {withdrawThresholds && (
            <p className="text-muted text-xs">
              {t('admin.withdrawThresholdCurrent', {
                instant: withdrawThresholds.auto_max_usd,
                review: withdrawThresholds.review_min_usd,
              })}
            </p>
          )}
          {withdrawThresholds && (
            <p className={`text-xs ${withdrawThresholds.payout_auto_enabled ? 'text-green' : 'text-muted'}`}>
              {withdrawThresholds.payout_auto_enabled
                ? t('admin.payoutAutoOn', { chains: (withdrawThresholds.payout_configured_chains || []).join(', ') || '—' })
                : t('admin.payoutAutoOff')}
            </p>
          )}
          <button className="btn btn-primary btn-sm" type="submit">{t('common.save')}</button>
        </form>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg page-panel-narrow">
        <h3 className="panel-title-sm mb-md">{t('admin.payoutWalletTitle')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.payoutWalletHint')}</p>
        <form onSubmit={savePayoutSettings} className="form-stack">
          <label className="auth-remember">
            <input
              type="checkbox"
              checked={payoutAutoDraft}
              onChange={e => setPayoutAutoDraft(e.target.checked)}
            />
            {t('admin.payoutAutoToggle')}
          </label>
          {PAYOUT_CHAINS.map(chain => (
            <label key={chain} className="form-field">
              <span className="text-muted text-sm" style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{chain}</span>
                <span className={payoutSettings?.chains?.[chain] ? 'text-green text-xs' : 'text-muted text-xs'}>
                  {payoutSettings?.chains?.[chain] ? t('admin.payoutKeyConfigured') : t('admin.payoutKeyMissing')}
                </span>
              </span>
              <input
                className="input input-mono"
                type="password"
                autoComplete="new-password"
                placeholder={t('admin.payoutKeyPh', { chain })}
                value={payoutKeyDraft[chain] || ''}
                onChange={e => setPayoutKeyDraft((d: Record<string, string>) => ({ ...d, [chain]: e.target.value }))}
              />
            </label>
          ))}
          <button className="btn btn-primary btn-sm" type="submit">{t('common.save')}</button>
        </form>
      </GlassCard>
      <GlassCard className="p-6 section-mb-lg page-panel-narrow">
        <h3 className="panel-title-sm mb-md">{t('admin.addUsdtAddr')}</h3>
        <p className="text-muted text-sm section-mb-sm">{t('admin.addrQrHint')}</p>
        <form onSubmit={addAddr} className="form-stack">
          <select className="input" value={newAddr.chain} onChange={e => setNewAddr({ ...newAddr, chain: e.target.value })}>
            {['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL'].map(c => <option key={c}>{c}</option>)}
          </select>
          <input className="input" placeholder={t('admin.addrLabelPh')} value={newAddr.label}
            onChange={e => setNewAddr({ ...newAddr, label: e.target.value })} />
          <input className="input" placeholder={t('admin.usdtAddrPh')} value={newAddr.address}
            onChange={e => setNewAddr({ ...newAddr, address: e.target.value })} required />
          <button className="btn btn-primary" type="submit">{t('common.add')}</button>
        </form>
      </GlassCard>
      {editingAddr && (
        <GlassCard className="p-6 section-mb-lg page-panel-narrow">
          <h3 className="panel-title-sm mb-md">{t('admin.editUsdtAddr')} #{editingAddr.id}</h3>
          <div className="form-stack">
            <select className="input" value={editingAddr.chain} onChange={e => setEditingAddr({ ...editingAddr, chain: e.target.value })}>
              {['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL'].map(c => <option key={c}>{c}</option>)}
            </select>
            <input className="input" value={editingAddr.label || ''} onChange={e => setEditingAddr({ ...editingAddr, label: e.target.value })} />
            <input className="input" value={editingAddr.address || ''} onChange={e => setEditingAddr({ ...editingAddr, address: e.target.value })} required />
            <label className="auth-remember">
              <input type="checkbox" checked={!!editingAddr.is_active} onChange={e => setEditingAddr({ ...editingAddr, is_active: e.target.checked })} />
              {t('admin.addrActive')}
            </label>
            <div className="form-field">
              <span className="text-muted text-sm">{t('admin.walletQr')}</span>
              {editingAddr.has_qr && (
                <img
                  className="deposit-qr-preview section-mb-xs"
                  src={`${adminApi.depositAddressQrUrl(editingAddr.id)}?t=${Date.now()}`}
                  alt={t('admin.walletQr')}
                />
              )}
              <input
                ref={editQrRef}
                className="input"
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                onChange={e => {
                  const file = e.target.files?.[0]
                  if (file) uploadAddrQr(editingAddr.id, file)
                  e.target.value = ''
                }}
              />
              {editingAddr.has_qr && (
                <button className="btn btn-ghost btn-sm section-mt-xs" type="button" onClick={() => removeAddrQr(editingAddr.id)}>
                  {t('admin.qrRemove')}
                </button>
              )}
            </div>
            <div className="flex-gap-sm">
              <button className="btn btn-primary btn-sm" type="button" onClick={saveEditingAddr}>{t('common.save')}</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setEditingAddr(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </GlassCard>
      )}
      <GlassCard className="p-0 table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('common.chain')}</th>
              <th>{t('common.label')}</th>
              <th>{t('common.address')}</th>
              <th>{t('admin.walletQr')}</th>
              <th>{t('common.status')}</th>
              <th>{t('common.action')}</th>
            </tr>
          </thead>
          <tbody>
            {depositAddrs.map((a: any) => (
              <tr key={a.id}>
                <td><span className="badge badge-green">{a.chain}</span></td>
                <td>{a.label || t('common.none')}</td>
                <td className="mono-address">{a.address}</td>
                <td>
                  {a.has_qr ? (
                    <img className="deposit-qr-thumb" src={adminApi.depositAddressQrUrl(a.id)} alt={t('admin.walletQr')} />
                  ) : (
                    <span className="text-muted text-xs">{t('admin.qrMissing')}</span>
                  )}
                </td>
                <td>{a.is_active ? t('common.yes') : t('common.no')}</td>
                <td className="table-actions">
                  <input
                    ref={el => { rowQrRefs.current[a.id] = el }}
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    className="sr-only"
                    onChange={e => {
                      onPickQr(a.id, e.target.files?.[0])
                      e.target.value = ''
                    }}
                  />
                  <button className="btn btn-ghost btn-xs" type="button" onClick={() => rowQrRefs.current[a.id]?.click()}>
                    {a.has_qr ? t('admin.qrReplace') : t('admin.qrUpload')}
                  </button>
                  {a.has_qr && (
                    <button className="btn btn-ghost btn-xs" type="button" onClick={() => removeAddrQr(a.id)}>{t('admin.qrRemove')}</button>
                  )}
                  <button className="btn btn-ghost btn-xs" type="button" onClick={() => setEditingAddr({ ...a })}>{t('common.edit')}</button>
                  <button className="btn btn-ghost btn-xs" onClick={() => adminApi.toggleDepositAddress(a.id).then(load)}>{t('common.toggle')}</button>
                  <button className="btn btn-ghost btn-xs" onClick={() => adminApi.deleteDepositAddress(a.id).then(load)}>{t('common.delete')}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </div>
  )
}
