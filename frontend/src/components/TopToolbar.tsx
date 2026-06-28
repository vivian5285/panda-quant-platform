import LanguageSwitcher from './LanguageSwitcher'
import ThemeToggle from './ThemeToggle'

export default function TopToolbar() {
  return (
    <div className="top-toolbar">
      <LanguageSwitcher />
      <span className="top-toolbar-divider" />
      <ThemeToggle />
    </div>
  )
}
