import { useEffect, useState } from 'react'
import Layout from '../components/Layout'
import PageHeader from '../components/PageHeader'
import GlassCard from '../components/GlassCard'
import StatCard from '../components/StatCard'
import Skeleton from '../components/ui/Skeleton'
import { userApi } from '../api'
import { useI18n, localeDate } from '../i18n'

export default function Signals() {
  const { t, locale } = useI18n()
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    userApi.signals().then(setData).finally(() => setLoading(false))
    const timer = setInterval(() => userApi.signals().then(setData), 20000)
    return () => clearInterval(timer)
  }, [])

  return (
    <Layout>
      <PageHeader title={t('nav.signals')} subtitle={t('signals.subtitle')} />
      <div className="stat-grid">
        {loading ? [1, 2, 3].map(n => <Skeleton key={n} height={88} />) : (
          <>
            <StatCard label={t('signals.total')} value={String(data?.total || 0)} delay={0.1} />
            <StatCard label={t('signals.successRate')} value={`${data?.success_rate || 0}%`} delay={0.15} />
            <StatCard label={t('signals.latency')} value="<1s" delay={0.2} />
          </>
        )}
      </div>
      <GlassCard className="p-6">
        <h3 className="card-heading">{t('signals.recent')}</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>{t('signals.event')}</th><th>{t('common.time')}</th><th>{t('signals.message')}</th></tr></thead>
            <tbody>
              {(data?.recent || []).map((s: any) => (
                <tr key={s.id}>
                  <td><span className="badge-gray">{s.event_type}</span></td>
                  <td>{s.created_at ? localeDate(s.created_at, locale) : '—'}</td>
                  <td style={{ maxWidth: 400, overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.message || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>
    </Layout>
  )
}
