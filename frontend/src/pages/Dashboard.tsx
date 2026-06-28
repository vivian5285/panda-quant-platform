import { useEffect, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import Layout from '../components/Layout'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import { userApi } from '../api'

function fmt(n: number) {
  const prefix = n >= 0 ? '+$' : '-$'
  return prefix + Math.abs(n).toFixed(2)
}

export default function Dashboard() {
  const [data, setData] = useState<any>(null)

  useEffect(() => {
    userApi.dashboard().then(setData).catch(console.error)
    const t = setInterval(() => userApi.dashboard().then(setData), 30000)
    return () => clearInterval(t)
  }, [])

  const chartOption = {
    backgroundColor: 'transparent',
    grid: { top: 30, right: 20, bottom: 30, left: 50 },
    xAxis: {
      type: 'category',
      data: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
      axisLine: { lineStyle: { color: 'rgba(0,0,0,0.08)' } },
      axisLabel: { color: '#86868b', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
      axisLabel: { color: '#86868b', fontSize: 11 },
    },
    series: [{
      data: [120, 280, -50, 390, 210, 328, data?.today_pnl || 0],
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { color: '#1d1d1f', width: 2 },
      itemStyle: { color: '#1d1d1f' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(0,0,0,0.08)' },
            { offset: 1, color: 'rgba(0,0,0,0)' },
          ],
        },
      },
    }],
  }

  return (
    <Layout>
      <div className="animate-in">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
          <h1 style={{ fontSize: 24, fontWeight: 600 }}>仪表盘</h1>
          <div className="pulse-dot" />
          <span className="text-muted" style={{ fontSize: 13 }}>实时</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 24 }}>
          <StatCard label="账户余额" value={`$${(data?.balance || 0).toFixed(2)}`} delay={0.1} />
          <StatCard label="未实现盈亏" value={fmt(data?.unrealized_pnl || 0)} positive={(data?.unrealized_pnl || 0) >= 0} delay={0.15} />
          <StatCard label="本周期盈亏" value={fmt(data?.cycle_pnl || 0)} positive={(data?.cycle_pnl || 0) >= 0} delay={0.18} />
          <StatCard label="初始本金" value={`$${(data?.initial_principal || 0).toFixed(2)}`} delay={0.2} />
          <StatCard label="今日盈亏" value={fmt(data?.today_pnl || 0)} positive={(data?.today_pnl || 0) >= 0} delay={0.22} />
          <StatCard label="累计收益" value={fmt(data?.total_pnl || 0)} positive={(data?.total_pnl || 0) >= 0} delay={0.25} />
        </div>

        <GlassCard className="p-6" delay={0.3} style={{ marginBottom: 24 } as any}>
          <h3 style={{ fontSize: 15, fontWeight: 500, marginBottom: 16 }}>盈亏趋势</h3>
          <ReactECharts option={chartOption} style={{ height: 280 }} />
        </GlassCard>

        {data?.open_position?.has_position && (
          <GlassCard green className="p-6" delay={0.35}>
            <h3 style={{ fontSize: 15, fontWeight: 500, marginBottom: 16 }}>当前持仓</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 16 }}>
              <div>
                <p className="text-muted" style={{ fontSize: 12 }}>方向</p>
                <p className={data.open_position.side === 'LONG' ? 'text-green' : 'text-red'} style={{ fontSize: 18, fontWeight: 600 }}>
                  {data.open_position.side}
                </p>
              </div>
              <div>
                <p className="text-muted" style={{ fontSize: 12 }}>数量</p>
                <p style={{ fontSize: 18, fontWeight: 600 }}>{data.open_position.qty} ETH</p>
              </div>
              <div>
                <p className="text-muted" style={{ fontSize: 12 }}>入场价</p>
                <p style={{ fontSize: 18, fontWeight: 600 }}>${data.open_position.entry_price?.toFixed(2)}</p>
              </div>
              <div>
                <p className="text-muted" style={{ fontSize: 12 }}>浮动盈亏</p>
                <p className={data.open_position.unrealized_pnl >= 0 ? 'text-green' : 'text-red'} style={{ fontSize: 18, fontWeight: 600 }}>
                  {fmt(data.open_position.unrealized_pnl)}
                </p>
              </div>
            </div>
          </GlassCard>
        )}
      </div>
    </Layout>
  )
}
