import { useState, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

import GlassCard from '../../../components/GlassCard'

import { adminApi } from '../../../api'

import { useAdmin } from '../AdminContext'

import WalletBalanceTable, { WalletTotalsBar, WalletUpdatedAt } from '../wallet/WalletBalanceTable'
import WalletSetupGuide from '../wallet/WalletSetupGuide'



const PAYOUT_CHAINS = ['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON'] as const

const EVM_RPC_CHAINS = ['ERC20', 'BEP20', 'ARBITRUM', 'POLYGON'] as const

type WalletSection = 'overview' | 'hd' | 'cold' | 'hot' | 'platform' | 'withdraw' | 'rpc' | 'dingtalk'



const SECTIONS: WalletSection[] = ['overview', 'hd', 'cold', 'hot', 'platform', 'withdraw', 'rpc', 'dingtalk']



function RoleGuide({ title, desc, bullets }: { title: string; desc: string; bullets: string[] }) {

  return (

    <div className="panel-muted-lg p-4 section-mb-sm">

      <h4 className="text-sm font-semibold section-mb-xs">{title}</h4>

      <p className="text-muted text-sm section-mb-xs">{desc}</p>

      <ul className="text-muted text-xs wallet-guide-list">

        {bullets.map(b => <li key={b}>{b}</li>)}

      </ul>

    </div>

  )

}



export default function AdminAddressesTab() {

  const {

    t, withdrawThresholds, thresholdDraft, setThresholdDraft, saveWithdrawThresholds,

    newAddr, setNewAddr, addAddr, editingAddr, setEditingAddr, saveEditingAddr,

    depositAddrs, load, uploadAddrQr, removeAddrQr,

    depositWalletSettings, depositMnemonicDraft, setDepositMnemonicDraft,

    depositBackfillDraft, setDepositBackfillDraft,

    saveDepositWalletSettings, clearDepositWalletSettings,

    sweepSettings, sweepLogs, sweepColdDraft, setSweepColdDraft,

    sweepGasDraft, setSweepGasDraft, sweepAutoDraft, setSweepAutoDraft,

    sweepMinDraft, setSweepMinDraft, sweepRequireMatched, setSweepRequireMatched,

    saveSweepSettings, runSweepNow,

    payoutSettings, payoutKeyDraft, setPayoutKeyDraft, payoutAutoDraft, setPayoutAutoDraft, savePayoutSettings,

    walletOverview, walletOverviewLoading, refreshWalletOverview,

    dingtalkSettings, dingtalkDraft, setDingtalkDraft, saveDingtalkSettings,

    chainRpcSettings, chainRpcDraft, setChainRpcDraft, saveChainRpcSettings, clearChainRpcSettings,

    setWalletSection,

  } = useAdmin()

  const [searchParams] = useSearchParams()

  const rawSection = searchParams.get('wallet') || 'overview'

  const section: WalletSection = SECTIONS.includes(rawSection as WalletSection)

    ? (rawSection as WalletSection)

    : 'overview'

  const setSection = (id: WalletSection) => setWalletSection(id)

  const editQrRef = useRef<HTMLInputElement>(null)

  const rowQrRefs = useRef<Record<number, HTMLInputElement | null>>({})



  const onPickQr = (id: number, file: File | undefined) => {

    if (!file) return

    uploadAddrQr(id, file)

  }



  const chainMatrix = PAYOUT_CHAINS.map(chain => {

    const cold = walletOverview?.cold_wallets?.find((w: any) => w.chain === chain)

    const hot = walletOverview?.hot_wallets?.find((w: any) => w.chain === chain)

    return { chain, cold, hot, rpc: walletOverview?.rpc_status?.[chain] }

  })



  return (

    <div className="wallet-hub">

      <GlassCard className="p-4 section-mb-md">

        <h2 className="panel-title-sm">{t('admin.walletHub.title')}</h2>

        <p className="text-muted text-sm section-mt-xs">{t('admin.walletHub.subtitle')}</p>

      </GlassCard>



      <WalletSetupGuide guide="cheatsheet" />



      <div className="wallet-section-nav section-mb-md">

        {SECTIONS.map(id => (

          <button

            key={id}

            type="button"

            className={`btn btn-sm ${section === id ? 'btn-primary' : 'btn-ghost'}`}

            onClick={() => setSection(id)}

          >

            {t(`admin.walletHub.sections.${id}`)}

          </button>

        ))}

      </div>



      {section === 'overview' && (

        <>

          <WalletUpdatedAt overview={walletOverview} loading={walletOverviewLoading} onRefresh={refreshWalletOverview} />

          <WalletTotalsBar overview={walletOverview} />



          <div className="grid-2-col-gap section-mb-lg">

            <GlassCard className="p-4">

              <h4 className="text-sm font-semibold section-mb-xs">{t('admin.walletHub.configStatus')}</h4>

              <ul className="text-sm wallet-config-status-list">

                <li className={depositWalletSettings?.configured ? 'text-green' : 'text-muted'}>

                  HD {depositWalletSettings?.configured ? t('admin.walletHub.statusOk') : t('admin.walletHub.statusMissing')}

                </li>

                <li className={(sweepSettings?.ready_chains || []).length ? 'text-green' : 'text-muted'}>

                  {t('admin.walletHub.roles.cold.short')} {(sweepSettings?.ready_chains || []).length ? t('admin.walletHub.statusOk') : t('admin.walletHub.statusMissing')}

                </li>

                <li className={payoutSettings?.auto_enabled ? 'text-green' : 'text-muted'}>

                  {t('admin.walletHub.roles.hot.short')} {payoutSettings?.auto_enabled ? t('admin.walletHub.statusOk') : t('admin.walletHub.statusPartial')}

                </li>

                <li className={dingtalkSettings?.configured ? 'text-green' : 'text-muted'}>

                  {t('admin.dingtalkSettingsTitle')} {dingtalkSettings?.configured ? t('admin.walletHub.statusOk') : t('admin.walletHub.statusMissing')}

                </li>

                <li className={chainRpcSettings?.tron_api_url_configured ? 'text-green' : 'text-muted'}>

                  RPC {chainRpcSettings?.tron_api_url_configured ? t('admin.walletHub.statusOk') : t('admin.walletHub.statusMissing')}

                </li>

              </ul>

              <div className="flex-gap-sm section-mt-sm flex-wrap">

                <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSection('hd')}>HD</button>

                <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSection('cold')}>{t('admin.walletHub.roles.cold.short')}</button>

                <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSection('hot')}>{t('admin.walletHub.roles.hot.short')}</button>

                <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSection('rpc')}>RPC</button>

                <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSection('dingtalk')}>{t('admin.walletHub.sections.dingtalk')}</button>

              </div>

            </GlassCard>

            <RoleGuide

              title={t('admin.walletHub.roles.hd.title')}

              desc={t('admin.walletHub.roles.hd.desc')}

              bullets={[t('admin.walletHub.roles.hd.b1'), t('admin.walletHub.roles.hd.b2'), t('admin.walletHub.roles.hd.b3')]}

            />

            <RoleGuide

              title={t('admin.walletHub.roles.cold.title')}

              desc={t('admin.walletHub.roles.cold.desc')}

              bullets={[t('admin.walletHub.roles.cold.b1'), t('admin.walletHub.roles.cold.b2'), t('admin.walletHub.roles.cold.b3')]}

            />

            <RoleGuide

              title={t('admin.walletHub.roles.hot.title')}

              desc={t('admin.walletHub.roles.hot.desc')}

              bullets={[t('admin.walletHub.roles.hot.b1'), t('admin.walletHub.roles.hot.b2'), t('admin.walletHub.roles.hot.b3')]}

            />

            <RoleGuide

              title={t('admin.walletHub.roles.platform.title')}

              desc={t('admin.walletHub.roles.platform.desc')}

              bullets={[t('admin.walletHub.roles.platform.b1'), t('admin.walletHub.roles.platform.b2')]}

            />

          </div>



          <GlassCard className="p-0 section-mb-lg">

            <div className="card-section-head"><h3 className="panel-title-sm">{t('admin.walletHub.chainMatrixTitle')}</h3></div>

            <div className="table-wrap">

              <table className="data-table data-table-sm">

                <thead>

                  <tr>

                    <th>{t('common.chain')}</th>

                    <th>{t('admin.walletHub.cols.rpc')}</th>

                    <th>{t('admin.walletHub.roles.cold.short')}</th>

                    <th>{t('admin.walletHub.roles.hot.short')}</th>

                    <th>{t('admin.walletHub.cols.native')}</th>

                  </tr>

                </thead>

                <tbody>

                  {chainMatrix.map(({ chain, cold, hot, rpc }) => (

                    <tr key={chain}>

                      <td><span className="badge badge-green">{chain}</span></td>

                      <td><span className={`badge ${rpc ? 'badge-green' : 'badge-gray'}`}>{rpc ? t('admin.walletHub.rpcOk') : t('admin.walletHub.rpcFail')}</span></td>

                      <td>{cold?.usdt != null ? `$${cold.usdt.toFixed(2)}` : '—'}</td>

                      <td>{hot?.usdt != null ? `$${hot.usdt.toFixed(2)}` : '—'}</td>

                      <td className={hot?.native_low ? 'text-red' : undefined}>

                        {hot?.native != null ? `${hot.native} ${hot.native_symbol}` : '—'}

                      </td>

                    </tr>

                  ))}

                </tbody>

              </table>

            </div>

          </GlassCard>



          <GlassCard className="p-4 section-mb-lg">

            <h3 className="panel-title-sm section-mb-sm">{t('admin.walletHub.flowTitle')}</h3>

            <p className="text-muted text-sm">{t('admin.walletHub.flowDesc')}</p>

          </GlassCard>

        </>

      )}



      {section === 'hd' && (

        <>

          <RoleGuide

            title={t('admin.walletHub.roles.hd.title')}

            desc={t('admin.walletHub.roles.hd.desc')}

            bullets={[t('admin.walletHub.roles.hd.b1'), t('admin.walletHub.roles.hd.b2'), t('admin.walletHub.roles.hd.b3')]}

          />

          <WalletSetupGuide guide="hd" />

          <GlassCard className="p-6 section-mb-lg page-panel-narrow">

            <h3 className="panel-title-sm mb-md">{t('admin.depositWalletTitle')}</h3>

            <p className="text-muted text-sm section-mb-sm">{t('admin.depositWalletHint')}</p>

            <p className={`text-xs section-mb-sm ${depositWalletSettings?.configured ? 'text-green' : 'text-muted'}`}>

              {depositWalletSettings?.configured

                ? t('admin.depositMnemonicConfigured', {

                    source: depositWalletSettings.source === 'runtime'

                      ? t('admin.depositSourceRuntime')

                      : t('admin.depositSourceEnv'),

                    offset: depositWalletSettings.derivation_offset,

                  })

                : t('admin.depositMnemonicMissing')}

            </p>

            {walletOverview?.hd_deposit && (

              <p className="text-muted text-xs section-mb-sm">

                {t('admin.walletHub.hdUsers', { count: walletOverview.hd_deposit.users_with_addresses ?? 0 })}

              </p>

            )}

            <form onSubmit={saveDepositWalletSettings} className="form-stack">

              <label className="form-field">

                <span className="text-muted text-sm">{t('admin.depositMnemonicLabel')}</span>

                <textarea

                  className="input input-mono"

                  rows={3}

                  autoComplete="off"

                  spellCheck={false}

                  placeholder={t('admin.depositMnemonicPh')}

                  value={depositMnemonicDraft}

                  onChange={e => setDepositMnemonicDraft(e.target.value)}

                />

              </label>

              <label className="auth-remember">

                <input type="checkbox" checked={depositBackfillDraft} onChange={e => setDepositBackfillDraft(e.target.checked)} />

                {t('admin.depositBackfillToggle')}

              </label>

              <div className="flex-gap-sm">

                <button className="btn btn-primary btn-sm" type="submit" disabled={!depositMnemonicDraft.trim()}>{t('common.save')}</button>

                {depositWalletSettings?.source === 'runtime' && (

                  <button className="btn btn-ghost btn-sm" type="button" onClick={clearDepositWalletSettings}>{t('admin.depositMnemonicClear')}</button>

                )}

              </div>

            </form>

          </GlassCard>

        </>

      )}



      {section === 'cold' && (

        <>

          <WalletUpdatedAt overview={walletOverview} loading={walletOverviewLoading} onRefresh={refreshWalletOverview} />

          <RoleGuide

            title={t('admin.walletHub.roles.cold.title')}

            desc={t('admin.walletHub.roles.cold.desc')}

            bullets={[t('admin.walletHub.roles.cold.b1'), t('admin.walletHub.roles.cold.b2'), t('admin.walletHub.roles.cold.b3')]}

          />

          <p className="text-muted text-sm section-mb-sm wallet-rpc-dep-note">

            {t('admin.chainRpcDepNote')}{' '}

            <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSection('rpc')}>

              {t('admin.chainRpcGoConfigure')}

            </button>

          </p>

          <WalletSetupGuide guide="cold" />

          <GlassCard className="p-0 section-mb-lg">

            <div className="card-section-head"><h3 className="panel-title-sm">{t('admin.walletHub.coldBalances')}</h3></div>

            <WalletBalanceTable rows={walletOverview?.cold_wallets || []} />

          </GlassCard>

          <GlassCard className="p-6 section-mb-lg page-panel-narrow">

            <h3 className="panel-title-sm mb-md">{t('admin.sweepTitle')}</h3>

            <p className="text-muted text-sm section-mb-sm">{t('admin.sweepHint')}</p>

            {sweepSettings && (

              <p className={`text-xs section-mb-sm ${(sweepSettings.ready_chains || []).length ? 'text-green' : 'text-muted'}`}>

                {t('admin.sweepReady', { chains: (sweepSettings.ready_chains || []).join(', ') || '—' })}

              </p>

            )}

            <form onSubmit={saveSweepSettings} className="form-stack">

              <label className="auth-remember">

                <input type="checkbox" checked={sweepAutoDraft} onChange={e => setSweepAutoDraft(e.target.checked)} />

                {t('admin.sweepAutoToggle')}

              </label>

              <label className="auth-remember">

                <input type="checkbox" checked={sweepRequireMatched} onChange={e => setSweepRequireMatched(e.target.checked)} />

                {t('admin.sweepRequireMatched')}

              </label>

              <label className="form-field">

                <span className="text-muted text-sm">{t('admin.sweepMinUsdt')}</span>

                <input className="input" type="number" step="0.01" min="0.01" value={sweepMinDraft} onChange={e => setSweepMinDraft(e.target.value)} />

              </label>

              {PAYOUT_CHAINS.map(chain => (

                <label key={`cold-${chain}`} className="form-field">

                  <span className="text-muted text-sm">{t('admin.sweepColdPh', { chain })}</span>

                  <input className="input input-mono" placeholder={sweepSettings?.cold_wallets?.[chain] || ''}

                    value={sweepColdDraft[chain] || ''}

                    onChange={e => setSweepColdDraft((d: Record<string, string>) => ({ ...d, [chain]: e.target.value }))} />

                </label>

              ))}

              <p className="text-muted text-xs">{t('admin.sweepGasHint')}</p>

              <WalletSetupGuide guide="gas" />

              {PAYOUT_CHAINS.map(chain => (

                <label key={`gas-${chain}`} className="form-field">

                  <span className="text-muted text-sm">{t('admin.sweepGasPh', { chain })}</span>

                  <input className="input input-mono" type="password" autoComplete="new-password"

                    placeholder={sweepSettings?.gas_funder_configured?.[chain] ? t('admin.payoutKeyConfigured') : t('admin.payoutKeyMissing')}

                    value={sweepGasDraft[chain] || ''}

                    onChange={e => setSweepGasDraft((d: Record<string, string>) => ({ ...d, [chain]: e.target.value }))} />

                </label>

              ))}

              <div className="flex-gap-sm">

                <button className="btn btn-primary btn-sm" type="submit">{t('common.save')}</button>

                <button className="btn btn-ghost btn-sm" type="button" onClick={runSweepNow}>{t('admin.sweepRunNow')}</button>

              </div>

            </form>

          </GlassCard>

          {sweepLogs.length > 0 && (

            <GlassCard className="p-0 table-wrap section-mb-lg">

              <div className="card-section-head"><h3 className="panel-title-sm">{t('admin.sweepLogTitle')}</h3></div>

              <table className="data-table data-table-sm">

                <thead>

                  <tr>

                    <th>{t('common.time')}</th>

                    <th>{t('admin.cols.uid')}</th>

                    <th>{t('common.chain')}</th>

                    <th>{t('admin.cols.amount')}</th>

                    <th>{t('common.status')}</th>

                    <th>{t('admin.cols.txHash')}</th>

                  </tr>

                </thead>

                <tbody>

                  {sweepLogs.map((l: any) => (

                    <tr key={l.id}>

                      <td>{new Date(l.created_at).toLocaleString()}</td>

                      <td>{l.user_uid || `#${l.user_id}`}</td>

                      <td>{l.chain}</td>

                      <td>${l.amount?.toFixed(2)}</td>

                      <td><span className={`badge ${l.status === 'success' ? 'badge-green' : l.status === 'failed' ? 'badge-red' : 'badge-gray'}`}>{l.status}</span></td>

                      <td className="mono-cell cell-ellipsis" title={l.sweep_tx_hash}>{l.sweep_tx_hash?.slice(0, 14) || '—'}…</td>

                    </tr>

                  ))}

                </tbody>

              </table>

            </GlassCard>

          )}

        </>

      )}



      {section === 'hot' && (

        <>

          <WalletUpdatedAt overview={walletOverview} loading={walletOverviewLoading} onRefresh={refreshWalletOverview} />

          <RoleGuide

            title={t('admin.walletHub.roles.hot.title')}

            desc={t('admin.walletHub.roles.hot.desc')}

            bullets={[t('admin.walletHub.roles.hot.b1'), t('admin.walletHub.roles.hot.b2'), t('admin.walletHub.roles.hot.b3')]}

          />

          <p className="text-muted text-sm section-mb-sm wallet-rpc-dep-note">

            {t('admin.chainRpcDepNote')}{' '}

            <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSection('rpc')}>

              {t('admin.chainRpcGoConfigure')}

            </button>

          </p>

          <WalletSetupGuide guide="hot" />

          <GlassCard className="p-0 section-mb-lg">

            <div className="card-section-head"><h3 className="panel-title-sm">{t('admin.walletHub.hotBalances')}</h3></div>

            <WalletBalanceTable rows={walletOverview?.hot_wallets || []} />

          </GlassCard>

          <GlassCard className="p-0 section-mb-lg">

            <div className="card-section-head"><h3 className="panel-title-sm">{t('admin.walletHub.gasBalances')}</h3></div>

            <WalletBalanceTable rows={walletOverview?.gas_funders || []} />

          </GlassCard>

          <GlassCard className="p-6 section-mb-lg page-panel-narrow">

            <h3 className="panel-title-sm mb-md">{t('admin.payoutWalletTitle')}</h3>

            <p className="text-muted text-sm section-mb-sm">{t('admin.payoutWalletHint')}</p>

            <form onSubmit={savePayoutSettings} className="form-stack">

              <label className="auth-remember">

                <input type="checkbox" checked={payoutAutoDraft} onChange={e => setPayoutAutoDraft(e.target.checked)} />

                {t('admin.payoutAutoToggle')}

              </label>

              {PAYOUT_CHAINS.map(chain => (

                <label key={chain} className="form-field">

                  <span className="text-muted text-sm flex-between-wrap">

                    <span>{chain}</span>

                    <span className={payoutSettings?.chains?.[chain] ? 'text-green text-xs' : 'text-muted text-xs'}>

                      {payoutSettings?.chains?.[chain] ? t('admin.payoutKeyConfigured') : t('admin.payoutKeyMissing')}

                    </span>

                  </span>

                  <input className="input input-mono" type="password" autoComplete="new-password"

                    placeholder={t('admin.payoutKeyPh', { chain })}

                    value={payoutKeyDraft[chain] || ''}

                    onChange={e => setPayoutKeyDraft((d: Record<string, string>) => ({ ...d, [chain]: e.target.value }))} />

                </label>

              ))}

              <button className="btn btn-primary btn-sm" type="submit">{t('common.save')}</button>

            </form>

          </GlassCard>

        </>

      )}



      {section === 'platform' && (

        <>

          <WalletUpdatedAt overview={walletOverview} loading={walletOverviewLoading} onRefresh={refreshWalletOverview} />

          <RoleGuide

            title={t('admin.walletHub.roles.platform.title')}

            desc={t('admin.walletHub.roles.platform.desc')}

            bullets={[t('admin.walletHub.roles.platform.b1'), t('admin.walletHub.roles.platform.b2')]}

          />

          <WalletSetupGuide guide="platform" />

          <GlassCard className="p-0 section-mb-lg">

            <div className="card-section-head"><h3 className="panel-title-sm">{t('admin.walletHub.platformBalances')}</h3></div>

            <WalletBalanceTable

              rows={(walletOverview?.platform_addresses || []).map((p: any) => ({

                ...p,

                label: p.label,

              }))}

              showLabel

            />

          </GlassCard>

          <GlassCard className="p-6 section-mb-lg page-panel-narrow">

            <h3 className="panel-title-sm mb-md">{t('admin.addUsdtAddr')}</h3>

            <p className="text-muted text-sm section-mb-sm">{t('admin.addrQrHint')}</p>

            <form onSubmit={addAddr} className="form-stack">

              <select className="input" value={newAddr.chain} onChange={e => setNewAddr({ ...newAddr, chain: e.target.value })}>

                {['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL'].map(c => <option key={c}>{c}</option>)}

              </select>

              <input className="input" placeholder={t('admin.addrLabelPh')} value={newAddr.label} onChange={e => setNewAddr({ ...newAddr, label: e.target.value })} />

              <input className="input" placeholder={t('admin.usdtAddrPh')} value={newAddr.address} onChange={e => setNewAddr({ ...newAddr, address: e.target.value })} required />

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

                    <img className="deposit-qr-preview section-mb-xs" src={`${adminApi.depositAddressQrUrl(editingAddr.id)}?t=${Date.now()}`} alt={t('admin.walletQr')} />

                  )}

                  <input ref={editQrRef} className="input" type="file" accept="image/png,image/jpeg,image/webp,image/gif"

                    onChange={e => { const file = e.target.files?.[0]; if (file) uploadAddrQr(editingAddr.id, file); e.target.value = '' }} />

                  {editingAddr.has_qr && (

                    <button className="btn btn-ghost btn-sm section-mt-xs" type="button" onClick={() => removeAddrQr(editingAddr.id)}>{t('admin.qrRemove')}</button>

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

                      <input ref={el => { rowQrRefs.current[a.id] = el }} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="sr-only"

                        onChange={e => { onPickQr(a.id, e.target.files?.[0]); e.target.value = '' }} />

                      <button className="btn btn-ghost btn-xs" type="button" onClick={() => rowQrRefs.current[a.id]?.click()}>

                        {a.has_qr ? t('admin.qrReplace') : t('admin.qrUpload')}

                      </button>

                      {a.has_qr && <button className="btn btn-ghost btn-xs" type="button" onClick={() => removeAddrQr(a.id)}>{t('admin.qrRemove')}</button>}

                      <button className="btn btn-ghost btn-xs" type="button" onClick={() => setEditingAddr({ ...a })}>{t('common.edit')}</button>

                      <button className="btn btn-ghost btn-xs" onClick={() => adminApi.toggleDepositAddress(a.id).then(load)}>{t('common.toggle')}</button>

                      <button className="btn btn-ghost btn-xs" onClick={() => adminApi.deleteDepositAddress(a.id).then(load)}>{t('common.delete')}</button>

                    </td>

                  </tr>

                ))}

              </tbody>

            </table>

          </GlassCard>

        </>

      )}



      {section === 'withdraw' && (

        <>

          <RoleGuide

            title={t('admin.walletHub.roles.withdraw.title')}

            desc={t('admin.walletHub.roles.withdraw.desc')}

            bullets={[t('admin.walletHub.roles.withdraw.b1'), t('admin.walletHub.roles.withdraw.b2')]}

          />

          <GlassCard className="p-6 section-mb-lg page-panel-narrow">

            <h3 className="panel-title-sm mb-md">{t('admin.withdrawThresholdTitle')}</h3>

            <p className="text-muted text-sm section-mb-sm">{t('admin.withdrawThresholdHint')}</p>

            <form onSubmit={saveWithdrawThresholds} className="form-stack">

              <div className="grid-2-col-gap">

                <label className="form-field">

                  <span className="text-muted text-sm">{t('admin.instantMaxUsd')}</span>

                  <input className="input" type="number" step="1" min="1" value={thresholdDraft.auto_max_usd}

                    onChange={e => setThresholdDraft((d: any) => ({ ...d, auto_max_usd: e.target.value }))} required />

                </label>

                <label className="form-field">

                  <span className="text-muted text-sm">{t('admin.reviewMinUsd')}</span>

                  <input className="input" type="number" step="1" min="1" value={thresholdDraft.review_min_usd}

                    onChange={e => setThresholdDraft((d: any) => ({ ...d, review_min_usd: e.target.value }))} required />

                </label>

              </div>

              {withdrawThresholds && (

                <p className="text-muted text-xs">

                  {t('admin.withdrawThresholdCurrent', { instant: withdrawThresholds.auto_max_usd, review: withdrawThresholds.review_min_usd })}

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

        </>

      )}



      {section === 'rpc' && (

        <>

          <RoleGuide

            title={t('admin.chainRpcTitle')}

            desc={t('admin.chainRpcHint')}

            bullets={[t('admin.chainRpcB1'), t('admin.chainRpcB2'), t('admin.chainRpcB3')]}

          />

          <WalletSetupGuide guide="rpc" />

          <GlassCard className="p-4 section-mb-md">

            <h4 className="wallet-setup-title">{t('admin.chainRpcMonitorTitle')}</h4>

            <ul className="wallet-setup-list section-mt-xs">

              {[1, 2, 3, 4].map(n => (

                <li key={n}>{t(`admin.chainRpcMonitor${n}`)}</li>

              ))}

            </ul>

          </GlassCard>

          <GlassCard className="p-4 section-mb-md">

            <div className="flex-between-wrap section-mb-sm">

              <div>

                <h4 className="wallet-setup-title">{t('admin.chainRpcStatusTitle')}</h4>

                <p className="text-muted text-xs section-mt-xs">{t('admin.chainRpcStatusHint')}</p>

              </div>

              <WalletUpdatedAt overview={walletOverview} loading={walletOverviewLoading} onRefresh={refreshWalletOverview} />

            </div>

            <div className="table-wrap">

              <table className="data-table data-table-sm">

                <thead>

                  <tr>

                    <th>{t('common.chain')}</th>

                    <th>{t('admin.walletHub.cols.rpc')}</th>

                    <th>{t('admin.chainRpcColSource')}</th>

                  </tr>

                </thead>

                <tbody>

                  {PAYOUT_CHAINS.map(chain => {

                    const rpcReady = chain === 'TRC20'

                      ? chainRpcSettings?.tron_api_url_configured

                      : chainRpcSettings?.chains?.[chain]?.configured

                    const src = chain === 'TRC20'

                      ? chainRpcSettings?.tron_source

                      : chainRpcSettings?.chains?.[chain]?.source

                    const srcLabel = src === 'runtime'

                      ? t('admin.depositSourceRuntime')

                      : src === 'env'

                        ? t('admin.depositSourceEnv')

                        : '—'

                    const liveRpc = walletOverview?.rpc_status?.[chain]

                    return (

                      <tr key={chain}>

                        <td><span className="badge badge-green">{chain}</span></td>

                        <td>

                          <span className={`badge ${(liveRpc ?? rpcReady) ? 'badge-green' : 'badge-gray'}`}>

                            {(liveRpc ?? rpcReady) ? t('admin.walletHub.rpcOk') : t('admin.walletHub.rpcFail')}

                          </span>

                        </td>

                        <td className="text-xs text-muted">{srcLabel}</td>

                      </tr>

                    )

                  })}

                </tbody>

              </table>

            </div>

          </GlassCard>

          <GlassCard className="p-6 section-mb-lg page-panel-narrow">

            <h3 className="panel-title-sm mb-md">{t('admin.chainRpcTitle')}</h3>

            <p className="text-muted text-sm section-mb-sm">{t('admin.chainRpcFormHint')}</p>

            <form onSubmit={saveChainRpcSettings} className="form-stack">

              {EVM_RPC_CHAINS.map(chain => (

                <label key={chain} className="form-field">

                  <span className="text-muted text-sm flex-between-wrap">

                    <span>{chain} RPC</span>

                    <span className={`text-xs ${chainRpcSettings?.chains?.[chain]?.configured ? 'text-green' : 'text-muted'}`}>

                      {chainRpcSettings?.chains?.[chain]?.configured

                        ? `${t('admin.chainRpcSource', { source: chainRpcSettings.chains[chain].source === 'runtime' ? t('admin.depositSourceRuntime') : t('admin.depositSourceEnv') })} · ${chainRpcSettings.chains[chain].preview}`

                        : t('admin.chainRpcMissing')}

                    </span>

                  </span>

                  <input className="input input-mono" placeholder={t('admin.chainRpcPh', { chain })}

                    value={chainRpcDraft[chain] || ''}

                    onChange={e => setChainRpcDraft((d: Record<string, string>) => ({ ...d, [chain]: e.target.value }))} />

                </label>

              ))}

              <label className="form-field">

                <span className="text-muted text-sm flex-between-wrap">

                  <span>TRC20 {t('admin.chainRpcTronUrl')}</span>

                  <span className={`text-xs ${chainRpcSettings?.tron_api_url_configured ? 'text-green' : 'text-muted'}`}>

                    {chainRpcSettings?.tron_api_url_configured

                      ? `${t('admin.chainRpcSource', { source: chainRpcSettings?.tron_source === 'runtime' ? t('admin.depositSourceRuntime') : t('admin.depositSourceEnv') })} · ${chainRpcSettings?.tron_api_url_preview || ''}`

                      : t('admin.chainRpcMissing')}

                  </span>

                </span>

                <input className="input input-mono" placeholder="https://api.trongrid.io"

                  value={chainRpcDraft.tron_api_url || ''}

                  onChange={e => setChainRpcDraft((d: Record<string, string>) => ({ ...d, tron_api_url: e.target.value }))} />

              </label>

              <label className="form-field">

                <span className="text-muted text-sm">TRC20 {t('admin.chainRpcTronKey')}</span>

                <input className="input input-mono" type="password" autoComplete="new-password"

                  placeholder={chainRpcSettings?.tron_api_key_configured ? t('admin.payoutKeyConfigured') : t('admin.payoutKeyMissing')}

                  value={chainRpcDraft.tron_api_key || ''}

                  onChange={e => setChainRpcDraft((d: Record<string, string>) => ({ ...d, tron_api_key: e.target.value }))} />

              </label>

              <div className="flex-gap-sm">

                <button className="btn btn-primary btn-sm" type="submit">{t('common.save')}</button>

                {chainRpcSettings?.has_runtime && (

                  <button className="btn btn-ghost btn-sm" type="button" onClick={clearChainRpcSettings}>{t('admin.chainRpcClear')}</button>

                )}

              </div>

            </form>

          </GlassCard>

        </>

      )}



      {section === 'dingtalk' && (

        <>

          <RoleGuide

            title={t('admin.dingtalkSettingsTitle')}

            desc={t('admin.dingtalkSettingsHint')}

            bullets={[t('admin.dingtalkBullet1'), t('admin.dingtalkBullet2')]}

          />

          <GlassCard className="p-6 section-mb-lg page-panel-narrow">

            <h3 className="panel-title-sm mb-md">{t('admin.dingtalkSettingsTitle')}</h3>

            <p className={`text-xs section-mb-sm ${dingtalkSettings?.configured ? 'text-green' : 'text-muted'}`}>

              {dingtalkSettings?.configured

                ? `${t('admin.dingtalkConfigured')}${dingtalkSettings.source ? ` (${dingtalkSettings.source === 'runtime' ? t('admin.depositSourceRuntime') : t('admin.depositSourceEnv')})` : ''}`

                : t('admin.dingtalkMissing')}

            </p>

            <form onSubmit={saveDingtalkSettings} className="form-stack">

              <input className="input" placeholder={t('admin.dingtalkWebhookPh')} value={dingtalkDraft.webhook}

                onChange={e => setDingtalkDraft((d: { webhook: string; secret: string }) => ({ ...d, webhook: e.target.value }))} />

              <input className="input" type="password" autoComplete="new-password" placeholder={t('admin.dingtalkSecretPh')}

                value={dingtalkDraft.secret} onChange={e => setDingtalkDraft((d: { webhook: string; secret: string }) => ({ ...d, secret: e.target.value }))} />

              <button className="btn btn-primary btn-sm" type="submit" disabled={!dingtalkDraft.webhook.trim()}>{t('common.save')}</button>

            </form>

          </GlassCard>

        </>

      )}

    </div>

  )

}


