import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'
import { useI18n, localeDate } from '../i18n'

const eventColors: Record<string, string> = {
  OPEN: 'badge-green', CLOSE: 'badge-gray', TRAIL: 'badge-green',
  SIGNAL: 'badge-gray', ADJUST: 'badge-gray', ERROR: 'badge-red',
  STARTUP: 'badge-green',
}

function formatDetail(raw?: string | null) {
  if (!raw) return null
  try {
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object' || !Object.keys(obj).length) return null
    return JSON.stringify(obj, null, 2)
  } catch {
    return raw
  }
}

export default function Logs() {
  const { t, locale } = useI18n()
  const [logs, setLogs] = useState<any[]>([])

  useEffect(() => { userApi.logs().then(setLogs) }, [])

  return (
    <Layout>
      <PageHeader title={t('logs.title')} subtitle={t('logs.subtitle')} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {logs.length === 0 ? (
          <GlassCard className="p-8" style={{ textAlign: 'center' }}>
            <p className="text-muted">{t('logs.empty')}</p>
          </GlassCard>
        ) : logs.map((log, i) => {
          const detail = formatDetail(log.detail_json)
          return (
            <GlassCard key={log.id} delay={i * 0.03} className="p-4">
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
                <span className={`badge ${eventColors[log.event_type] || 'badge-gray'}`}>{log.event_type}</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 14 }}>{log.message}</p>
                  <p className="text-muted" style={{ fontSize: 12, marginTop: 4 }}>
                    {localeDate(log.created_at, locale)}
                    {log.trade_id ? ` · trade #${log.trade_id}` : ''}
                  </p>
                  {detail && (
                    <pre className="text-muted" style={{
                      fontSize: 11, marginTop: 10, padding: 10, borderRadius: 8,
                      background: 'rgba(255,255,255,0.03)', overflow: 'auto', whiteSpace: 'pre-wrap',
                    }}>{detail}</pre>
                  )}
                </div>
              </div>
            </GlassCard>
          )
        })}
      </div>
    </Layout>
  )
}
