import { useEffect, useState } from 'react'
import { Check, Crown } from 'lucide-react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { billingApi } from '../api'
import { useI18n } from '../i18n'

export default function Billing() {
  const t = useI18n(s => s.t)
  const [plans, setPlans] = useState<any[]>([])
  const [sub, setSub] = useState<any>(null)
  const [invoices, setInvoices] = useState<any[]>([])
  const [txHash, setTxHash] = useState<Record<number, string>>({})
  const [msg, setMsg] = useState('')

  useEffect(() => {
    billingApi.plans().then(setPlans)
    billingApi.subscription().then(setSub)
    billingApi.invoices().then(setInvoices)
  }, [])

  const subscribe = async (code: string) => {
    const res = await billingApi.subscribe(code, 'crypto')
    setMsg(res.status === 'paid' ? t('billing.activated') : t('billing.invoiceCreated', { id: res.invoice_id }))
    billingApi.subscription().then(setSub)
    billingApi.invoices().then(setInvoices)
  }

  const pay = async (id: number) => {
    await billingApi.payInvoice(id, txHash[id] || '')
    setMsg(t('billing.paymentSubmitted'))
    billingApi.invoices().then(setInvoices)
    billingApi.subscription().then(setSub)
  }

  return (
    <Layout>
      <PageHeader title={t('nav.billing')} subtitle={t('billing.subtitle')} />
      {msg && <p className="text-green" style={{ marginBottom: 16 }}>{msg}</p>}
      <p className="text-muted" style={{ marginBottom: 16 }}>{t('billing.currentPlan')}: <strong>{sub?.plan_code || 'starter'}</strong></p>

      <div className="billing-grid">
        {plans.map((plan, i) => (
          <GlassCard key={plan.code} className={`p-6 billing-card ${sub?.plan_code === plan.code ? 'glass-green' : ''}`} delay={i * 0.08}>
            {plan.code === 'vip' && <Crown size={20} className="text-green" style={{ marginBottom: 8 }} />}
            <h3>{plan.name}</h3>
            <p className="billing-price">{plan.price_usd ? `$${plan.price_usd}/mo` : t('billing.plans.starter.price')}</p>
            <ul className="billing-features">
              {(plan.features || []).map((f: string) => <li key={f}><Check size={14} /> {f}</li>)}
            </ul>
            <button type="button" className="btn btn-primary" style={{ width: '100%', marginTop: 16 }}
              disabled={sub?.plan_code === plan.code && plan.price_usd === 0}
              onClick={() => subscribe(plan.code)}>
              {sub?.plan_code === plan.code ? t('billing.current') : t('billing.subscribe')}
            </button>
          </GlassCard>
        ))}
      </div>

      {invoices.length > 0 && (
        <GlassCard className="p-6" style={{ marginTop: 24 }}>
          <h3 className="card-heading">{t('billing.invoices')}</h3>
          {invoices.map(inv => (
            <div key={inv.id} style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
              <span>#{inv.id} · {inv.plan_code} · ${inv.amount} · {inv.status}</span>
              {inv.status === 'pending' && (
                <>
                  <input className="input" placeholder="TxHash" value={txHash[inv.id] || ''} onChange={e => setTxHash({ ...txHash, [inv.id]: e.target.value })} style={{ flex: 1, minWidth: 160 }} />
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => pay(inv.id)}>{t('billing.pay')}</button>
                </>
              )}
            </div>
          ))}
        </GlassCard>
      )}

      <GlassCard className="p-6" style={{ marginTop: 24 }}>
        <h3 className="card-heading">{t('nav.settlements')}</h3>
        <p className="text-muted">{t('billing.settlementNote')}</p>
        <Link to="/settlements" className="btn btn-secondary" style={{ marginTop: 12 }}>{t('billing.viewSettlements')}</Link>
      </GlassCard>
    </Layout>
  )
}
