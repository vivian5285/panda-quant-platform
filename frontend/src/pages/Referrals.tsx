import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Layout from '../components/Layout'
import StatCard from '../components/StatCard'
import GlassCard from '../components/GlassCard'
import { referralApi } from '../api'
import { generateInvitePoster, downloadPoster } from '../utils/invitePoster'
import { Copy, Check, Link2, Image, Download, Share2 } from 'lucide-react'

export default function Referrals() {
  const [data, setData] = useState<any>(null)
  const [copied, setCopied] = useState('')
  const [posterUrl, setPosterUrl] = useState('')
  const [posterLoading, setPosterLoading] = useState(false)
  const [showPoster, setShowPoster] = useState(false)

  useEffect(() => { referralApi.summary().then(setData) }, [])

  const copyText = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(''), 2000)
  }

  const generatePoster = async () => {
    if (!data) return
    setPosterLoading(true)
    try {
      const url = await generateInvitePoster({
        inviteUrl: data.invite_url,
        referralCode: data.referral_code,
        displayName: data.display_name || '推广达人',
        uid: data.uid,
        l1Rate: data.commission?.l1_rate ?? 0.1,
        l2Rate: data.commission?.l2_rate ?? 0.05,
      })
      setPosterUrl(url)
      setShowPoster(true)
    } finally {
      setPosterLoading(false)
    }
  }

  const shareLink = async () => {
    if (!data?.invite_url) return
    if (navigator.share) {
      try {
        await navigator.share({
          title: '熊猫量化 · Panda Quant AI',
          text: 'AI 智能量化托管，邀请你一起加入！',
          url: data.invite_url,
        })
      } catch { /* cancelled */ }
    } else {
      copyText(data.invite_url, 'share')
    }
  }

  return (
    <Layout>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 8 }}>推广中心</h1>
      <p className="text-secondary" style={{ fontSize: 14, marginBottom: 24 }}>
        专属邀请链接 · 精美海报 · 二级分润自动结算
      </p>

      <GlassCard green className="p-6" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <p className="text-muted" style={{ fontSize: 13, marginBottom: 8 }}>我的专属邀请链接</p>
            <p style={{
              fontSize: 14, wordBreak: 'break-all', lineHeight: 1.6,
              padding: '12px 16px', borderRadius: 10, background: 'rgba(0,0,0,0.3)',
              border: '1px solid rgba(0,230,118,0.15)', fontFamily: 'monospace',
            }}>
              {data?.invite_url || '...'}
            </p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8 }}>
              推荐码 <span className="text-green" style={{ fontWeight: 600 }}>{data?.referral_code}</span>
              {' · '}UID {data?.uid}
            </p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 140 }}>
            <button className="btn btn-primary" onClick={() => copyText(data?.invite_url, 'link')}>
              {copied === 'link' ? <Check size={16} /> : <Link2 size={16} />}
              {copied === 'link' ? '已复制链接' : '复制邀请链接'}
            </button>
            <button className="btn btn-ghost" onClick={() => copyText(data?.referral_code, 'code')}>
              {copied === 'code' ? <Check size={16} /> : <Copy size={16} />}
              {copied === 'code' ? '已复制' : '复制推荐码'}
            </button>
            <button className="btn btn-ghost" onClick={shareLink}>
              <Share2 size={16} /> 分享
            </button>
            <button className="btn btn-ghost" onClick={generatePoster} disabled={posterLoading}>
              <Image size={16} /> {posterLoading ? '生成中...' : '生成邀请海报'}
            </button>
          </div>
        </div>
      </GlassCard>

      {showPoster && posterUrl && (
        <GlassCard className="p-6" style={{ marginBottom: 24, textAlign: 'center' }}>
          <h3 style={{ fontSize: 15, marginBottom: 16 }}>邀请海报预览</h3>
          <img src={posterUrl} alt="邀请海报" style={{
            maxWidth: '100%', width: 375, borderRadius: 16,
            boxShadow: '0 20px 60px rgba(0,230,118,0.15)',
          }} />
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 20, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={() => downloadPoster(posterUrl, `panda-invite-${data?.referral_code}.png`)}>
              <Download size={16} /> 下载海报
            </button>
            <button className="btn btn-ghost" onClick={() => setShowPoster(false)}>关闭预览</button>
          </div>
        </GlassCard>
      )}

      <GlassCard className="p-6" style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, marginBottom: 16 }}>二级分润规则</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
          <div style={{ padding: 16, borderRadius: 12, background: 'rgba(0,230,118,0.06)', border: '1px solid rgba(0,230,118,0.15)' }}>
            <p className="text-green" style={{ fontSize: 28, fontWeight: 700 }}>{Math.round((data?.commission?.l1_rate ?? 0.1) * 100)}%</p>
            <p style={{ fontSize: 14, fontWeight: 500, marginTop: 4 }}>一级推广分润</p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>
              您直接邀请的用户，每次结算盈利后，从平台 25% 分成中获得 10%
            </p>
          </div>
          <div style={{ padding: 16, borderRadius: 12, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <p className="text-green" style={{ fontSize: 28, fontWeight: 700 }}>{Math.round((data?.commission?.l2_rate ?? 0.05) * 100)}%</p>
            <p style={{ fontSize: 14, fontWeight: 500, marginTop: 4 }}>二级推广分润</p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>
              您的下级再邀请的用户盈利结算后，您持续获得 5% 分润
            </p>
          </div>
          <div style={{ padding: 16, borderRadius: 12, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
            <p style={{ fontSize: 28, fontWeight: 700 }}>25%</p>
            <p style={{ fontSize: 14, fontWeight: 500, marginTop: 4 }}>平台分成基数</p>
            <p className="text-muted" style={{ fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>
              用户盈利结算时平台收取 25%，推广奖励从该部分分出
            </p>
          </div>
        </div>
        <p className="text-muted" style={{ fontSize: 12, marginTop: 16 }}>
          ✓ 下级用户结算确认付款后，分润自动进入您的奖励账户 · 可提现或内部转账
        </p>
      </GlassCard>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 16, marginBottom: 24 }}>
        <StatCard label="一级下级" value={String(data?.l1_count || 0)} />
        <StatCard label="二级下级" value={String(data?.l2_count || 0)} />
        <StatCard label="一级累计奖励" value={`$${(data?.l1_total_rewards || 0).toFixed(2)}`} />
        <StatCard label="二级累计奖励" value={`$${(data?.l2_total_rewards || 0).toFixed(2)}`} />
        <StatCard label="奖励余额" value={`$${(data?.reward_balance || 0).toFixed(2)}`} />
        <StatCard label="待结算" value={`$${(data?.pending_rewards || 0).toFixed(2)}`} />
      </div>

      <GlassCard className="p-4" style={{ marginBottom: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 } as any}>
        <p style={{ fontSize: 14 }}>累计推广收益 <span className="text-green" style={{ fontSize: 20, fontWeight: 600 }}>${(data?.total_rewards || 0).toFixed(2)}</span></p>
        <Link to="/withdraw" className="btn btn-primary" style={{ textDecoration: 'none' }}>提现 / 转账</Link>
      </GlassCard>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <h3 style={{ fontSize: 15 }}>一级下级 <span className="text-green">{Math.round((data?.commission?.l1_rate ?? 0.1) * 100)}%</span></h3>
          </div>
          <table className="data-table">
            <thead><tr><th>用户</th><th>累计盈亏</th><th>我的奖励</th></tr></thead>
            <tbody>
              {(data?.l1_users || []).length === 0 ? (
                <tr><td colSpan={3} className="text-muted" style={{ textAlign: 'center', padding: 24 }}>邀请好友加入，开始赚取分润</td></tr>
              ) : data.l1_users.map((u: any) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td className={u.week_pnl >= 0 ? 'text-green' : 'text-red'}>${u.week_pnl?.toFixed(2)}</td>
                  <td className="text-green">${u.total_reward?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>

        <GlassCard className="p-0" style={{ overflow: 'hidden' } as any}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <h3 style={{ fontSize: 15 }}>二级下级 <span className="text-green">{Math.round((data?.commission?.l2_rate ?? 0.05) * 100)}%</span></h3>
          </div>
          <table className="data-table">
            <thead><tr><th>用户</th><th>累计盈亏</th><th>我的奖励</th></tr></thead>
            <tbody>
              {(data?.l2_users || []).length === 0 ? (
                <tr><td colSpan={3} className="text-muted" style={{ textAlign: 'center', padding: 24 }}>暂无二级下级</td></tr>
              ) : data.l2_users.map((u: any) => (
                <tr key={u.id}>
                  <td>{u.email}</td>
                  <td className={u.week_pnl >= 0 ? 'text-green' : 'text-red'}>${u.week_pnl?.toFixed(2)}</td>
                  <td className="text-green">${u.total_reward?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
      </div>

      <style>{`@media (max-width: 768px) { div[style*="grid-template-columns: 1fr 1fr"] { grid-template-columns: 1fr !important; } }`}</style>
    </Layout>
  )
}
