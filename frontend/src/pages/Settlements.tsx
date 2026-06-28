import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { referralApi, walletApi, referralApiExtra } from '../api'
import { useI18n } from '../i18n'
import { Copy, Check } from 'lucide-react'

export default function Settlements() {
  const { t } = useI18n()
  const [items, setItems] = useState<any[]>([])
  const [addresses, setAddresses] = useState<any[]>([])
  const [payingId, setPayingId] = useState<number | null>(null)
  const [chain, setChain] = useState('TRC20')
  const [txHash, setTxHash] = useState('')
  const [amount, setAmount] = useState('')
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState('')

  const load = () => {
    referralApi.settlements().then(setItems)
    walletApi.depositAddresses().then(setAddresses)
  }

  useEffect(() => { load() }, [])

  const copyAddr = (addr: string, key: string) => {
    navigator.clipboard.writeText(addr)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const submitPay = async (id: number, payable: number) => {
    setError('')
    setMsg('')
    try {
      await walletApi.paySettlement(id, chain, txHash, parseFloat(amount) || payable)
      setMsg(t('settlements.proofSubmitted'))
      setPayingId(null)
      setTxHash('')
      setAmount('')
      load()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('settlements.submitFail'))
    }
  }

  const downloadPdf = async (id: number) => {
    const blob = await referralApiExtra.settlementPdf(id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `settlement-${id}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }

  const statusLabel = (s: string) => t(`settlements.status.${s}`) || s

  return (
    <Layout>
      <PageHeader title={t('settlements.title')} subtitle={t('settlements.subtitle')} />

      <GlassCard green className="p-6" style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 500, marginBottom: 16 }}>{t('settlements.platformAddr')}</h3>
        {addresses.length === 0 ? (
          <p className="text-muted">{t('settlements.noAddr')}</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {addresses.map(a => (
              <div key={a.id} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                flexWrap: 'wrap', gap: 12, padding: '12px 16px',
                background: 'rgba(255,255,255,0.03)', borderRadius: 10,
              }}>
                <div>
                  <span className="badge badge-green">{a.chain}</span>
                  {a.label && <span className="text-muted" style={{ marginLeft: 8, fontSize: 12 }}>{a.label}</span>}
                  <p style={{ fontSize: 13, marginTop: 8, wordBreak: 'break-all', fontFamily: 'monospace' }}>{a.address}</p>
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

      {msg && <p className="text-green" style={{ marginBottom: 16 }}>{msg}</p>}
      {error && <p className="text-red" style={{ marginBottom: 16 }}>{error}</p>}

      <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('settlements.cols.period')}</th>
              <th>{t('settlements.cols.days')}</th>
              <th>{t('settlements.cols.netProfit')}</th>
              <th>{t('settlements.cols.platformFee')}</th>
              <th>{t('settlements.cols.payable')}</th>
              <th>{t('settlements.cols.status')}</th>
              <th>{t('settlements.cols.action')}</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={7} className="text-muted" style={{ textAlign: 'center', padding: 40 }}>{t('settlements.empty')}</td></tr>
            ) : items.map(s => (
              <tr key={s.id}>
                <td>{s.period_start} ~ {s.period_end}</td>
                <td><span className="badge badge-gray">{s.cycle_days || 7}{t('common.days')}</span></td>
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
                    <button className="btn btn-ghost" style={{ padding: '4px 12px', fontSize: 12 }}
                      onClick={() => { setPayingId(s.id); setAmount(String(s.user_payable)) }}>
                      {t('settlements.submitPay')}
                    </button>
                  )}
                  {s.payment_tx_hash && (
                    <span className="text-muted" style={{ fontSize: 11 }} title={s.payment_tx_hash}>
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
        <GlassCard green className="p-6" style={{ marginTop: 24, maxWidth: 480 }}>
          <h3 style={{ fontSize: 15, marginBottom: 16 }}>{t('settlements.payFormTitle')}</h3>
          <div style={{ marginBottom: 12 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>{t('settlements.chainLabel')}</label>
            <select className="input" value={chain} onChange={e => setChain(e.target.value)}>
              {['TRC20', 'ERC20', 'BEP20', 'ARBITRUM', 'POLYGON', 'SOL'].map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: 12 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>{t('settlements.amountLabel')}</label>
            <input className="input" type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label className="text-secondary" style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>{t('settlements.txHashLabel')}</label>
            <input className="input" value={txHash} onChange={e => setTxHash(e.target.value)} placeholder={t('settlements.txHashPh')} required />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary" onClick={() => submitPay(payingId, parseFloat(amount))}>{t('settlements.confirmSubmit')}</button>
            <button className="btn btn-ghost" onClick={() => setPayingId(null)}>{t('common.cancel')}</button>
          </div>
        </GlassCard>
      )}
    </Layout>
  )
}
