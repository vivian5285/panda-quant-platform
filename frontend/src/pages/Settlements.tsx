import { useEffect, useMemo, useState, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import Layout from '../components/Layout'
import WithdrawCta from '../components/WithdrawCta'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import PendingPerfFeeCard from '../components/PendingPerfFeeCard'
import { referralApi, walletApi } from '../api'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'
import { Copy, Check } from 'lucide-react'
import UserUniqueDepositPanel from '../components/UserUniqueDepositPanel'
import { formatSettlementCycle } from '../utils/settlementCycle'

export default function Settlements() {
  const { t } = useI18n()
  const [searchParams] = useSearchParams()
  const paySectionRef = useRef<HTMLDivElement>(null)
  const [items, setItems] = useState<any[]>([])
  const [addresses, setAddresses] = useState<any[]>([])
  const [myAddresses, setMyAddresses] = useState<any[]>([])
  const [deposits, setDeposits] = useState<any[]>([])
  const [appeals, setAppeals] = useState<any[]>([])
  const [tracking, setTracking] = useState<any>(null)
  const [payingId, setPayingId] = useState<number | null>(null)
  const [appealingId, setAppealingId] = useState<number | null>(null)
  const [appealNote, setAppealNote] = useState('')
  const [chain, setChain] = useState('TRC20')
  const [monitoredChains, setMonitoredChains] = useState<string[]>(['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON'])
  const [txHash, setTxHash] = useState('')
  const [amount, setAmount] = useState('')
  const [copied, setCopied] = useState('')

  const load = () => {
    referralApi.settlements().then(setItems)
    walletApi.depositAddresses().then(setAddresses).catch(() => setAddresses([]))
    walletApi.myDepositAddresses().then(setMyAddresses).catch(() => setMyAddresses([]))
    walletApi.settlementDeposits().then(setDeposits).catch(() => setDeposits([]))
    walletApi.settlementAppeals().then(setAppeals).catch(() => setAppeals([]))
    walletApi.settlementPaymentTracking(true).then(setTracking).catch(() => setTracking(null))
    walletApi.depositChains().then((info: { monitored?: string[] }) => {
      const chains = info?.monitored?.length ? info.monitored : ['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON']
      setMonitoredChains(chains)
      setChain(prev => (chains.includes(prev) ? prev : chains[0]))
    }).catch(() => {})
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  const pendingItem = items.find(s => s.payment_status === 'pending' || s.payment_status === 'paid')

  useEffect(() => {
    if (searchParams.get('pay') !== '1' || !pendingItem) return
    const timer = window.setTimeout(() => {
      paySectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchParams, pendingItem?.id])

  const copyAddr = (addr: string, key: string) => {
    navigator.clipboard.writeText(addr)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const submitPay = async (id: number, payable: number) => {
    if (!txHash.trim()) {
      toast.error(t('settlements.txHashRequired'))
      return
    }
    try {
      await walletApi.paySettlement(id, chain, txHash, parseFloat(amount) || payable)
      toast.success(t('settlements.proofSubmitted'))
      setPayingId(null)
      setTxHash('')
      setAmount('')
      load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('settlements.submitFail'))
    }
  }

  const submitAppeal = async (id: number, payable: number) => {
    if (!txHash.trim()) {
      toast.error(t('settlements.txHashRequired'))
      return
    }
    try {
      await walletApi.appealSettlement(id, chain, txHash, parseFloat(amount) || payable, appealNote || undefined)
      toast.success(t('settlements.appealSubmitted'))
      setAppealingId(null)
      setTxHash('')
      setAmount('')
      setAppealNote('')
      load()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || t('settlements.appealFail'))
    }
  }

  const downloadPdf = async (id: number) => {
    const blob = await referralApi.settlementPdf(id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `settlement-${id}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }

  const statusLabel = (s: string) => t(`settlements.status.${s}`) || s

  const summary = useMemo(() => {
    const confirmed = items.filter(s => s.payment_status === 'confirmed')
    return {
      cycles: items.length,
      netProfit: items.reduce((n, s) => n + (s.net_profit || 0), 0),
      paid: confirmed.reduce((n, s) => n + (s.user_payable || 0), 0),
    }
  }, [items])

  return (
    <Layout>
      <PageHeader title={t('settlements.title')} subtitle={t('settlements.subtitle')} />

      {pendingItem && (
        <div className="section-mb-md" ref={paySectionRef} id="perf-fee-pay-section">
          <PendingPerfFeeCard settlement={pendingItem} showPayButton={false} variant="compact" />
          <GlassCard className="p-4 section-mt-sm settlement-pay-hint-card">
            <p className="text-sm-strong section-mb-xs">{t('settlements.payHeroTitle')}</p>
            <p className="text-muted text-sm">{t('settlements.payHeroHint')}</p>
          </GlassCard>
          <UserUniqueDepositPanel addresses={myAddresses} />
        </div>
      )}

      {tracking?.active && (
        <GlassCard className="p-4 section-mb-lg settlement-tracking-card">
          <h3 className="panel-title-sm section-mb-xs">{t('settlements.trackingTitle')}</h3>
          <p className="text-muted text-sm section-mb-md">{t('settlements.trackingHint')}</p>
          <div className="flex-between-wrap gap-sm section-mb-md">
            <span className={`badge ${tracking.payment_status === 'confirmed' ? 'badge-green' : 'badge-gray'}`}>
              {t(`settlements.trackingPhase.${tracking.tracking_phase}`) || tracking.tracking_phase}
            </span>
            <span className="text-muted text-xs">
              {t('settlements.monitorHealth')}: {t(`admin.depositMonitorHealth.${tracking.monitor_health}`) || tracking.monitor_health}
              {tracking.last_scan_at && ` · ${t('settlements.lastScan')} ${new Date(tracking.last_scan_at).toLocaleString()}`}
            </span>
          </div>
          <div className="stat-grid stat-grid-flush section-mb-md">
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('settlements.cols.payable')}</p>
              <p className="text-md-strong">${tracking.user_payable?.toFixed(2)}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('settlements.cols.netProfit')}</p>
              <p className="text-green text-md-strong">${tracking.net_profit?.toFixed(2)}</p>
            </div>
            <div className="stat-tile">
              <p className="text-muted text-xs">{t('settlements.depositLog')}</p>
              <p className="text-md-strong">${tracking.detected_total?.toFixed(2) ?? '0.00'}</p>
            </div>
          </div>
          {tracking.split && (
            <div className="section-mb-md">
              <p className="text-sm-strong section-mb-xs">{t('settlements.splitBreakdown')}</p>
              <div className="commission-grid">
                <div className="stat-tile"><p className="text-muted text-xs">{t('perfFee.splitUser')}</p><p>${tracking.split.user_payable}</p></div>
                <div className="stat-tile"><p className="text-muted text-xs">{t('perfFee.splitL1')}</p><p className="text-green">${tracking.split.l1_reward}</p></div>
                <div className="stat-tile"><p className="text-muted text-xs">{t('perfFee.splitL2')}</p><p className="text-green">${tracking.split.l2_reward}</p></div>
                <div className="stat-tile"><p className="text-muted text-xs">{t('perfFee.splitPlatform')}</p><p>${tracking.split.platform_net}</p></div>
              </div>
            </div>
          )}
          {tracking.tracking_phase === 'awaiting_transfer' || tracking.tracking_phase === 'underpaid' || tracking.tracking_phase === 'amount_ok_detecting' ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setAppealingId(tracking.settlement_id)
                setPayingId(null)
                setAmount(String(tracking.user_payable))
              }}
            >
              {t('settlements.appealCta')}
            </button>
          ) : null}
        </GlassCard>
      )}

      <GlassCard className="p-4 section-mb-lg">
        <p className="text-sm"><strong>{t('perfFee.cycleTitle')}</strong></p>
        <p className="text-muted text-sm section-mt-xs">{t('perfFee.flowSteps')}</p>
        <p className="text-muted text-xs section-mt-sm">{t('perfFee.resetNote')}</p>
        <p className="text-sm section-mt-md"><strong>{t('perfFee.splitTitle')}</strong></p>
        <p className="text-muted text-sm section-mt-xs">{t('perfFee.splitExample')}</p>
      </GlassCard>

      <div className="stat-grid section-mb-lg">
        <StatCard label={t('settlements.totalCycles')} countUp={{ end: summary.cycles, decimals: 0 }} />
        <StatCard label={t('settlements.totalProfit')} countUp={{ end: summary.netProfit, pnl: true, decimals: 2 }} positive={summary.netProfit >= 0} />
        <StatCard label={t('settlements.totalPaid')} countUp={{ end: summary.paid, prefix: '$', decimals: 2 }} />
      </div>

      <WithdrawCta />

      {!pendingItem && <UserUniqueDepositPanel addresses={myAddresses} />}

      {myAddresses.length === 0 && (
      <GlassCard className="p-6 section-mb-lg">
        <h3 className="panel-title-sm mb-md">{t('settlements.platformAddr')}</h3>
        {addresses.length === 0 ? (
          <p className="text-muted">{t('settlements.noAddr')}</p>
        ) : (
          <div className="log-list-stack">
            {addresses.map(a => (
              <div key={a.id} className="panel-muted-lg addr-panel-row">
                <div className="addr-panel-main">
                  <div>
                    <span className="badge badge-green">{a.chain}</span>
                    {a.label && <span className="text-muted label-inline">{a.label}</span>}
                    <p className="mono-text-sm">{a.address}</p>
                  </div>
                  {a.has_qr && (
                    <img
                      className="deposit-qr-settlement"
                      src={walletApi.depositAddressQrUrl(a.id)}
                      alt={t('settlements.walletQr')}
                    />
                  )}
                </div>
                <button className="btn btn-ghost" onClick={() => copyAddr(a.address, String(a.id))}>
                  {copied === String(a.id) ? <Check size={14} /> : <Copy size={14} />}
                  {copied === String(a.id) ? t('settlements.copied') : t('settlements.copyAddr')}
                </button>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
      )}

      {deposits.length > 0 && (
        <GlassCard className="p-0 table-wrap card-overflow-hidden section-mb-lg">
          <div className="card-section-head"><h3 className="panel-title-sm">{t('settlements.depositLog')}</h3></div>
          <table className="data-table data-table-sm">
            <thead>
              <tr>
                <th>{t('common.time')}</th>
                <th>{t('common.chain')}</th>
                <th>{t('settlements.cols.payable')}</th>
                <th>{t('common.status')}</th>
                <th>TxHash</th>
              </tr>
            </thead>
            <tbody>
              {deposits.map(d => (
                <tr key={d.id}>
                  <td>{new Date(d.detected_at).toLocaleString()}</td>
                  <td><span className="badge badge-gray">{d.chain}</span></td>
                  <td>${d.amount?.toFixed(2)}</td>
                  <td><span className="badge badge-gray">{d.status}</span></td>
                  <td className="mono-cell cell-ellipsis" title={d.tx_hash}>{d.tx_hash?.slice(0, 16)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      {appeals.length > 0 && (
        <GlassCard className="p-0 table-wrap card-overflow-hidden section-mb-lg">
          <div className="card-section-head"><h3 className="panel-title-sm">{t('settlements.appealLog')}</h3></div>
          <table className="data-table data-table-sm">
            <thead>
              <tr>
                <th>{t('common.time')}</th>
                <th>{t('common.chain')}</th>
                <th>{t('settlements.cols.payable')}</th>
                <th>{t('common.status')}</th>
                <th>TxHash</th>
              </tr>
            </thead>
            <tbody>
              {appeals.map(a => (
                <tr key={a.id}>
                  <td>{new Date(a.created_at).toLocaleString()}</td>
                  <td><span className="badge badge-gray">{a.chain}</span></td>
                  <td>${a.claimed_amount?.toFixed(2)}</td>
                  <td><span className="badge badge-gray">{t(`settlements.appealStatus.${a.status}`) || a.status}</span></td>
                  <td className="mono-cell cell-ellipsis" title={a.tx_hash}>{a.tx_hash?.slice(0, 16)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      )}

      <GlassCard className="p-0 table-wrap card-overflow-hidden">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('settlements.cols.period')}</th>
              <th>{t('settlements.cols.days')}</th>
              <th>{t('settlements.cols.hwm')}</th>
              <th>{t('settlements.cols.netProfit')}</th>
              <th>{t('settlements.cols.platformFee')}</th>
              <th>{t('settlements.cols.payable')}</th>
              <th>{t('settlements.cols.status')}</th>
              <th>{t('settlements.cols.action')}</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={8} className="text-muted empty-state-lg">{t('settlements.empty')}</td></tr>
            ) : items.map(s => (
              <tr key={s.id} className={s.payment_status === 'pending' || s.payment_status === 'paid' ? 'settlement-pending-row' : undefined}>
                <td>{s.period_start} ~ {s.period_end}</td>
                <td><span className="badge badge-gray">{formatSettlementCycle(s.cycle_days, t)}</span></td>
                <td className="text-muted">${(s.high_water_mark ?? 0).toFixed(2)}</td>
                <td className="text-green">${s.net_profit?.toFixed(2)}</td>
                <td>${s.platform_fee?.toFixed(2)}</td>
                <td>${s.user_payable?.toFixed(2)}</td>
                <td>
                  <span className={`badge ${s.payment_status === 'confirmed' ? 'badge-green' : 'badge-gray'}`}>
                    {statusLabel(s.payment_status)}
                  </span>
                </td>
                <td>
                  {s.payment_status === 'confirmed' && (
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => downloadPdf(s.id)}>{t('settlements.downloadPdf')}</button>
                  )}
                  {s.payment_status === 'pending' && (
                    <>
                      <button className="btn btn-ghost btn-compact-md"
                        onClick={() => { setPayingId(s.id); setAppealingId(null); setAmount(String(s.user_payable)) }}>
                        {t('settlements.submitPay')}
                      </button>
                      <button className="btn btn-ghost btn-compact-md"
                        onClick={() => { setAppealingId(s.id); setPayingId(null); setAmount(String(s.user_payable)) }}>
                        {t('settlements.submitAppeal')}
                      </button>
                    </>
                  )}
                  {s.payment_status === 'rejected' && (
                    <>
                      <button className="btn btn-ghost btn-compact-md"
                        onClick={() => { setPayingId(s.id); setAppealingId(null); setAmount(String(s.user_payable)) }}>
                        {t('settlements.resubmitPay')}
                      </button>
                      <button className="btn btn-ghost btn-compact-md"
                        onClick={() => { setAppealingId(s.id); setPayingId(null); setAmount(String(s.user_payable)) }}>
                        {t('settlements.submitAppeal')}
                      </button>
                    </>
                  )}
                  {s.payment_tx_hash && (
                    <span className="text-muted text-xs" title={s.payment_tx_hash}>
                      {s.payment_chain} · {s.payment_tx_hash.slice(0, 8)}...
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </GlassCard>

      {payingId && (
        <GlassCard className="p-6 section-mt-lg page-panel-form-sm">
          <h3 className="panel-title-sm mb-md">{t('settlements.payFormTitle')}</h3>
          <div className="form-stack">
            <div>
              <label className="text-secondary field-label">{t('settlements.chainLabel')}</label>
              <select className="input" value={chain} onChange={e => setChain(e.target.value)}>
                {monitoredChains.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <p className="text-muted text-xs section-mt-xs">{t('settlements.monitoredChainsHint')}</p>
            </div>
            <div>
              <label className="text-secondary field-label">{t('settlements.amountLabel')}</label>
              <input className="input" type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} />
            </div>
            <div>
              <label className="text-secondary field-label">{t('settlements.txHashLabel')}</label>
              <input className="input" value={txHash} onChange={e => setTxHash(e.target.value)} placeholder={t('settlements.txHashPh')} />
              <p className="text-muted text-xs section-mt-xs">{t('settlements.manualPayHint')}</p>
            </div>
            <div className="flex-gap-sm">
              <button className="btn btn-primary" type="button" onClick={() => submitPay(payingId, parseFloat(amount))}>{t('settlements.confirmSubmit')}</button>
              <button className="btn btn-ghost" type="button" onClick={() => setPayingId(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </GlassCard>
      )}

      {appealingId && (
        <GlassCard className="p-6 section-mt-lg page-panel-form-sm">
          <h3 className="panel-title-sm mb-md">{t('settlements.appealFormTitle')}</h3>
          <p className="text-muted text-sm section-mb-md">{t('settlements.appealFormHint')}</p>
          <div className="form-stack">
            <div>
              <label className="text-secondary field-label">{t('settlements.chainLabel')}</label>
              <select className="input" value={chain} onChange={e => setChain(e.target.value)}>
                {monitoredChains.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-secondary field-label">{t('settlements.amountLabel')}</label>
              <input className="input" type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} />
            </div>
            <div>
              <label className="text-secondary field-label">{t('settlements.txHashLabel')}</label>
              <input className="input" value={txHash} onChange={e => setTxHash(e.target.value)} placeholder={t('settlements.txHashPh')} />
            </div>
            <div>
              <label className="text-secondary field-label">{t('settlements.appealNoteLabel')}</label>
              <textarea className="input" rows={2} value={appealNote} onChange={e => setAppealNote(e.target.value)} placeholder={t('settlements.appealNotePh')} />
            </div>
            <div className="flex-gap-sm">
              <button className="btn btn-primary" type="button" onClick={() => submitAppeal(appealingId, parseFloat(amount))}>{t('settlements.confirmAppeal')}</button>
              <button className="btn btn-ghost" type="button" onClick={() => setAppealingId(null)}>{t('common.cancel')}</button>
            </div>
          </div>
        </GlassCard>
      )}
    </Layout>
  )
}
