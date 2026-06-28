import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'
import { useI18n, localeDate } from '../i18n'

const eventColors: Record<string, string> = {
  OPEN: 'badge-green', CLOSE: 'badge-gray', TRAIL: 'badge-green',
  SIGNAL: 'badge-gray', ADJUST: 'badge-gray', ERROR: 'badge-red',
}

export default function Logs() {
  const { t, locale } = useI18n()
  const [logs, setLogs] = useState<any[]>([])

  useEffect(() => { userApi.logs().then(setLogs) }, [])

  return (
    <Layout>
      <PageHeader title={t('logs.title')} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {logs.length === 0 ? (
          <GlassCard className="p-8" style={{ textAlign: 'center' }}>
            <p className="text-muted">{t('logs.empty')}</p>
          </GlassCard>
        ) : logs.map((log, i) => (
          <GlassCard key={log.id} delay={i * 0.03} className="p-4" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <span className={`badge ${eventColors[log.event_type] || 'badge-gray'}`}>{log.event_type}</span>
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: 14 }}>{log.message}</p>
              <p className="text-muted" style={{ fontSize: 12, marginTop: 4 }}>
                {localeDate(log.created_at, locale)}
              </p>
            </div>
          </GlassCard>
        ))}
      </div>
    </Layout>
  )
}
