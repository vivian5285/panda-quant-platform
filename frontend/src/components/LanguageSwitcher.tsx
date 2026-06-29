import { Globe } from 'lucide-react'
import { useI18n } from '../i18n'

export default function LanguageSwitcher() {
  const locale = useI18n(s => s.locale)
  const setLocale = useI18n(s => s.setLocale)
  const t = useI18n(s => s.t)

  const toggle = () => setLocale(locale === 'zh' ? 'en' : 'zh')

  return (
    <button
      type="button"
      className="lang-switch"
      onClick={toggle}
      title={locale === 'zh' ? t('lang.switchToEn') : t('lang.switchToZh')}
      aria-label={locale === 'zh' ? t('lang.switchToEn') : t('lang.switchToZh')}
    >
      <Globe size={15} />
      <span>{locale === 'zh' ? 'EN' : '中文'}</span>
    </button>
  )
}
