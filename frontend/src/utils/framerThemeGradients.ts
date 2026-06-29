import type { Theme } from '../store/theme'

/** Accent-tinted card background for landing stat / workflow cells */
export function accentCardGradient(accent: string, theme: Theme): string {
  if (theme === 'light') {
    return `linear-gradient(160deg, color-mix(in srgb, ${accent} 16%, #ffffff) 0%, color-mix(in srgb, ${accent} 7%, #f8fafc) 48%, #f1f5f9 100%)`
  }
  return `linear-gradient(160deg, color-mix(in srgb, ${accent} 20%, #000) 0%, color-mix(in srgb, ${accent} 8%, #0c0c0c) 50%, #141414 100%)`
}

/** Multi-stop panel gradient (showcase tiles, partners) */
export function panelGradient(stops: string, theme: Theme): string {
  if (theme === 'light') {
    return stops
      .replace(/#000\b/g, '#f8fafc')
      .replace(/#0a0a0a/g, '#f1f5f9')
      .replace(/#111827/g, '#e2e8f0')
      .replace(/#141414/g, '#ffffff')
      .replace(/#0c0c0c/g, '#f8fafc')
      .replace(/100%\)/g, '100%)')
  }
  return stops
}
