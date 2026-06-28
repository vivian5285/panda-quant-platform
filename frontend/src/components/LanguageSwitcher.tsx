import { Globe } from 'lucide-react'
import { useI18n } from '../i18n'

export default function LanguageSwitcher() {
  const locale = useI18n(s => s.locale)
  const setLocale = useI18n(s => s.setLocale)

  const toggle = () => setLocale(locale === 'zh' ? 'en' : 'zh')

  return (
    <button type="button" className="lang-switch" onClick={toggle} title={locale === 'zh' ? 'English' : '中文'}>
      <Globe size={15} />
      <span>{locale === 'zh' ? 'EN' : '中'}</span>
    </button>
  )
}
