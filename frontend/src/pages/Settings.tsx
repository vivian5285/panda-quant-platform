import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { settingsApi } from '../api'
import { useI18n } from '../i18n'

export default function Settings() {
  const t = useI18n(s => s.t)
  const [prefs, setPrefs] = useState<any>(null)
  const [totp, setTotp] = useState<any>(null)
  const [code, setCode] = useState('')
  const [apiKeys, setApiKeys] = useState<any[]>([])
  const [newKey, setNewKey] = useState<string | null>(null)
  const [msg, setMsg] = useState('')

  const load = () => {
    settingsApi.get().then(setPrefs).catch(() => {})
    settingsApi.apiKeys().then(setApiKeys).catch(() => {})
  }
  useEffect(() => { load() }, [])

  const save = async () => {
    await settingsApi.update(prefs)
    setMsg(t('settings.saved'))
  }

  const setup2fa = async () => {
    const res = await settingsApi.totpSetup()
    setTotp(res)
  }

  const enable2fa = async () => {
    await settingsApi.totpEnable(code)
    setMsg(t('settings.totpEnabled'))
    load()
  }

  const createKey = async () => {
    const res = await settingsApi.createApiKey('Open API')
    setNewKey(res.key)
    load()
  }

  if (!prefs) return <Layout><p>{t('common.loading')}</p></Layout>

  return (
    <Layout>
      <PageHeader title={t('nav.settings')} subtitle={t('settings.subtitle')} />
      {msg && <p className="text-green" style={{ marginBottom: 16 }}>{msg}</p>}

      <GlassCard className="p-6" style={{ marginBottom: 24 }}>
        <h3 className="card-heading">{t('settings.notifications')}</h3>
        {['notify_email', 'notify_in_app', 'notify_telegram', 'notify_webhook'].map(k => (
          <label key={k} className="auth-remember" style={{ display: 'block', marginBottom: 8 }}>
            <input type="checkbox" checked={!!prefs[k]} onChange={e => setPrefs({ ...prefs, [k]: e.target.checked })} />
            {t(`settings.${k}`)}
          </label>
        ))}
        <div className="form-field"><label className="form-label">Telegram Chat ID</label>
          <input className="input" value={prefs.telegram_chat_id || ''} onChange={e => setPrefs({ ...prefs, telegram_chat_id: e.target.value })} /></div>
        <div className="form-field"><label className="form-label">Discord Webhook</label>
          <input className="input" value={prefs.discord_webhook_url || ''} onChange={e => setPrefs({ ...prefs, discord_webhook_url: e.target.value })} /></div>
        <button type="button" className="btn btn-primary" onClick={save}>{t('common.save')}</button>
      </GlassCard>

      <GlassCard className="p-6" style={{ marginBottom: 24 }}>
        <h3 className="card-heading">{t('settings.totp')}</h3>
        <p className="text-muted">{prefs.totp_enabled ? t('settings.totpOn') : t('settings.totpOff')}</p>
        {!totp ? (
          <button type="button" className="btn btn-secondary" onClick={setup2fa}>{t('settings.setup2fa')}</button>
        ) : (
          <div>
            <p className="text-muted" style={{ fontSize: 12, wordBreak: 'break-all' }}>{totp.provisioning_uri}</p>
            <input className="input" value={code} onChange={e => setCode(e.target.value)} placeholder="6-digit code" style={{ maxWidth: 200, marginTop: 12 }} />
            <button type="button" className="btn btn-primary" style={{ marginLeft: 8 }} onClick={enable2fa}>{t('settings.enable2fa')}</button>
          </div>
        )}
      </GlassCard>

      <GlassCard className="p-6">
        <h3 className="card-heading">{t('settings.openApi')}</h3>
        {newKey && <p className="text-green" style={{ wordBreak: 'break-all', marginBottom: 12 }}>{newKey}</p>}
        <button type="button" className="btn btn-primary" onClick={createKey}>{t('settings.createKey')}</button>
        <ul style={{ marginTop: 16, listStyle: 'none' }}>
          {apiKeys.map(k => (
            <li key={k.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--glass-border)' }}>
              <span>{k.name} · {k.key_prefix}…</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => settingsApi.revokeApiKey(k.id).then(load)}>{t('common.delete')}</button>
            </li>
          ))}
        </ul>
      </GlassCard>
    </Layout>
  )
}
