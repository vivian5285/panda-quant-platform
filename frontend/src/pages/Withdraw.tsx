import { useEffect, useState, useMemo } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import { walletApi } from '../api'
import DualVerifyFields from '../components/DualVerifyFields'
import { useI18n, localeDate } from '../i18n'
import { toast } from '../store/toast'
import { Star, Trash2 } from 'lucide-react'

export default function Withdraw() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [account, setAccount] = useState<any>(null)
  const [settings, setSettings] = useState<any>(null)
  const [withdrawals, setWithdrawals] = useState<any[]>([])
  const [savedAddrs, setSavedAddrs] = useState<any[]>([])
  const [transfers, setTransfers] = useState<any[]>([])
  const [rewardLedger, setRewardLedger] = useState<any[]>([])
  const [selectedAddrId, setSelectedAddrId] = useState<number | ''>('')
  const [amount, setAmount] = useState('')
  const [feePreview, setFeePreview] = useState<any>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'withdraw' | 'addressbook' | 'transfer'>('withdraw')

  const [bindType, setBindType] = useState<'exchange' | 'wallet'>('exchange')
  const [bindChain, setBindChain] = useState('TRC20')
  const [bindSource, setBindSource] = useState('Binance')
  const [bindAddress, setBindAddress] = useState('')
  const [bindLabel, setBindLabel] = useState('')
  const [bindMemo, setBindMemo] = useState('')

  const [transferRecipient, setTransferRecipient] = useState('')
  const [transferAmount, setTransferAmount] = useState('')
  const [transferNote, setTransferNote] = useState('')
  const [transferPreview, setTransferPreview] = useState<any>(null)

  const [bindEmailCode, setBindEmailCode] = useState('')
  const [bindPhoneCode, setBindPhoneCode] = useState('')
  const [withdrawPwd, setWithdrawPwd] = useState('')
  const [wdEmailCode, setWdEmailCode] = useState('')
  const [wdPhoneCode, setWdPhoneCode] = useState('')
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null)
  const [deleteEmailCode, setDeleteEmailCode] = useState('')
  const [deletePhoneCode, setDeletePhoneCode] = useState('')
  const [devEmail, setDevEmail] = useState('')
  const [devPhone, setDevPhone] = useState('')

  const chains = settings?.supported_chains || ['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL']
  const exchangeSources = settings?.exchange_sources || ['Binance', 'OKX', 'Bybit']
  const walletSources = settings?.wallet_sources || ['MetaMask', 'Trust Wallet']

  const selectedAddr = useMemo(
    () => savedAddrs.find(a => a.id === selectedAddrId),
    [savedAddrs, selectedAddrId]
  )

  const load = () => {
    walletApi.rewardAccount().then(setAccount)
    walletApi.withdrawSettings().then(setSettings)
    walletApi.withdrawals().then(setWithdrawals)
    walletApi.withdrawAddresses().then(addrs => {
      setSavedAddrs(addrs)
      const def = addrs.find((a: any) => a.is_default) || addrs[0]
      if (def && !selectedAddrId) setSelectedAddrId(def.id)
    })
    walletApi.transfers().then(setTransfers)
    walletApi.rewardLedger().then(setRewardLedger).catch(() => setRewardLedger([]))
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (selectedAddr && amount && parseFloat(amount) > 0) {
      walletApi.feePreview(selectedAddr.chain, parseFloat(amount)).then(setFeePreview).catch(() => setFeePreview(null))
    } else {
      setFeePreview(null)
    }
  }, [selectedAddr, amount])

  const handleWithdraw = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedAddrId) { setError(t('withdraw.selectAddrError')); return }
    setError('')
    try {
      const res = await walletApi.withdraw(
        parseFloat(amount), withdrawPwd, wdEmailCode, wdPhoneCode, Number(selectedAddrId)
      )
      const amt = parseFloat(amount)
      const reviewMin = settings?.review_min_usd ?? 500
      const autoMax = settings?.auto_max_usd ?? 100
      if (res.status === 'completed' && res.tx_hash) {
        toast.success(t('withdraw.completedInstant', {
          net: res.amount_net?.toFixed(2),
          tx: res.tx_hash.slice(0, 12) + '…',
        }))
      } else if (res.auto_approved || amt <= autoMax) {
        toast.success(t('withdraw.submittedInstant', {
          gross: res.amount?.toFixed(2),
          fee: res.network_fee?.toFixed(2),
          net: res.amount_net?.toFixed(2),
        }))
      } else if (amt >= reviewMin) {
        toast.success(t('withdraw.submittedReview', {
          gross: res.amount?.toFixed(2),
          fee: res.network_fee?.toFixed(2),
          net: res.amount_net?.toFixed(2),
        }))
      } else {
        toast.success(t('withdraw.withdrawSubmitted', {
          gross: res.amount?.toFixed(2),
          fee: res.network_fee?.toFixed(2),
          net: res.amount_net?.toFixed(2),
        }))
      }
      setAmount('')
      load()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('withdraw.withdrawFail'))
    }
  }

  const handleBindAddress = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await walletApi.addWithdrawAddress({
        chain: bindChain,
        address: bindAddress,
        address_type: bindType,
        source_name: bindSource,
        label: bindLabel || bindSource,
        memo: bindMemo || undefined,
        is_default: savedAddrs.length === 0,
        email_code: bindEmailCode,
        phone_code: bindPhoneCode,
      })
      toast.success(t('withdraw.bindSuccess'))
      setBindAddress('')
      setBindLabel('')
      setBindMemo('')
      load()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('withdraw.bindFail'))
    }
  }

  const lookupRecipient = async () => {
    setError('')
    setTransferPreview(null)
    if (!transferRecipient.trim()) return
    try {
      setTransferPreview(await walletApi.lookupRecipient(transferRecipient.trim()))
    } catch (err: any) {
      setError(err.response?.data?.detail || t('withdraw.recipientNotFound'))
    }
  }

  const handleTransfer = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const res = await walletApi.transfer(transferRecipient.trim(), parseFloat(transferAmount), transferNote)
      toast.success(t('withdraw.transferSuccess', { name: res.to_display_name, amount: res.amount.toFixed(2) }))
      setTransferRecipient('')
      setTransferAmount('')
      setTransferNote('')
      setTransferPreview(null)
      load()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('withdraw.transferFail'))
    }
  }

  const feeMap = useMemo(() => {
    const m: Record<string, number> = {}
    settings?.chain_fees?.forEach((f: any) => { m[f.chain] = f.fee_usd })
    return m
  }, [settings])

  const wStatus = (s: string) => t(`admin.wStatus.${s}`) || s
  const addrTypeLabel = (type: string) => type === 'exchange' ? t('withdraw.exchange') : t('withdraw.wallet')

  const confirmDeleteAddress = async () => {
    if (!deleteTargetId) return
    setError('')
    try {
      await walletApi.deleteWithdrawAddress(deleteTargetId, deleteEmailCode, deletePhoneCode)
      setDeleteTargetId(null)
      setDeleteEmailCode('')
      setDeletePhoneCode('')
      load()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('withdraw.deleteFail'))
    }
  }

  return (
    <Layout>
      <PageHeader title={t('withdraw.title')} />

      <div className="stat-grid">
        <StatCard label={t('withdraw.balance')} value={`$${(account?.balance || 0).toFixed(2)}`} />
        <StatCard label={t('withdraw.totalEarned')} value={`$${(account?.total_earned || 0).toFixed(2)}`} />
        <StatCard label={t('withdraw.totalWithdrawn')} value={`$${(account?.total_withdrawn || 0).toFixed(2)}`} />
      </div>

      {error && <p className="text-red form-error-block">{error}</p>}

      <div className="withdraw-tabs">
        {[
          { k: 'withdraw' as const, l: t('withdraw.tabWithdraw') },
          { k: 'addressbook' as const, l: t('withdraw.tabAddress') },
          { k: 'transfer' as const, l: t('withdraw.tabTransfer') },
        ].map(item => (
          <button key={item.k} className={`btn ${tab === item.k ? 'btn-primary' : 'btn-ghost'}`} onClick={() => { setTab(item.k); setError('') }}>{item.l}</button>
        ))}
      </div>

      {tab === 'withdraw' && settings && (
        <GlassCard className="p-4 section-mb-md">
          <p className="text-sm">{t('withdraw.thresholdHint', {
            instant: settings.auto_max_usd,
            review: settings.review_min_usd,
            min: settings.min_usd,
          })}</p>
        </GlassCard>
      )}

      {tab === 'withdraw' && (
        <div className="withdraw-split">
          <GlassCard className="p-6">
            <h3 className="card-heading">{t('withdraw.applyTitle')}</h3>
            {savedAddrs.length === 0 ? (
              <p className="text-muted form-hint">{t('withdraw.bindAddrFirst')}</p>
            ) : (
              <form onSubmit={handleWithdraw} className="form-stack">
                <div>
                  <label className="text-secondary field-label">{t('withdraw.selectAddrBook')}</label>
                  <select className="input" value={selectedAddrId} onChange={e => setSelectedAddrId(Number(e.target.value))}>
                    {savedAddrs.map(a => (
                      <option key={a.id} value={a.id}>
                        [{addrTypeLabel(a.address_type)}] {a.source_name || a.label} · {a.chain} · {a.address.slice(0, 10)}...
                      </option>
                    ))}
                  </select>
                </div>
                {selectedAddr && (
                  <div className="panel-muted panel-muted-spaced">
                    <p><span className="text-muted">{t('withdraw.chainLabel')}</span> <span className="badge badge-green">{selectedAddr.chain}</span></p>
                    <p className="mono-address panel-line-spaced">{selectedAddr.address}</p>
                    <p className="text-muted panel-line-spaced">{t('withdraw.networkFee')} ${feeMap[selectedAddr.chain] ?? '?'}</p>
                  </div>
                )}
                <div>
                  <label className="text-secondary field-label">{t('withdraw.amountLabel')}</label>
                  <input className="input" type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} required />
                </div>
                {feePreview && (
                  <div className="panel-success">
                    <div className="split-row"><span>{t('withdraw.deductBalance')}</span><span>${feePreview.gross_amount?.toFixed(2)}</span></div>
                    <div className="split-row split-row-gap"><span className="text-muted">{t('withdraw.networkFeeLabel')}</span><span>-${feePreview.network_fee?.toFixed(2)}</span></div>
                    <div className="split-row split-row-strong"><span>{t('withdraw.netReceive')}</span><span className="text-green">${feePreview.amount_net?.toFixed(2)}</span></div>
                  </div>
                )}
                <input className="input" type="password" placeholder={t('withdraw.withdrawPwdPh')} value={withdrawPwd}
                  onChange={e => setWithdrawPwd(e.target.value)} required />
                <DualVerifyFields
                  emailCode={wdEmailCode} phoneCode={wdPhoneCode}
                  onEmailCode={setWdEmailCode} onPhoneCode={setWdPhoneCode}
                  devEmail={devEmail} devPhone={devPhone}
                  onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
                />
                <button className="btn btn-primary" type="submit">{t('withdraw.submitWithdraw')}</button>
              </form>
            )}
          </GlassCard>

          <GlassCard className="p-6">
            <h3 className="panel-title-sm mb-md">{t('withdraw.feeTableTitle')}</h3>
            <div className="table-wrap">
            <table className="data-table data-table-sm">
              <thead><tr><th>{t('withdraw.feeTableChain')}</th><th>{t('withdraw.feeTableFee')}</th></tr></thead>
              <tbody>
                {Object.entries(feeMap).map(([c, f]) => (
                  <tr key={c}><td><span className="badge badge-gray">{c}</span></td><td>${(f as number).toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
            </div>
            <p className="text-muted fee-note">{t('withdraw.feeTableNote')}</p>
          </GlassCard>
        </div>
      )}

      {tab === 'addressbook' && (
        <div className="grid-2-col">
          <GlassCard className="p-6">
            <h3 className="panel-title-sm mb-md">{t('withdraw.bindTitle')}</h3>
            <form onSubmit={handleBindAddress} className="form-stack">
              <div className="toggle-btn-row">
                <button type="button" className={`btn ${bindType === 'exchange' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => { setBindType('exchange'); setBindSource('Binance') }}>{t('withdraw.exchange')}</button>
                <button type="button" className={`btn ${bindType === 'wallet' ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => { setBindType('wallet'); setBindSource('MetaMask') }}>{t('withdraw.wallet')}</button>
              </div>
              <select className="input" value={bindSource} onChange={e => setBindSource(e.target.value)}>
                {(bindType === 'exchange' ? exchangeSources : walletSources).map((s: string) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <select className="input" value={bindChain} onChange={e => setBindChain(e.target.value)}>
                {chains.map((c: string) => <option key={c}>{c}</option>)}
              </select>
              <input className="input" placeholder={t('withdraw.addrPh')} value={bindAddress} onChange={e => setBindAddress(e.target.value)} required />
              <input className="input" placeholder={t('withdraw.labelPh')} value={bindLabel} onChange={e => setBindLabel(e.target.value)} />
              <input className="input" placeholder={t('withdraw.memoPh')} value={bindMemo} onChange={e => setBindMemo(e.target.value)} />
              <DualVerifyFields
                emailCode={bindEmailCode} phoneCode={bindPhoneCode}
                onEmailCode={setBindEmailCode} onPhoneCode={setBindPhoneCode}
                devEmail={devEmail} devPhone={devPhone}
                onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
              />
              <button className="btn btn-primary" type="submit">{t('withdraw.bindBtn')}</button>
            </form>
          </GlassCard>

          <GlassCard className="p-0 card-overflow-hidden">
            <div className="card-section-head">
              <h3 className="panel-title-sm">{t('withdraw.addrBookTitle')} ({savedAddrs.length})</h3>
            </div>
            {savedAddrs.length === 0 ? (
              <p className="text-muted empty-state">{t('withdraw.noAddr')}</p>
            ) : savedAddrs.map(a => (
              <div key={a.id} className="list-row-divider list-row-flex">
                <div className="list-row-main">
                  <div className="list-row-meta">
                    {a.is_default && <Star size={14} className="text-green" fill="var(--accent)" />}
                    <span className="badge badge-green">{a.chain}</span>
                    <span className="badge badge-gray">{addrTypeLabel(a.address_type)}</span>
                    <span className="list-row-name">{a.source_name || a.label}</span>
                  </div>
                  <p className="addr-mono">{a.address}</p>
                  {a.memo && <p className="text-muted text-xs mt-xs">{t('withdraw.memoLabel')}: {a.memo}</p>}
                </div>
                <div className="table-actions">
                  {!a.is_default && (
                    <button className="btn btn-ghost btn-compact"
                      onClick={() => walletApi.setDefaultAddress(a.id).then(load)}>{t('withdraw.defaultBtn')}</button>
                  )}
                  <button className="btn btn-ghost btn-compact" type="button"
                    onClick={() => {
                      setDeleteTargetId(a.id)
                      setDeleteEmailCode('')
                      setDeletePhoneCode('')
                    }}><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </GlassCard>

          {deleteTargetId && (
            <GlassCard className="p-6 section-mb-lg page-panel">
              <h3 className="panel-title-sm mb-sm">{t('withdraw.deleteAddrTitle')}</h3>
              <DualVerifyFields
                emailCode={deleteEmailCode}
                phoneCode={deletePhoneCode}
                onEmailCode={setDeleteEmailCode}
                onPhoneCode={setDeletePhoneCode}
                devEmail={devEmail}
                devPhone={devPhone}
                onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
              />
              <div className="flex-gap-sm section-mt-md">
                <button type="button" className="btn btn-danger" onClick={confirmDeleteAddress}>{t('withdraw.confirmDelete')}</button>
                <button type="button" className="btn btn-ghost" onClick={() => setDeleteTargetId(null)}>{t('common.cancel')}</button>
              </div>
            </GlassCard>
          )}
        </div>
      )}

      {tab === 'transfer' && (
        <GlassCard className="p-6 page-panel">
          <h3 className="panel-title-sm mb-sm">{t('withdraw.transferTitle')}</h3>
          <p className="text-muted text-sm section-mb-sm">{t('withdraw.transferHint')}</p>
          <form onSubmit={handleTransfer} className="form-stack">
            <div className="grid-input-action">
              <input className="input" value={transferRecipient} onChange={e => setTransferRecipient(e.target.value)}
                placeholder={t('withdraw.recipientPh')} required />
              <button type="button" className="btn btn-ghost" onClick={lookupRecipient}>{t('withdraw.lookup')}</button>
            </div>
            {transferPreview && (
              <div className="panel-success panel-compact">
                {t('withdraw.recipientLabel')}：<span className="text-green">{transferPreview.display_name}</span>
                <span className="text-muted ml-sm">{t('withdraw.uidLine', { uid: transferPreview.uid })}</span>
              </div>
            )}
            <div className="grid-2-col-gap">
              <input className="input" type="number" step="0.01" value={transferAmount} onChange={e => setTransferAmount(e.target.value)} placeholder={t('withdraw.transferAmountPh')} required />
              <input className="input" value={transferNote} onChange={e => setTransferNote(e.target.value)} placeholder={t('withdraw.notePh')} />
            </div>
            <button className="btn btn-primary" type="submit">{t('withdraw.confirmTransfer')}</button>
          </form>
        </GlassCard>
      )}

      <GlassCard className="p-0 table-wrap card-overflow-hidden section-mt-lg">
        <div className="card-section-head"><h3 className="panel-title-sm">{t('withdraw.rewardLedgerTitle')}</h3></div>
        <table className="data-table data-table-sm">
          <thead><tr><th>{t('common.time')}</th><th>{t('withdraw.ledgerType')}</th><th>{t('admin.cols.detail')}</th><th>{t('withdraw.ledgerBalance')}</th></tr></thead>
          <tbody>
            {rewardLedger.length === 0 ? (
              <tr><td colSpan={4} className="text-muted empty-state">{t('withdraw.emptyLedger')}</td></tr>
            ) : rewardLedger.map(r => (
              <tr key={r.id}>
                <td>{localeDate(r.created_at, locale)}</td>
                <td><span className="badge badge-gray">{r.entry_type}</span></td>
                <td className={r.amount >= 0 ? 'text-green' : 'text-red'}>${r.amount?.toFixed(2)}</td>
                <td>${r.balance_after?.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      {transfers.length > 0 && (
        <GlassCard className="p-0 table-wrap card-overflow-hidden section-mt-lg">
          <div className="card-section-head"><h3 className="panel-title-sm">{t('withdraw.transferHistoryTitle')}</h3></div>
          <table className="data-table data-table-sm">
            <thead><tr><th>{t('common.time')}</th><th>{t('withdraw.recipientLabel')}</th><th>{t('admin.cols.detail')}</th><th>{t('withdraw.notePh')}</th></tr></thead>
            <tbody>
              {transfers.map(tr => (
                <tr key={tr.id}>
                  <td>{localeDate(tr.created_at, locale)}</td>
                  <td>{tr.to_display_name} <span className="text-muted text-xs">({tr.to_uid})</span></td>
                  <td className="text-green">${tr.amount?.toFixed(2)}</td>
                  <td className="cell-ellipsis">{tr.note || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      <GlassCard className="p-0 table-wrap card-overflow-hidden section-mt-lg">
        <div className="card-section-head"><h3 className="panel-title-sm">{t('withdraw.historyTitle')}</h3></div>
        <table className="data-table">
          <thead><tr><th>{t('common.time')}</th><th>{t('common.chain')}</th><th>{t('admin.cols.detail')}</th><th>{t('admin.cols.fee')}</th><th>{t('admin.cols.received')}</th><th>{t('common.status')}</th><th>TxHash</th></tr></thead>
          <tbody>
            {withdrawals.length === 0 ? (
              <tr><td colSpan={7} className="text-muted empty-state">{t('withdraw.emptyHistory')}</td></tr>
            ) : withdrawals.map(w => (
              <tr key={w.id}>
                <td>{localeDate(w.created_at, locale)}</td>
                <td><span className="badge badge-gray">{w.chain}</span></td>
                <td>${w.amount?.toFixed(2)}</td>
                <td className="text-muted">${(w.network_fee ?? 0).toFixed(2)}</td>
                <td className="text-green">${(w.amount_net ?? w.amount)?.toFixed(2)}</td>
                <td>
                  <span className={`badge ${
                    w.status === 'completed' ? 'badge-green'
                    : w.status === 'processing' ? 'badge-yellow'
                    : 'badge-gray'
                  }`}>
                    {w.status === 'completed' && w.admin_note === 'auto_payout'
                      ? t('admin.wStatus.autoCompleted')
                      : wStatus(w.status)}
                  </span>
                </td>
                <td className="mono-address-sm">
                  {w.explorer_url && w.tx_hash ? (
                    <a href={w.explorer_url} target="_blank" rel="noopener noreferrer" className="link-muted">
                      {w.tx_hash.slice(0, 14)}…
                    </a>
                  ) : w.tx_hash ? (
                    <span>{w.tx_hash.slice(0, 14)}…</span>
                  ) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>
    </Layout>
  )
}
