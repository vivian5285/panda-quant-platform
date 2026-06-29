import GlassCard from '../../../components/GlassCard'
import { adminApi } from '../../../api'
import { useAdmin } from '../AdminContext'

export default function AdminAddressesTab() {
  const {
    t, withdrawThresholds, thresholdDraft, setThresholdDraft, saveWithdrawThresholds,
    newAddr, setNewAddr, addAddr, editingAddr, setEditingAddr, saveEditingAddr,
    depositAddrs, load,
  } = useAdmin()

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
        <h3 className="panel-title-sm mb-md">{t('admin.addUsdtAddr')}</h3>
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
            <div className="flex-gap-sm">
              <button className="btn btn-primary btn-sm" type="button" onClick={saveEditingAddr}>{t('common.save')}</button>
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setEditingAddr(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </GlassCard>
      )}
      <GlassCard className="p-0 table-wrap">
        <table className="data-table">
          <thead><tr><th>{t('common.chain')}</th><th>{t('common.label')}</th><th>{t('common.address')}</th><th>{t('common.status')}</th><th>{t('common.action')}</th></tr></thead>
          <tbody>
            {depositAddrs.map((a: any) => (
              <tr key={a.id}>
                <td><span className="badge badge-green">{a.chain}</span></td>
                <td>{a.label || t('common.none')}</td>
                <td className="mono-address">{a.address}</td>
                <td>{a.is_active ? t('common.yes') : t('common.no')}</td>
                <td className="table-actions">
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
