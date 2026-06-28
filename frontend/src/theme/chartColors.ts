/** Framer / Gemini chart palette — blue accent, red loss */
export const CHART = {
  green: '#3b82f6',
  greenDim: 'rgba(59,130,246,0.2)',
  greenGlow: 'rgba(59,130,246,0.1)',
  gold: '#64748b',
  goldDim: 'rgba(100,116,139,0.25)',
  red: '#dc2626',
  redDim: 'rgba(220,38,38,0.12)',
  neutral: '#0a0a0a',
  neutralDark: '#fafafa',
  pie: ['#3b82f6', '#64748b', '#2563eb', '#94a3b8', '#1d4ed8', '#475569'],
  axisLine: (dark: boolean) => (dark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'),
  splitLine: (dark: boolean) => (dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)'),
  axisLabel: (dark: boolean) => (dark ? '#737373' : '#999999'),
  label: (dark: boolean) => (dark ? '#a3a3a3' : '#666666'),
  pieBorder: (dark: boolean) => (dark ? '#141414' : '#ffffff'),
  heatmap: (dark: boolean) => (dark
    ? ['#dc2626', '#141414', '#3b82f6']
    : ['#dc2626', '#f5f5f5', '#3b82f6']),
} as const

/** P&L semantic colors (industry convention) */
export const PNL = {
  up: '#16a34a',
  down: '#dc2626',
} as const
