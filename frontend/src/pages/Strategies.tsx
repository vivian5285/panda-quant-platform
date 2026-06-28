import { useEffect, useState } from 'react'
import { Bot, Copy, Pause, Play, Plus, Trash2, TrendingUp } from 'lucide-react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { strategyApi } from '../api'
import { useI18n } from '../i18n'

export default function Strategies() {
  const t = useI18n(s => s.t)
  const [list, setList] = useState<any[]>([])
  const [form, setForm] = useState({ name: '', description: '', strategy_type: 'trend' })
  const [showForm, setShowForm] = useState(false)
  const [selected, setSelected] = useState<any>(null)
  const [versions, setVersions] = useState<any[]>([])

  const load = () => strategyApi.list().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    await strategyApi.create({ ...form, config: { leverage: 15, symbol: 'ETHUSDT' } })
    setForm({ name: '', description: '', strategy_type: 'trend' })
    setShowForm(false)
    load()
  }

  const toggle = async (s: any) => {
    await strategyApi.update(s.id, { status: s.status === 'active' ? 'paused' : 'active' })
    load()
  }

  const remove = async (id: number) => {
    if (!confirm(t('common.confirm') + '?')) return
    await strategyApi.remove(id)
    load()
  }

  const openDetail = async (s: any) => {
    setSelected(s)
    setVersions(await strategyApi.versions(s.id))
  }

  return (
    <Layout>
      <PageHeader title={t('nav.strategies')} subtitle={t('strategies.subtitle')}
        action={<button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}><Plus size={16} /> {t('common.add')}</button>} />

      {showForm && (
        <GlassCard className="p-6" style={{ marginBottom: 24 }}>
          <form onSubmit={create}>
            <div className="form-field"><label className="form-label">{t('common.nickname')}</label>
              <input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required /></div>
            <div className="form-field"><label className="form-label">Type</label>
              <select className="input" value={form.strategy_type} onChange={e => setForm({ ...form, strategy_type: e.target.value })}>
                {['trend', 'breakout', 'mean', 'momentum'].map(k => <option key={k} value={k}>{t(`landing.strategy.tags.${k}`)}</option>)}
              </select></div>
            <div className="form-field"><label className="form-label">Description</label>
              <input className="input" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></div>
            <button type="submit" className="btn btn-primary">{t('common.save')}</button>
            <button type="button" className="btn btn-ghost" style={{ marginLeft: 8 }} onClick={() => setShowForm(false)}>{t('common.cancel')}</button>
          </form>
        </GlassCard>
      )}

      <div className="strategy-grid">
        {list.map((s, i) => (
          <GlassCard key={s.id} className="p-6 strategy-card" delay={i * 0.05}>
            <div className="strategy-card-head">
              <div className="bento-icon"><Bot size={20} /></div>
              <span className={`badge-green ${s.status !== 'active' ? 'badge-gray' : ''}`}>{s.status}</span>
            </div>
            <h3>{s.name}</h3>
            <p className="text-muted" style={{ fontSize: 13, marginBottom: 12 }}>{s.description || s.strategy_type}</p>
            {s.webhook_token && <p className="text-muted" style={{ fontSize: 11, wordBreak: 'break-all' }}>Webhook: …{s.webhook_token.slice(-8)}</p>}
            <div className="strategy-metrics">
              <div><label>Sharpe</label><strong>{s.sharpe || '—'}</strong></div>
              <div><label>Win</label><strong>{s.win_rate ? `${s.win_rate}%` : '—'}</strong></div>
              <div><label>MDD</label><strong>{s.max_drawdown || '—'}</strong></div>
            </div>
            <div className="strategy-actions">
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => toggle(s)}><Pause size={14} /></button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigator.clipboard.writeText(s.webhook_token || '')}><Copy size={14} /></button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => remove(s.id)}><Trash2 size={14} /></button>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => openDetail(s)}><TrendingUp size={14} /> {t('strategies.details')}</button>
            </div>
          </GlassCard>
        ))}
      </div>

      {selected && (
        <GlassCard className="p-6" style={{ marginTop: 24 }}>
          <h3 className="card-heading">{selected.name} — {t('strategies.versions')}</h3>
          <ul className="landing-check-list">
            {versions.map(v => <li key={v.id}><Play size={14} /><div><strong>v{v.version}</strong><span>{v.change_note} · {v.created_at}</span></div></li>)}
          </ul>
          <button type="button" className="btn btn-ghost" style={{ marginTop: 12 }} onClick={() => setSelected(null)}>{t('common.cancel')}</button>
        </GlassCard>
      )}
    </Layout>
  )
}
