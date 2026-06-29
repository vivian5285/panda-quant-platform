import QRCode from 'qrcode'
import { drawGeminiLogoCanvas } from '../components/GeminiLogo'

export interface PosterLabels {
  headline: string
  badges: [string, string, string]
  commissionTitle: string
  l1Title: string
  l1Sub: string
  l2Title: string
  l2Sub: string
  scanHint: string
  inviterLine: string
  inviterUidLabel: string
  disclaimer: string
}

export interface PosterData {
  inviteUrl: string
  referralCode: string
  displayName: string
  uid: string
  l1Rate: number
  l2Rate: number
  brandName?: string
  brandTagline?: string
  posterTagline?: string
  labels: PosterLabels
}

const C = {
  primary: '#3b82f6',
  primaryLight: '#60a5fa',
  purple: '#8b5cf6',
  cyan: '#06b6d4',
  bgDeep: '#000000',
  bgBase: '#070b14',
  glass: 'rgba(20, 24, 36, 0.72)',
  glassBorder: 'rgba(96, 165, 250, 0.22)',
  text: '#ffffff',
  textSoft: 'rgba(255,255,255,0.68)',
  textMuted: 'rgba(255,255,255,0.42)',
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rad = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rad, y)
  ctx.arcTo(x + w, y, x + w, y + h, rad)
  ctx.arcTo(x + w, y + h, x, y + h, rad)
  ctx.arcTo(x, y + h, x, y, rad)
  ctx.arcTo(x, y, x + w, y, rad)
  ctx.closePath()
}

function brandGradient(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number) {
  const g = ctx.createLinearGradient(x1, y1, x2, y2)
  g.addColorStop(0, C.primaryLight)
  g.addColorStop(0.45, C.primary)
  g.addColorStop(1, C.purple)
  return g
}

function drawStarField(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const seed = [0.12, 0.28, 0.41, 0.55, 0.63, 0.71, 0.82, 0.91, 0.18, 0.37, 0.49, 0.66, 0.74, 0.88, 0.95]
  seed.forEach((sx, i) => {
    const sy = (i * 0.067 + 0.08) % 1
    const px = sx * w
    const py = sy * h
    const r = i % 3 === 0 ? 1.6 : 1
    ctx.beginPath()
    ctx.arc(px, py, r, 0, Math.PI * 2)
    ctx.fillStyle = i % 4 === 0 ? 'rgba(96,165,250,0.55)' : 'rgba(255,255,255,0.18)'
    ctx.fill()
  })
}

function drawConstellationDecor(ctx: CanvasRenderingContext2D, w: number, h: number) {
  ctx.save()
  ctx.strokeStyle = 'rgba(59,130,246,0.12)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(w * 0.08, h * 0.22)
  ctx.lineTo(w * 0.18, h * 0.16)
  ctx.lineTo(w * 0.28, h * 0.24)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(w * 0.72, h * 0.12)
  ctx.lineTo(w * 0.82, h * 0.18)
  ctx.lineTo(w * 0.9, h * 0.11)
  ctx.stroke()
  ctx.restore()
}

function drawGlassPanel(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number,
) {
  roundRect(ctx, x, y, w, h, r)
  ctx.fillStyle = C.glass
  ctx.fill()
  ctx.strokeStyle = C.glassBorder
  ctx.lineWidth = 1
  ctx.stroke()
}

function fillGradientText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  font: string,
  align: CanvasTextAlign = 'center',
) {
  ctx.font = font
  ctx.textAlign = align
  const metrics = ctx.measureText(text)
  const left = align === 'center' ? x - metrics.width / 2 : x
  const grad = brandGradient(ctx, left, y - 20, left + metrics.width, y + 8)
  ctx.fillStyle = grad
  ctx.fillText(text, x, y)
}

function drawValuePill(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  text: string,
) {
  const h = 36
  roundRect(ctx, x, y, w, h, 18)
  ctx.fillStyle = 'rgba(59,130,246,0.1)'
  ctx.fill()
  ctx.strokeStyle = 'rgba(139,92,246,0.28)'
  ctx.lineWidth = 1
  ctx.stroke()

  ctx.beginPath()
  ctx.arc(x + 18, y + h / 2, 4, 0, Math.PI * 2)
  ctx.fillStyle = brandGradient(ctx, x, y, x + w, y + h)
  ctx.fill()

  ctx.fillStyle = C.textSoft
  ctx.font = '500 15px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText(text, x + 32, y + 23)
}

function drawRateColumn(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  rate: number,
  title: string,
  sub: string,
) {
  const pct = `${Math.round(rate * 100)}%`
  fillGradientText(ctx, pct, x + w / 2, y + 44, 'bold 40px Inter, system-ui, sans-serif')
  ctx.fillStyle = C.text
  ctx.font = '600 16px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(title, x + w / 2, y + 78)
  ctx.fillStyle = C.textMuted
  ctx.font = '13px Inter, "PingFang SC", system-ui, sans-serif'
  wrapText(ctx, sub, x + w / 2, y + 98, w - 16, 18)
}

function wrapText(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  y: number,
  maxW: number,
  lineH: number,
) {
  ctx.textAlign = 'center'
  const chars = [...text]
  let line = ''
  const lines: string[] = []
  for (const ch of chars) {
    const test = line + ch
    if (ctx.measureText(test).width > maxW && line) {
      lines.push(line)
      line = ch
    } else {
      line = test
    }
  }
  if (line) lines.push(line)
  lines.forEach((ln, i) => ctx.fillText(ln, cx, y + i * lineH))
}

function drawInviterAvatar(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  r: number,
  name: string,
) {
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fillStyle = brandGradient(ctx, cx - r, cy - r, cx + r, cy + r)
  ctx.fill()
  const initial = (name.trim()[0] || 'G').toUpperCase()
  ctx.fillStyle = '#ffffff'
  ctx.font = `bold ${Math.round(r * 0.9)}px Inter, system-ui, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(initial, cx, cy + 1)
  ctx.textBaseline = 'alphabetic'
}

function drawQrFrame(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  size: number,
) {
  const pad = 18
  const outer = size + pad * 2
  const x = cx - outer / 2
  const y = cy - outer / 2

  roundRect(ctx, x - 4, y - 4, outer + 8, outer + 8, 24)
  ctx.strokeStyle = brandGradient(ctx, x, y, x + outer, y + outer)
  ctx.lineWidth = 3
  ctx.stroke()

  roundRect(ctx, x, y, outer, outer, 20)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
}

export async function generateInvitePoster(data: PosterData): Promise<string> {
  const W = 750
  const H = 1334
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  const L = data.labels

  const bg = ctx.createLinearGradient(0, 0, W * 0.3, H)
  bg.addColorStop(0, C.bgDeep)
  bg.addColorStop(0.35, C.bgBase)
  bg.addColorStop(1, '#030308')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  const glowBlue = ctx.createRadialGradient(W * 0.15, H * 0.08, 0, W * 0.15, H * 0.08, 420)
  glowBlue.addColorStop(0, 'rgba(59,130,246,0.22)')
  glowBlue.addColorStop(1, 'rgba(59,130,246,0)')
  ctx.fillStyle = glowBlue
  ctx.fillRect(0, 0, W, H)

  const glowPurple = ctx.createRadialGradient(W * 0.88, H * 0.42, 0, W * 0.88, H * 0.42, 380)
  glowPurple.addColorStop(0, 'rgba(139,92,246,0.16)')
  glowPurple.addColorStop(1, 'rgba(139,92,246,0)')
  ctx.fillStyle = glowPurple
  ctx.fillRect(0, 0, W, H)

  drawStarField(ctx, W, H)
  drawConstellationDecor(ctx, W, H)

  ctx.strokeStyle = 'rgba(96,165,250,0.18)'
  ctx.lineWidth = 1.5
  roundRect(ctx, 24, 24, W - 48, H - 48, 32)
  ctx.stroke()

  drawGeminiLogoCanvas(ctx, W / 2, 98, 88)

  ctx.fillStyle = C.text
  ctx.font = 'bold 38px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(data.brandName || 'GEMINI AI', W / 2, 168)

  ctx.fillStyle = C.textSoft
  ctx.font = '16px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(data.brandTagline || '', W / 2, 198)

  fillGradientText(
    ctx,
    L.headline,
    W / 2,
    258,
    'bold 32px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif',
  )

  ctx.fillStyle = C.textSoft
  ctx.font = '18px Inter, "PingFang SC", system-ui, sans-serif'
  wrapText(ctx, data.posterTagline || '', W / 2, 298, W - 120, 26)

  const pillW = W - 96
  const pillX = 48
  L.badges.forEach((badge, i) => drawValuePill(ctx, pillX, 340 + i * 44, pillW, badge))

  const commY = 478
  const commH = 248
  drawGlassPanel(ctx, 40, commY, W - 80, commH, 22)

  ctx.fillStyle = C.cyan
  ctx.font = '600 14px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText(L.commissionTitle, 64, commY + 36)

  ctx.strokeStyle = 'rgba(148,163,184,0.15)'
  ctx.beginPath()
  ctx.moveTo(W / 2, commY + 52)
  ctx.lineTo(W / 2, commY + commH - 28)
  ctx.stroke()

  const colW = (W - 80) / 2
  drawRateColumn(ctx, 40, commY + 56, colW, data.l1Rate, L.l1Title, L.l1Sub)
  drawRateColumn(ctx, 40 + colW, commY + 56, colW, data.l2Rate, L.l2Title, L.l2Sub)

  const qrSize = 220
  const qrY = commY + commH + 36
  const qrX = (W - qrSize) / 2

  const qrDataUrl = await QRCode.toDataURL(data.inviteUrl, {
    width: qrSize,
    margin: 1,
    color: { dark: '#0f172a', light: '#ffffff' },
  })

  drawQrFrame(ctx, W / 2, qrY + qrSize / 2 + 18, qrSize)
  const qrImg = await loadImage(qrDataUrl)
  ctx.drawImage(qrImg, qrX, qrY + 18, qrSize, qrSize)

  ctx.textAlign = 'center'
  ctx.fillStyle = C.textSoft
  ctx.font = '600 20px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(L.scanHint, W / 2, qrY + qrSize + 58)

  ctx.fillStyle = C.textMuted
  ctx.font = '600 15px ui-monospace, monospace'
  ctx.fillText(data.referralCode, W / 2, qrY + qrSize + 86)

  const invY = qrY + qrSize + 108
  drawGlassPanel(ctx, 56, invY, W - 112, 96, 20)
  drawInviterAvatar(ctx, 108, invY + 48, 28, data.displayName)
  ctx.textAlign = 'left'
  ctx.fillStyle = C.text
  ctx.font = '600 18px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(data.displayName, 152, invY + 40)
  ctx.fillStyle = C.textSoft
  ctx.font = '14px Inter, system-ui, sans-serif'
  ctx.fillText(L.inviterLine, 152, invY + 64)
  ctx.fillStyle = brandGradient(ctx, 152, invY + 72, W - 80, invY + 88)
  ctx.font = '600 13px ui-monospace, monospace'
  ctx.fillText(L.inviterUidLabel, 152, invY + 84)

  ctx.fillStyle = C.textMuted
  ctx.font = '12px Inter, system-ui, sans-serif'
  ctx.textAlign = 'center'
  const urlShort = data.inviteUrl.length > 48 ? data.inviteUrl.slice(0, 45) + '…' : data.inviteUrl
  ctx.fillText(urlShort, W / 2, invY + 118)

  ctx.fillStyle = 'rgba(255,255,255,0.28)'
  ctx.font = '11px Inter, "PingFang SC", system-ui, sans-serif'
  wrapText(ctx, L.disclaimer, W / 2, H - 56, W - 100, 16)

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
