import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'

const eventColors: Record<string, string> = {
  OPEN: 'badge-green', CLOSE: 'badge-gray', TRAIL: 'badge-green',
  SIGNAL: 'badge-gray', ADJUST: 'badge-gray', ERROR: 'badge-red',
}

export default function Logs() {
  const [logs, setLogs] = useState<any[]>([])

  useEffect(() => { userApi.logs().then(setLogs) }, [])

  return (
    <Layout>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>操作日志</h1>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {logs.length === 0 ? (
          <GlassCard className="p-8" style={{ textAlign: 'center' } as any}>
            <p className="text-muted">暂无日志</p>
          </GlassCard>
        ) : logs.map((log, i) => (
          <GlassCard key={log.id} delay={i * 0.03} className="p-4" style={{ display: 'flex', alignItems: 'center', gap: 16 } as any}>
            <span className={`badge ${eventColors[log.event_type] || 'badge-gray'}`}>{log.event_type}</span>
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: 14 }}>{log.message}</p>
              <p className="text-muted" style={{ fontSize: 12, marginTop: 4 }}>
                {new Date(log.created_at).toLocaleString('zh-CN')}
              </p>
            </div>
          </GlassCard>
        ))}
      </div>
    </Layout>
  )
}
