import { create } from 'zustand'
import zh from './locales/zh'
import en from './locales/en'

export type Locale = 'zh' | 'en'
const locales = { zh, en }

function lookup(obj: Record<string, unknown>, path: string): string | undefined {
  const val = path.split('.').reduce<unknown>((o, k) => (o as Record<string, unknown>)?.[k], obj)
  return typeof val === 'string' ? val : undefined
}

function detectLocale(): Locale {
  const saved = localStorage.getItem('locale') as Locale | null
  if (saved === 'zh' || saved === 'en') return saved
  return navigator.language.startsWith('zh') ? 'zh' : 'en'
}

function syncDocumentMeta(locale: Locale) {
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
  const titles = locales[locale] as { meta?: { title?: string } }
  const title = titles.meta?.title
  if (title) document.title = title
  const ogLocale = document.querySelector('meta[property="og:locale"]')
  if (ogLocale) ogLocale.setAttribute('content', locale === 'zh' ? 'zh_CN' : 'en_US')
}

interface I18nState {
  locale: Locale
  setLocale: (l: Locale) => void
  t: (key: string, params?: Record<string, string | number>) => string
}

export const useI18n = create<I18nState>((set, get) => ({
  locale: detectLocale(),
  setLocale: (locale) => {
    localStorage.setItem('locale', locale)
    syncDocumentMeta(locale)
    set({ locale })
  },
  t: (key, params) => {
    let str = lookup(locales[get().locale] as unknown as Record<string, unknown>, key)
      || lookup(locales.zh as unknown as Record<string, unknown>, key)
      || key
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        str = str.replace(`{${k}}`, String(v))
      }
    }
    return str
  },
}))

/** Prefer this over `useI18n(s => s.t)` — subscribes to locale so UI re-renders on language switch */
export function useTranslation() {
  const locale = useI18n(s => s.locale)
  const t = useI18n(s => s.t)
  const setLocale = useI18n(s => s.setLocale)
  return { t, locale, setLocale }
}

export function initI18n() {
  const locale = detectLocale()
  syncDocumentMeta(locale)
  useI18n.setState({ locale })
}

export function localeDate(iso: string, locale: Locale) {
  return new Date(iso).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US')
}
