import QRCode from 'qrcode'
import { drawGeminiLogoCanvas } from '../components/GeminiLogo'
import { displayReferralCode } from './referralCode'

export type PosterTheme = 'dark' | 'light'

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
  theme?: PosterTheme
}

interface PosterPalette {
  primary: string
  primaryLight: string
  purple: string
  cyan: string
  bgDeep: string
  bgBase: string
  glass: string
  glassHi: string
  glassBorder: string
  text: string
  textSoft: string
  textMuted: string
  qrDark: string
  qrLight: string
  codePillBg: string
  codePillBorder: string
  ambientSpots: [number, number, number, string][]
  gridAlpha: number
  showStars: boolean
  outerBorder: string
  logoVariant: 'dark' | 'light'
}

const PALETTES: Record<PosterTheme, PosterPalette> = {
  dark: {
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
    qrDark: '#0f172a',
    qrLight: '#ffffff',
    codePillBg: 'rgba(59,130,246,0.12)',
    codePillBorder: 'rgba(96,165,250,0.28)',
    ambientSpots: [
      [0.12, 0.1, 480, 'rgba(59,130,246,0.2)'],
      [0.88, 0.35, 420, 'rgba(167,139,250,0.14)'],
      [0.5, 0.72, 360, 'rgba(34,211,238,0.08)'],
    ],
    gridAlpha: 0.04,
    showStars: true,
    outerBorder: 'rgba(148,163,184,0.12)',
    logoVariant: 'dark',
  },
  light: {
    primary: '#2563eb',
    primaryLight: '#3b82f6',
    purple: '#6366f1',
    cyan: '#0891b2',
    bgDeep: '#f8fafc',
    bgBase: '#eef2ff',
    glass: 'rgba(255, 255, 255, 0.92)',
    glassHi: 'rgba(248, 250, 252, 0.95)',
    glassBorder: 'rgba(148, 163, 184, 0.22)',
    text: '#0f172a',
    textSoft: 'rgba(15,23,42,0.78)',
    textMuted: 'rgba(100,116,139,0.95)',
    qrDark: '#0f172a',
    qrLight: '#ffffff',
    codePillBg: 'rgba(37,99,235,0.08)',
    codePillBorder: 'rgba(37,99,235,0.22)',
    ambientSpots: [
      [0.15, 0.12, 400, 'rgba(59,130,246,0.12)'],
      [0.85, 0.28, 380, 'rgba(99,102,241,0.1)'],
      [0.5, 0.85, 320, 'rgba(14,165,233,0.06)'],
    ],
    gridAlpha: 0.06,
    showStars: false,
    outerBorder: 'rgba(148,163,184,0.25)',
    logoVariant: 'light',
  },
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

function brandGradient(ctx: CanvasRenderingContext2D, P: PosterPalette, x1: number, y1: number, x2: number, y2: number) {
  const g = ctx.createLinearGradient(x1, y1, x2, y2)
  g.addColorStop(0, P.primaryLight)
  g.addColorStop(0.5, P.primary)
  g.addColorStop(1, P.purple)
  return g
}

function drawAmbient(ctx: CanvasRenderingContext2D, W: number, H: number, P: PosterPalette, theme: PosterTheme) {
  const bg = ctx.createLinearGradient(0, 0, W * 0.35, H)
  if (theme === 'light') {
    bg.addColorStop(0, P.bgDeep)
    bg.addColorStop(0.5, '#ffffff')
    bg.addColorStop(1, P.bgBase)
  } else {
    bg.addColorStop(0, P.bgDeep)
    bg.addColorStop(0.45, P.bgBase)
    bg.addColorStop(1, '#030712')
  }
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, W, H)

  for (const [sx, sy, r, color] of P.ambientSpots) {
    const g = ctx.createRadialGradient(sx * W, sy * H, 0, sx * W, sy * H, r)
    g.addColorStop(0, color)
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, W, H)
  }

  ctx.save()
  ctx.globalAlpha = P.gridAlpha
  ctx.strokeStyle = theme === 'light' ? '#94a3b8' : '#ffffff'
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

function drawStarField(ctx: CanvasRenderingContext2D, w: number, h: number, P: PosterPalette) {
  const pts = [
    [0.08, 0.15], [0.22, 0.08], [0.41, 0.19], [0.67, 0.11], [0.91, 0.17],
    [0.15, 0.42], [0.78, 0.38], [0.33, 0.58], [0.56, 0.51], [0.89, 0.62],
  ]
  pts.forEach(([sx, sy], i) => {
    ctx.beginPath()
    ctx.arc(sx * w, sy * h, i % 3 === 0 ? 1.8 : 1.1, 0, Math.PI * 2)
    ctx.fillStyle = i % 2 === 0 ? `${P.primaryLight}73` : 'rgba(255,255,255,0.15)'
    ctx.fill()
  })
}

function fillGradientText(
  ctx: CanvasRenderingContext2D,
  P: PosterPalette,
  text: string,
  x: number,
  y: number,
  font: string,
  align: CanvasTextAlign = 'center',
  theme: PosterTheme,
) {
  ctx.font = font
  ctx.textAlign = align
  if (theme === 'light') {
    ctx.fillStyle = P.text
    ctx.fillText(text, x, y)
    return
  }
  const metrics = ctx.measureText(text)
  const left = align === 'center' ? x - metrics.width / 2 : x
  ctx.fillStyle = brandGradient(ctx, P, left, y - 24, left + metrics.width, y + 6)
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

function drawGlassPanel(ctx: CanvasRenderingContext2D, P: PosterPalette, x: number, y: number, w: number, h: number, r: number) {
  roundRect(ctx, x, y, w, h, r)
  ctx.fillStyle = P.glass
  ctx.fill()
  ctx.strokeStyle = P.glassBorder
  ctx.lineWidth = 1
  ctx.stroke()
}

function drawAdvantageCard(
  ctx: CanvasRenderingContext2D,
  P: PosterPalette,
  x: number,
  y: number,
  w: number,
  h: number,
  index: number,
  title: string,
  desc: string,
) {
  drawGlassPanel(ctx, P, x, y, w, h, 18)

  const barX = x + 20
  const barY = y + 22
  roundRect(ctx, barX, barY, 4, h - 44, 2)
  ctx.fillStyle = brandGradient(ctx, P, barX, barY, barX, barY + h - 44)
  ctx.fill()

  const accentColors = [P.primaryLight, P.cyan, P.purple]
  ctx.beginPath()
  ctx.arc(x + w - 36, y + 36, 18, 0, Math.PI * 2)
  ctx.fillStyle = `${accentColors[index % 3]}22`
  ctx.fill()
  ctx.strokeStyle = `${accentColors[index % 3]}55`
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.fillStyle = accentColors[index % 3]
  ctx.font = '600 11px ui-monospace, monospace'
  ctx.textAlign = 'center'
  ctx.fillText(`0${index + 1}`, x + w - 36, y + 40)

  ctx.textAlign = 'left'
  ctx.fillStyle = P.text
  ctx.font = '600 19px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(title, x + 40, y + 38)

  ctx.fillStyle = P.textMuted
  ctx.font = '14px Inter, "PingFang SC", system-ui, sans-serif'
  wrapText(ctx, desc, x + 40, y + 62, w - 88, 20, 'left')
}

function drawInviterAvatar(ctx: CanvasRenderingContext2D, P: PosterPalette, cx: number, cy: number, r: number, name: string) {
  ctx.beginPath()
  ctx.arc(cx, cy, r, 0, Math.PI * 2)
  ctx.fillStyle = brandGradient(ctx, P, cx - r, cy - r, cx + r, cy + r)
  ctx.fill()
  const initial = (name.trim()[0] || 'G').toUpperCase()
  ctx.fillStyle = '#ffffff'
  ctx.font = `bold ${Math.round(r * 0.88)}px Inter, system-ui, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(initial, cx, cy + 1)
  ctx.textBaseline = 'alphabetic'
}

function drawQrFrame(ctx: CanvasRenderingContext2D, P: PosterPalette, cx: number, cy: number, size: number) {
  const pad = 20
  const outer = size + pad * 2
  const x = cx - outer / 2
  const y = cy - outer / 2

  roundRect(ctx, x - 6, y - 6, outer + 12, outer + 12, 28)
  ctx.strokeStyle = brandGradient(ctx, P, x, y, x + outer, y + outer)
  ctx.lineWidth = 2.5
  ctx.stroke()

  roundRect(ctx, x, y, outer, outer, 22)
  ctx.fillStyle = '#ffffff'
  ctx.fill()
}

export async function generateInvitePoster(data: PosterData): Promise<string> {
  const theme: PosterTheme = data.theme ?? 'dark'
  const P = PALETTES[theme]
  const W = 750
  const H = 1334
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  const L = data.labels
  const displayCode = displayReferralCode(data.referralCode)

  drawAmbient(ctx, W, H, P, theme)
  if (P.showStars) drawStarField(ctx, W, H, P)

  ctx.strokeStyle = P.outerBorder
  ctx.lineWidth = 1
  roundRect(ctx, 28, 28, W - 56, H - 56, 36)
  ctx.stroke()

  drawGeminiLogoCanvas(ctx, W / 2, 108, 96, P.logoVariant)

  ctx.fillStyle = P.text
  ctx.font = 'bold 40px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(data.brandName || 'GEMINI AI', W / 2, 182)

  ctx.fillStyle = P.textSoft
  ctx.font = '15px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(data.brandTagline || '', W / 2, 214)

  ctx.strokeStyle = brandGradient(ctx, P, W * 0.25, 232, W * 0.75, 232)
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(W * 0.2, 232)
  ctx.lineTo(W * 0.8, 232)
  ctx.stroke()

  fillGradientText(
    ctx, P, L.headline, W / 2, 278,
    'bold 34px "Plus Jakarta Sans", Inter, "PingFang SC", system-ui, sans-serif',
    'center', theme,
  )

  ctx.fillStyle = P.textSoft
  ctx.font = '17px Inter, "PingFang SC", system-ui, sans-serif'
  wrapText(ctx, data.posterTagline || '', W / 2, 318, W - 128, 26)

  const advTitleY = 368
  ctx.fillStyle = theme === 'light' ? P.primary : P.cyan
  ctx.font = '600 13px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(L.advantagesTitle.toUpperCase(), W / 2, advTitleY)

  const cardX = 52
  const cardW = W - 104
  const cardH = 96
  const cardGap = 14
  L.advantages.forEach((adv, i) => {
    drawAdvantageCard(ctx, P, cardX, advTitleY + 18 + i * (cardH + cardGap), cardW, cardH, i, adv.title, adv.desc)
  })

  const advBlockBottom = advTitleY + 18 + 3 * (cardH + cardGap) - cardGap
  const qrSize = 228
  const qrY = advBlockBottom + 36

  const qrDataUrl = await QRCode.toDataURL(data.inviteUrl, {
    width: qrSize,
    margin: 1,
    color: { dark: P.qrDark, light: P.qrLight },
  })

  drawQrFrame(ctx, P, W / 2, qrY + qrSize / 2 + 20, qrSize)
  const qrImg = await loadImage(qrDataUrl)
  ctx.drawImage(qrImg, (W - qrSize) / 2, qrY + 20, qrSize, qrSize)

  ctx.textAlign = 'center'
  ctx.fillStyle = P.text
  ctx.font = '600 21px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(L.scanHint, W / 2, qrY + qrSize + 68)

  const pillW = Math.max(236, ctx.measureText(displayCode).width + 48)
  roundRect(ctx, W / 2 - pillW / 2, qrY + qrSize + 82, pillW, 34, 17)
  ctx.fillStyle = P.codePillBg
  ctx.fill()
  ctx.strokeStyle = P.codePillBorder
  ctx.lineWidth = 1
  ctx.stroke()
  ctx.fillStyle = theme === 'light' ? P.primary : P.primaryLight
  ctx.font = '600 14px ui-monospace, monospace'
  ctx.fillText(displayCode, W / 2, qrY + qrSize + 104)

  const invY = qrY + qrSize + 132
  drawGlassPanel(ctx, P, 56, invY, W - 112, 88, 20)
  drawInviterAvatar(ctx, P, 108, invY + 44, 26, data.displayName)
  ctx.textAlign = 'left'
  ctx.fillStyle = P.text
  ctx.font = '600 17px Inter, "PingFang SC", system-ui, sans-serif'
  ctx.fillText(data.displayName, 148, invY + 36)
  ctx.fillStyle = P.textSoft
  ctx.font = '13px Inter, system-ui, sans-serif'
  ctx.fillText(L.inviterLine, 148, invY + 58)
  ctx.fillStyle = P.textMuted
  ctx.font = '600 12px ui-monospace, monospace'
  ctx.fillText(L.inviterUidLabel, 148, invY + 76)

  ctx.fillStyle = P.textMuted
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
