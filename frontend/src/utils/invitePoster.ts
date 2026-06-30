import QRCode from 'qrcode'
import { drawGeminiLogoCanvas } from '../components/GeminiLogo'

export interface PosterAdvantage {
  title: string
  desc: string
}

export interface PosterLabels {
  headline: string
  advantagesTitle: string
  advantages: [PosterAdvantage, PosterAdvantage, PosterAdvantage]
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
  brandName?: string
  brandTagline?: string
  posterTagline?: string
  labels: PosterLabels
}

const C = {
  primary: '#3b82f6',
  primaryLight: '#93c5fd',
  purple: '#a78bfa',
  cyan: '#22d3ee',
  bgDeep: '#020617',
  bgBase: '#0a0f1e',
  glass: 'rgba(15, 23, 42, 0.65)',
  glassHi: 'rgba(30, 41, 59, 0.55)',
  glassBorder: 'rgba(148, 163, 184, 0.14)',
  text: '#f8fafc',
  textSoft: 'rgba(248,250,252,0.78)',
  textMuted: 'rgba(148,163,184,0.85)',
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
  g.addColorStop(0.5, C.primary)
  g.addColorStop(1, C.purple)
  return g
}

function drawAmbient(ctx: CanvasRenderingContext2D, W: number, H: number) {
  const bg = ctx.createLinearGradient(0, 0, W * 0.4, H)
  bg.addColorStop(0, C.bgDeep)
  bg.addColorStop(0.45, C.bgBase)
  bg.addColorStop(1, '#030712')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  const spots: [number, number, number, string][] = [
    [0.12, 0.1, 480, 'rgba(59,130,246,0.2)'],
    [0.88, 0.35, 420, 'rgba(167,139,250,0.14)'],
    [0.5, 0.72, 360, 'rgba(34,211,238,0.08)'],
  ]
  for (const [sx, sy, r, color] of spots) {
    const g = ctx.createRadialGradient(sx * W, sy * H, 0, sx * W, sy * H, r)
    g.addColorStop(0, color)
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, W, H)
  }

  ctx.save()
  ctx.globalAlpha = 0.04
  ctx.strokeStyle = '#ffffff'
  ctx.lineWidth = 1
  for (let i = 0; i < 12; i++) {
    const y = 80 + i * 110
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(W, y)
    ctx.stroke()
  }
  ctx.restore()
}

function drawStarField(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const pts = [
    [0.08, 0.15], [0.22, 0.08], [0.41, 0.19], [0.67, 0.11], [0.91, 0.17],
    [0.15, 0.42], [0.78, 0.38], [0.33, 0.58], [0.56, 0.51], [0.89, 0.62],
  ]
  pts.forEach(([sx, sy], i) => {
    ctx.beginPath()
    ctx.arc(sx * w, sy * h, i % 3 === 0 ? 1.8 : 1.1, 0, Math.PI * 2)
    ctx.fillStyle = i % 2 === 0 ? 'rgba(147,197,253,0.45)' : 'rgba(255,255,255,0.15)'
    ctx.fill()
  })
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
  ctx.fillStyle = brandGradient(ctx, left, y - 24, left + metrics.width, y + 6)
  ctx.fillText(text, x, y)
}

function wrapText(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  y: number,
  maxW: number,
  lineH: number,
  align: CanvasTextAlign = 'center',
) {
  ctx.textAlign = align
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

function drawGlassPanel(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  roundRect(ctx, x, y, w, h, r)
  ctx.fillStyle = C.glass
  ctx.fill()
  ctx.strokeStyle = C.glassBorder
  ctx.lineWidth = 1
  ctx.stroke()
}

function drawAdvantageCard(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  index: number,
  title: string,
  desc: string,
) {
  drawGlassPanel(ctx, x, y, w, h, 18)

  const barX = x + 20
  const barY = y + 22
  roundRect(ctx, barX, barY, 4, h - 44, 2)
  ctx.fillStyle = brandGradient(ctx, barX, barY, barX, barY + h - 44)
  ctx.fill()

  const accentColors = [C.primaryLight, C.cyan, C.purple]
  ctx.beginPath()
  ctx.arc(x + w - 36, y + 36, 18, 0, Math.PI * 2)
  ctx.fillStyle = `${accentColors[index % 3]}18`
  ctx.fill()
  ctx.strokeStyle = `${accentColors[index % 3]}44`
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.fillStyle = accentColors[index % 3]
  ctx.font = '600 11px ui-monospace, monospace'
  ctx.textAlign = 'center'
  ctx.fillText(`0${index + 1}`, x + w - 36, y + 40)

  ctx.textAlign = 'left'
  ctx.fillStyle = C.text
  ctx.font = '600 19px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(title, x + 40, y + 38)

  ctx.fillStyle = C.textMuted
  ctx.font = '14px Inter, "PingFang SC", system-ui, sans-serif'
  wrapText(ctx, desc, x + 40, y + 62, w - 88, 20, 'left')
}

function drawInviterAvatar(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number, name: string) {
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fillStyle = brandGradient(ctx, cx - r, cy - r, cx + r, cy + r)
  ctx.fill()
  const initial = (name.trim()[0] || 'G').toUpperCase()
  ctx.fillStyle = '#ffffff'
  ctx.font = `bold ${Math.round(r * 0.88)}px Inter, system-ui, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(initial, cx, cy + 1)
  ctx.textBaseline = 'alphabetic'
}

function drawQrFrame(ctx: CanvasRenderingContext2D, cx: number, cy: number, size: number) {
  const pad = 20
  const outer = size + pad * 2
  const x = cx - outer / 2
  const y = cy - outer / 2

  roundRect(ctx, x - 6, y - 6, outer + 12, outer + 12, 28)
  ctx.strokeStyle = brandGradient(ctx, x, y, x + outer, y + outer)
  ctx.lineWidth = 2.5
  ctx.stroke()

  roundRect(ctx, x, y, outer, outer, 22)
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

  drawAmbient(ctx, W, H)
  drawStarField(ctx, W, H)

  ctx.strokeStyle = 'rgba(148,163,184,0.12)'
  ctx.lineWidth = 1
  roundRect(ctx, 28, 28, W - 56, H - 56, 36)
  ctx.stroke()

  drawGeminiLogoCanvas(ctx, W / 2, 108, 96)

  ctx.fillStyle = C.text
  ctx.font = 'bold 40px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(data.brandName || 'GEMINI AI', W / 2, 182)

  ctx.fillStyle = C.textSoft
  ctx.font = '15px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(data.brandTagline || '', W / 2, 214)

  ctx.strokeStyle = brandGradient(ctx, W * 0.25, 232, W * 0.75, 232)
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(W * 0.2, 232)
  ctx.lineTo(W * 0.8, 232)
  ctx.stroke()

  fillGradientText(
    ctx,
    L.headline,
    W / 2,
    278,
    'bold 34px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif',
  )

  ctx.fillStyle = C.textSoft
  ctx.font = '17px Inter, "PingFang SC", system-ui, sans-serif'
  wrapText(ctx, data.posterTagline || '', W / 2, 318, W - 128, 26)

  const advTitleY = 368
  ctx.fillStyle = C.cyan
  ctx.font = '600 13px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(L.advantagesTitle.toUpperCase(), W / 2, advTitleY)

  const cardX = 52
  const cardW = W - 104
  const cardH = 96
  const cardGap = 14
  L.advantages.forEach((adv, i) => {
    drawAdvantageCard(ctx, cardX, advTitleY + 18 + i * (cardH + cardGap), cardW, cardH, i, adv.title, adv.desc)
  })

  const advBlockBottom = advTitleY + 18 + 3 * (cardH + cardGap) - cardGap
  const qrSize = 228
  const qrY = advBlockBottom + 36

  const qrDataUrl = await QRCode.toDataURL(data.inviteUrl, {
    width: qrSize,
    margin: 1,
    color: { dark: '#0f172a', light: '#ffffff' },
  })

  drawQrFrame(ctx, W / 2, qrY + qrSize / 2 + 20, qrSize)
  const qrImg = await loadImage(qrDataUrl)
  ctx.drawImage(qrImg, (W - qrSize) / 2, qrY + 20, qrSize, qrSize)

  ctx.textAlign = 'center'
  ctx.fillStyle = C.text
  ctx.font = '600 21px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(L.scanHint, W / 2, qrY + qrSize + 68)

  roundRect(ctx, W / 2 - 118, qrY + qrSize + 82, 236, 34, 17)
  ctx.fillStyle = 'rgba(59,130,246,0.12)'
  ctx.fill()
  ctx.strokeStyle = 'rgba(96,165,250,0.28)'
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.fillStyle = C.primaryLight
  ctx.font = '600 14px ui-monospace, monospace'
  ctx.fillText(data.referralCode, W / 2, qrY + qrSize + 104)

  const invY = qrY + qrSize + 132
  drawGlassPanel(ctx, 56, invY, W - 112, 88, 20)
  drawInviterAvatar(ctx, 108, invY + 44, 26, data.displayName)
  ctx.textAlign = 'left'
  ctx.fillStyle = C.text
  ctx.font = '600 17px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(data.displayName, 148, invY + 36)
  ctx.fillStyle = C.textSoft
  ctx.font = '13px Inter, system-ui, sans-serif'
  ctx.fillText(L.inviterLine, 148, invY + 58)
  ctx.fillStyle = C.textMuted
  ctx.font = '600 12px ui-monospace, monospace'
  ctx.fillText(L.inviterUidLabel, 148, invY + 76)

  ctx.fillStyle = 'rgba(148,163,184,0.55)'
  ctx.font = '11px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'center'
  wrapText(ctx, L.disclaimer, W / 2, H - 52, W - 120, 15)

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
