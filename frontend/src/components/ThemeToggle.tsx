import { motion } from 'framer-motion'
import { Sun, Moon } from 'lucide-react'
import { useTheme } from '../store/theme'
import { useI18n } from '../i18n'

export default function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const { t } = useI18n()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={isDark ? t('theme.light') : t('theme.dark')}
      title={isDark ? t('theme.light') : t('theme.dark')}
    >
      <motion.div
        className="theme-toggle-track"
        layout
        transition={{ type: 'spring', stiffness: 500, damping: 35 }}
      >
        <motion.div
          className="theme-toggle-thumb"
          layout
          transition={{ type: 'spring', stiffness: 500, damping: 35 }}
          animate={{ x: isDark ? 28 : 0 }}
        >
          <motion.span
            key={theme}
            initial={{ rotate: -30, opacity: 0, scale: 0.6 }}
            animate={{ rotate: 0, opacity: 1, scale: 1 }}
            transition={{ duration: 0.25 }}
            className="theme-toggle-icon"
          >
            {isDark ? <Moon size={14} /> : <Sun size={14} />}
          </motion.span>
        </motion.div>
        <Sun size={12} className="theme-toggle-bg-icon theme-toggle-sun" />
        <Moon size={12} className="theme-toggle-bg-icon theme-toggle-moon" />
      </motion.div>
    </button>
  )
}
