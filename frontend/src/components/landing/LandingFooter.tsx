import { Link } from 'react-router-dom'
import { Github, MessageCircle, Send, Twitter } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useAuth } from '../../store/auth'

export default function LandingFooter() {
  const t = useI18n(s => s.t)
  const token = useAuth(s => s.token)

  const social = [
    { icon: MessageCircle, label: 'Discord', href: '#' },
    { icon: Send, label: 'Telegram', href: '#' },
    { icon: Twitter, label: 'Twitter', href: '#' },
    { icon: Github, label: 'GitHub', href: 'https://github.com/vivian5285/panda-quant-platform' },
  ]

  return (
    <footer className="landing-footer saas-footer">
      <div className="landing-footer-inner">
        <div>
          <strong>{t('brand.name')}</strong>
          <p>{t('saas.footer.tagline')}</p>
          <div className="saas-social">
            {social.map(({ icon: Icon, label, href }) => (
              <a key={label} href={href} target="_blank" rel="noreferrer" title={label} className="saas-social-link">
                <Icon size={18} />
              </a>
            ))}
          </div>
        </div>
        <div className="saas-footer-cols">
          <div>
            <h4>{t('saas.footer.product')}</h4>
            <Link to="/register">{t('auth.register')}</Link>
            <Link to="/help">{t('nav.help')}</Link>
            <a href="#features">{t('landing.nav.features')}</a>
          </div>
          <div>
            <h4>{t('saas.footer.legal')}</h4>
            <Link to="/privacy">{t('saas.footer.privacy')}</Link>
            <Link to="/terms">{t('saas.footer.terms')}</Link>
            <Link to="/help">{t('saas.footer.docs')}</Link>
          </div>
        </div>
        <div className="landing-footer-links">
          <Link to="/login">{t('auth.login')}</Link>
          {token && <Link to="/dashboard">{t('landing.nav.console')}</Link>}
        </div>
        <p className="landing-footer-copy">{t('landing.footer.rights')}</p>
        <p className="landing-footer-risk">{t('landing.footer.riskDisclaimer')}</p>
      </div>
    </footer>
  )
}
