import { create } from 'zustand'

export type Theme = 'light' | 'dark'

interface ThemeState {
  theme: Theme
  setTheme: (t: Theme) => void
  toggle: () => void
}

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', theme === 'light' ? '#ffffff' : '#050816')
}

function detectTheme(): Theme {
  const saved = localStorage.getItem('theme') as Theme | null
  if (saved === 'light' || saved === 'dark') return saved
  return 'dark'
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: 'dark',
  setTheme: (theme) => {
    localStorage.setItem('theme', theme)
    applyTheme(theme)
    set({ theme })
  },
  toggle: () => {
    const next = get().theme === 'light' ? 'dark' : 'light'
    get().setTheme(next)
  },
}))

export function initTheme() {
  const theme = detectTheme()
  applyTheme(theme)
  useTheme.setState({ theme })
}
