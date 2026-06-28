import { useEffect, useState, useMemo } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import { walletApi } from '../api'
import DualVerifyFields from '../components/DualVerifyFields'
import { useI18n, localeDate } from '../i18n'
import { Star, Trash2 } from 'lucide-react'

export default function Withdraw() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const [account, setAccount] = useState<any>(null)
  const [settings, setSettings] = useState<any>(null)
  const [withdrawals, setWithdrawals] = useState<any[]>([])
  const [savedAddrs, setSavedAddrs] = useState<any[]>([])
  const [transfers, setTransfers] = useState<any[]>([])
  const [selectedAddrId, setSelectedAddrId] = useState<number | ''>('')
  const [amount, setAmount] = useState('')
  const [feePreview, setFeePreview] = useState<any>(null)
  const [msg, setMsg] = useState('')
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
    setMsg('')
    try {
      const res = await walletApi.withdraw(
        parseFloat(amount), withdrawPwd, wdEmailCode, wdPhoneCode, Number(selectedAddrId)
      )
      setMsg(t('withdraw.withdrawSubmitted', {
        gross: res.amount?.toFixed(2),
        fee: res.network_fee?.toFixed(2),
        net: res.amount_net?.toFixed(2),
      }))
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
      setMsg(t('withdraw.bindSuccess'))
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
    setMsg('')
    try {
      const res = await walletApi.transfer(transferRecipient.trim(), parseFloat(transferAmount), transferNote)
      setMsg(t('withdraw.transferSuccess', { name: res.to_display_name, amount: res.amount.toFixed(2) }))
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

  return (
    <Layout>
      <PageHeader title={t('withdraw.title')} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 16, marginBottom: 24 }}>
        <StatCard label={t('withdraw.balance')} value={`$${(account?.balance || 0).toFixed(2)}`} />
        <StatCard label={t('withdraw.totalEarned')} value={`$${(account?.total_earned || 0).toFixed(2)}`} />
        <StatCard label={t('withdraw.totalWithdrawn')} value={`$${(account?.total_withdrawn || 0).toFixed(2)}`} />
      </div>

      {msg && <p className="text-green" style={{ marginBottom: 16 }}>{msg}</p>}
      {error && <p className="text-red" style={{ marginBottom: 16 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {[
          { k: 'withdraw' as const, l: t('withdraw.tabWithdraw') },
          { k: 'addressbook' as const, l: t('withdraw.tabAddress') },
          { k: 'transfer' as const, l: t('withdraw.tabTransfer') },
        ].map(item => (
          <button key={item.k} className={`btn ${tab === item.k ? 'btn-primary' : 'btn-ghost'}`} onClick={() => { setTab(item.k); setError(''); setMsg('') }}>{item.l}</button>
        ))}
      </div>

      {tab === 'withdraw' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <GlassCard green className="p-6">
            <h3 style={{ fontSize: 15, marginBottom: 16 }}>{t('withdraw.applyTitle')}</h3>
            {savedAddrs.length === 0 ? (
              <p className="text-muted" style={{ fontSize: 14 }}>{t('withdraw.bindAddrFirst')}</p>
            ) : (
              <form onSubmit={handleWithdraw}>
                <div style={{ marginBottom: 12 }}>
                  <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>{t('withdraw.selectAddrBook')}</label>
                  <select className="input" value={selectedAddrId} onChange={e => setSelectedAddrId(Number(e.target.value))}>
                    {savedAddrs.map(a => (
                      <option key={a.id} value={a.id}>
                        [{addrTypeLabel(a.address_type)}] {a.source_name || a.label} · {a.chain} · {a.address.slice(0, 10)}...
                      </option>
                    ))}
                  </select>
                </div>
                {selectedAddr && (
                  <div style={{ padding: 12, marginBottom: 12, borderRadius: 8, background: 'rgba(255,255,255,0.03)', fontSize: 12 }}>
                    <p><span className="text-muted">{t('withdraw.chainLabel')}</span> <span className="badge badge-green">{selectedAddr.chain}</span></p>
                    <p style={{ marginTop: 6, wordBreak: 'break-all', fontFamily: 'monospace' }}>{selectedAddr.address}</p>
                    <p className="text-muted" style={{ marginTop: 6 }}>{t('withdraw.networkFee')} ${feeMap[selectedAddr.chain] ?? '?'}</p>
                  </div>
                )}
                <div style={{ marginBottom: 16 }}>
                  <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>{t('withdraw.amountLabel')}</label>
                  <input className="input" type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} required />
                </div>
                {feePreview && (
                  <div style={{ padding: 12, marginBottom: 16, borderRadius: 8, background: 'rgba(0,176,80,0.08)', fontSize: 13 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>{t('withdraw.deductBalance')}</span><span>${feePreview.gross_amount?.toFixed(2)}</span></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}><span className="text-muted">{t('withdraw.networkFeeLabel')}</span><span>-${feePreview.network_fee?.toFixed(2)}</span></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontWeight: 600 }}><span>{t('withdraw.netReceive')}</span><span className="text-green">${feePreview.amount_net?.toFixed(2)}</span></div>
                  </div>
                )}
                <input className="input" type="password" placeholder={t('withdraw.withdrawPwdPh')} value={withdrawPwd}
                  onChange={e => setWithdrawPwd(e.target.value)} style={{ marginBottom: 12 }} required />
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
            <h3 style={{ fontSize: 15, marginBottom: 12 }}>{t('withdraw.feeTableTitle')}</h3>
            <table className="data-table" style={{ fontSize: 13 }}>
              <thead><tr><th>{t('withdraw.feeTableChain')}</th><th>{t('withdraw.feeTableFee')}</th></tr></thead>
              <tbody>
                {Object.entries(feeMap).map(([c, f]) => (
                  <tr key={c}><td><span className="badge badge-gray">{c}</span></td><td>${(f as number).toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="text-muted" style={{ fontSize: 11, marginTop: 12 }}>{t('withdraw.feeTableNote')}</p>
          </GlassCard>
        </div>
      )}

      {tab === 'addressbook' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <GlassCard green className="p-6">
            <h3 style={{ fontSize: 15, marginBottom: 16 }}>{t('withdraw.bindTitle')}</h3>
            <form onSubmit={handleBindAddress}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                <button type="button" className={`btn ${bindType === 'exchange' ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ flex: 1, fontSize: 12 }} onClick={() => { setBindType('exchange'); setBindSource('Binance') }}>{t('withdraw.exchange')}</button>
                <button type="button" className={`btn ${bindType === 'wallet' ? 'btn-primary' : 'btn-ghost'}`}
                  style={{ flex: 1, fontSize: 12 }} onClick={() => { setBindType('wallet'); setBindSource('MetaMask') }}>{t('withdraw.wallet')}</button>
              </div>
              <select className="input" value={bindSource} onChange={e => setBindSource(e.target.value)} style={{ marginBottom: 8 }}>
                {(bindType === 'exchange' ? exchangeSources : walletSources).map((s: string) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <select className="input" value={bindChain} onChange={e => setBindChain(e.target.value)} style={{ marginBottom: 8 }}>
                {chains.map((c: string) => <option key={c}>{c}</option>)}
              </select>
              <input className="input" placeholder={t('withdraw.addrPh')} value={bindAddress} onChange={e => setBindAddress(e.target.value)} required style={{ marginBottom: 8 }} />
              <input className="input" placeholder={t('withdraw.labelPh')} value={bindLabel} onChange={e => setBindLabel(e.target.value)} style={{ marginBottom: 8 }} />
              <input className="input" placeholder={t('withdraw.memoPh')} value={bindMemo} onChange={e => setBindMemo(e.target.value)} style={{ marginBottom: 12 }} />
              <DualVerifyFields
                emailCode={bindEmailCode} phoneCode={bindPhoneCode}
                onEmailCode={setBindEmailCode} onPhoneCode={setBindPhoneCode}
                devEmail={devEmail} devPhone={devPhone}
                onDevCodes={(e, p) => { setDevEmail(e || ''); setDevPhone(p || '') }}
              />
              <button className="btn btn-primary" type="submit">{t('withdraw.bindBtn')}</button>
            </form>
          </GlassCard>

          <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
              <h3 style={{ fontSize: 15 }}>{t('withdraw.addrBookTitle')} ({savedAddrs.length})</h3>
            </div>
            {savedAddrs.length === 0 ? (
              <p className="text-muted" style={{ padding: 32, textAlign: 'center' }}>{t('withdraw.noAddr')}</p>
            ) : savedAddrs.map(a => (
              <div key={a.id} style={{
                padding: '14px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)',
                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12,
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {a.is_default && <Star size={14} className="text-green" fill="var(--accent)" />}
                    <span className="badge badge-green">{a.chain}</span>
                    <span className="badge badge-gray">{addrTypeLabel(a.address_type)}</span>
                    <span style={{ fontSize: 13 }}>{a.source_name || a.label}</span>
                  </div>
                  <p style={{ fontSize: 12, marginTop: 8, wordBreak: 'break-all', fontFamily: 'monospace' }}>{a.address}</p>
                  {a.memo && <p className="text-muted" style={{ fontSize: 11, marginTop: 4 }}>Memo: {a.memo}</p>}
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {!a.is_default && (
                    <button className="btn btn-ghost" style={{ padding: '4px 8px', fontSize: 11 }}
                      onClick={() => walletApi.setDefaultAddress(a.id).then(load)}>{t('withdraw.defaultBtn')}</button>
                  )}
                  <button className="btn btn-ghost" style={{ padding: '4px 8px' }}
                    onClick={async () => {
                      const ec = window.prompt(t('withdraw.emailCodePrompt'))
                      const pc = window.prompt(t('withdraw.phoneCodePrompt'))
                      if (!ec || !pc) return
                      try {
                        await walletApi.deleteWithdrawAddress(a.id, ec, pc)
                        load()
                      } catch (err: any) {
                        setError(err.response?.data?.detail || t('withdraw.deleteFail'))
                      }
                    }}><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </GlassCard>
        </div>
      )}

      {tab === 'transfer' && (
        <GlassCard green className="p-6" style={{ maxWidth: 560 }}>
          <h3 style={{ fontSize: 15, marginBottom: 8 }}>{t('withdraw.transferTitle')}</h3>
          <p className="text-green" style={{ fontSize: 13, marginBottom: 16 }}>{t('withdraw.transferHint')}</p>
          <form onSubmit={handleTransfer}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, marginBottom: 12 }}>
              <input className="input" value={transferRecipient} onChange={e => setTransferRecipient(e.target.value)}
                placeholder={t('withdraw.recipientPh')} required />
              <button type="button" className="btn btn-ghost" onClick={lookupRecipient}>{t('withdraw.lookup')}</button>
            </div>
            {transferPreview && (
              <div style={{ padding: 10, marginBottom: 12, borderRadius: 8, background: 'rgba(0,176,80,0.08)', fontSize: 13 }}>
                {t('withdraw.recipientLabel')}：<span className="text-green">{transferPreview.display_name}</span>
                <span className="text-muted" style={{ marginLeft: 8 }}>UID: {transferPreview.uid}</span>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
              <input className="input" type="number" step="0.01" value={transferAmount} onChange={e => setTransferAmount(e.target.value)} placeholder={t('withdraw.transferAmountPh')} required />
              <input className="input" value={transferNote} onChange={e => setTransferNote(e.target.value)} placeholder={t('withdraw.notePh')} />
            </div>
            <button className="btn btn-primary" type="submit">{t('withdraw.confirmTransfer')}</button>
          </form>
        </GlassCard>
      )}

      <GlassCard className="p-0" style={{ overflow: 'hidden', marginTop: 24 } as any}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}><h3 style={{ fontSize: 15 }}>{t('withdraw.historyTitle')}</h3></div>
        <table className="data-table">
          <thead><tr><th>{t('common.time')}</th><th>{t('common.chain')}</th><th>{t('admin.cols.detail')}</th><th>{t('admin.cols.fee')}</th><th>{t('admin.cols.received')}</th><th>{t('common.status')}</th></tr></thead>
          <tbody>
            {withdrawals.length === 0 ? (
              <tr><td colSpan={6} className="text-muted" style={{ textAlign: 'center', padding: 32 }}>{t('withdraw.emptyHistory')}</td></tr>
            ) : withdrawals.map(w => (
              <tr key={w.id}>
                <td>{localeDate(w.created_at, locale)}</td>
                <td><span className="badge badge-gray">{w.chain}</span></td>
                <td>${w.amount?.toFixed(2)}</td>
                <td className="text-muted">${(w.network_fee ?? 0).toFixed(2)}</td>
                <td className="text-green">${(w.amount_net ?? w.amount)?.toFixed(2)}</td>
                <td><span className={`badge ${w.status === 'completed' ? 'badge-green' : 'badge-gray'}`}>{wStatus(w.status)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      <style>{`@media (max-width: 768px) { div[style*="grid-template-columns: 1fr 1fr"] { grid-template-columns: 1fr !important; } }`}</style>
    </Layout>
  )
}
