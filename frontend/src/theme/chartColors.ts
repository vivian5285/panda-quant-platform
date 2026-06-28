/** Cyber blockchain chart palette — green profit, gold accent, red loss */
export const CHART = {
  green: '#00B050',
  greenDim: 'rgba(0,176,80,0.25)',
  greenGlow: 'rgba(0,176,80,0.12)',
  gold: '#F3BA2F',
  goldDim: 'rgba(243,186,47,0.35)',
  red: '#EF4444',
  redDim: 'rgba(239,68,68,0.15)',
  neutral: '#1a1f1c',
  neutralDark: '#0c0c0e',
  pie: ['#00B050', '#F3BA2F', '#34c759', '#d4a017', '#00c45a', '#f5c842'],
  axisLine: (dark: boolean) => (dark ? 'rgba(0,176,80,0.2)' : 'rgba(0,176,80,0.15)'),
  splitLine: (dark: boolean) => (dark ? 'rgba(0,176,80,0.08)' : 'rgba(52,199,89,0.06)'),
  axisLabel: (dark: boolean) => (dark ? '#6b756d' : '#8a938e'),
  label: (dark: boolean) => (dark ? '#9ca89f' : '#5c6560'),
  pieBorder: (dark: boolean) => (dark ? '#111113' : '#fff'),
  heatmap: (dark: boolean) => (dark
    ? ['#EF4444', '#0c0c0e', '#00B050']
    : ['#EF4444', '#eef5f0', '#00B050']),
} as const
