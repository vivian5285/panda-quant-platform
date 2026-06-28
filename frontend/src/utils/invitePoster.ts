import QRCode from 'qrcode'

export interface PosterData {
  inviteUrl: string
  referralCode: string
  displayName: string
  uid: string
  l1Rate: number
  l2Rate: number
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

export async function generateInvitePoster(data: PosterData): Promise<string> {
  const W = 750
  const H = 1200
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!

  const bg = ctx.createLinearGradient(0, 0, W, H)
  bg.addColorStop(0, '#030303')
  bg.addColorStop(0.5, '#0a0f0a')
  bg.addColorStop(1, '#050505')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  ctx.strokeStyle = 'rgba(0,230,118,0.15)'
  ctx.lineWidth = 2
  roundRect(ctx, 24, 24, W - 48, H - 48, 32)
  ctx.stroke()

  const glow = ctx.createRadialGradient(W / 2, 280, 20, W / 2, 280, 320)
  glow.addColorStop(0, 'rgba(0,230,118,0.12)')
  glow.addColorStop(1, 'rgba(0,230,118,0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, W, 500)

  ctx.font = '72px serif'
  ctx.textAlign = 'center'
  ctx.fillText('🐼', W / 2, 120)

  ctx.fillStyle = '#FFFFFF'
  ctx.font = 'bold 42px Inter, sans-serif'
  ctx.fillText('熊猫量化', W / 2, 190)

  ctx.fillStyle = '#00E676'
  ctx.font = '22px Inter, sans-serif'
  ctx.fillText('Panda Quant AI', W / 2, 228)

  ctx.fillStyle = 'rgba(255,255,255,0.65)'
  ctx.font = '24px Inter, sans-serif'
  ctx.fillText('AI 智能量化托管 · 安全透明 · 稳定收益', W / 2, 280)

  const badges = ['🔒 加密托管', '📊 透明结算', '💰 二级分润']
  ctx.font = '18px Inter, sans-serif'
  let bx = W / 2 - 200
  badges.forEach(b => {
    ctx.fillStyle = 'rgba(0,230,118,0.12)'
    roundRect(ctx, bx, 310, 130, 36, 18)
    ctx.fill()
    ctx.strokeStyle = 'rgba(0,230,118,0.3)'
    ctx.stroke()
    ctx.fillStyle = '#00E676'
    ctx.textAlign = 'center'
    ctx.fillText(b, bx + 65, 334)
    bx += 145
  })

  ctx.fillStyle = 'rgba(255,255,255,0.08)'
  roundRect(ctx, 48, 380, W - 96, 180, 20)
  ctx.fill()
  ctx.strokeStyle = 'rgba(0,230,118,0.2)'
  ctx.stroke()

  ctx.textAlign = 'left'
  ctx.fillStyle = 'rgba(255,255,255,0.5)'
  ctx.font = '18px Inter, sans-serif'
  ctx.fillText('推广收益（从平台分成中结算）', 72, 420)

  ctx.fillStyle = '#FFFFFF'
  ctx.font = 'bold 36px Inter, sans-serif'
  ctx.fillText(`一级推广  ${Math.round(data.l1Rate * 100)}%`, 72, 470)
  ctx.fillStyle = 'rgba(255,255,255,0.55)'
  ctx.font = '20px Inter, sans-serif'
  ctx.fillText('直接邀请的用户盈利结算后分润', 72, 500)

  ctx.fillStyle = '#FFFFFF'
  ctx.font = 'bold 36px Inter, sans-serif'
  ctx.fillText(`二级推广  ${Math.round(data.l2Rate * 100)}%`, 72, 545)
  ctx.fillStyle = 'rgba(255,255,255,0.55)'
  ctx.font = '20px Inter, sans-serif'
  ctx.fillText('下级再邀请的用户，持续获得分润', 72, 575)

  const qrSize = 220
  const qrX = (W - qrSize) / 2
  const qrY = 600
  const qrDataUrl = await QRCode.toDataURL(data.inviteUrl, {
    width: qrSize,
    margin: 2,
    color: { dark: '#000000', light: '#FFFFFF' },
  })

  ctx.fillStyle = '#FFFFFF'
  roundRect(ctx, qrX - 16, qrY - 16, qrSize + 32, qrSize + 32, 16)
  ctx.fill()

  const qrImg = await loadImage(qrDataUrl)
  ctx.drawImage(qrImg, qrX, qrY, qrSize, qrSize)

  ctx.textAlign = 'center'
  ctx.fillStyle = 'rgba(255,255,255,0.55)'
  ctx.font = '20px Inter, sans-serif'
  ctx.fillText('扫码注册 · 开启 AI 量化之旅', W / 2, qrY + qrSize + 48)

  ctx.fillStyle = '#00E676'
  ctx.font = 'bold 28px monospace'
  ctx.fillText(data.referralCode, W / 2, qrY + qrSize + 88)

  ctx.fillStyle = 'rgba(255,255,255,0.4)'
  ctx.font = '16px Inter, sans-serif'
  ctx.fillText(`邀请人：${data.displayName}  ·  UID ${data.uid}`, W / 2, qrY + qrSize + 120)

  ctx.fillStyle = 'rgba(255,255,255,0.25)'
  ctx.font = '14px Inter, sans-serif'
  const urlShort = data.inviteUrl.length > 50 ? data.inviteUrl.slice(0, 47) + '...' : data.inviteUrl
  ctx.fillText(urlShort, W / 2, qrY + qrSize + 150)

  ctx.fillStyle = 'rgba(255,255,255,0.2)'
  ctx.font = '13px Inter, sans-serif'
  ctx.fillText('投资有风险 · 请理性参与 · 平台仅提供策略托管服务', W / 2, H - 60)

  return canvas.toDataURL('image/png')
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

export function downloadPoster(dataUrl: string, filename: string) {
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  a.click()
}
