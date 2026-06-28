import { Link } from 'react-router-dom'
import LandingNav from '../components/landing/LandingNav'
import TradingViewWidget from '../components/landing/TradingViewWidget'
import LogoMarquee from '../components/landing/LogoMarquee'
import FeaturesGridSection from '../components/landing/FeaturesGridSection'
import AiAgentsSection from '../components/landing/AiAgentsSection'
import HowItWorksSection from '../components/landing/HowItWorksSection'
import PricingSection from '../components/landing/PricingSection'
import HeroSection from '../components/landing/HeroSection'
import BentoSection from '../components/landing/BentoSection'
import ProductShowcase from '../components/landing/ProductShowcase'
import TestimonialsSection from '../components/landing/TestimonialsSection'
import FaqSection from '../components/landing/FaqSection'
import LandingFooter from '../components/landing/LandingFooter'
import GlassCard from '../components/GlassCard'
import ScrollReveal from '../components/ui/ScrollReveal'
import { useI18n } from '../i18n'
import { useTheme } from '../store/theme'
import { useAuth } from '../store/auth'
import { ShieldCheck, TrendingUp } from 'lucide-react'

const BINANCE_SYMBOLS = [
  { proName: 'BINANCE:BTCUSDT', title: 'BTC/USDT' },
  { proName: 'BINANCE:ETHUSDT', title: 'ETH/USDT' },
  { proName: 'BINANCE:BNBUSDT', title: 'BNB/USDT' },
  { proName: 'BINANCE:SOLUSDT', title: 'SOL/USDT' },
  { proName: 'BINANCE:XRPUSDT', title: 'XRP/USDT' },
  { proName: 'BINANCE:DOGEUSDT', title: 'DOGE/USDT' },
]

const MARKET_SYMBOLS = [
  { s: 'BINANCE:BTCUSDT', d: 'Bitcoin', base: 'BTC' },
  { s: 'BINANCE:ETHUSDT', d: 'Ethereum', base: 'ETH' },
  { s: 'BINANCE:BNBUSDT', d: 'BNB', base: 'BNB' },
  { s: 'BINANCE:SOLUSDT', d: 'Solana', base: 'SOL' },
  { s: 'BINANCE:XRPUSDT', d: 'XRP', base: 'XRP' },
  { s: 'BINANCE:DOGEUSDT', d: 'Dogecoin', base: 'DOGE' },
]

export default function Landing() {
  const t = useI18n(s => s.t)
  const locale = useI18n(s => s.locale)
  const { theme } = useTheme()
  const token = useAuth(s => s.token)
  const tvLocale = locale === 'zh' ? 'zh_CN' : 'en'
  const tvTheme = theme === 'dark' ? 'dark' : 'light'

  return (
    <div className="landing-page saas-landing">
      <div className="landing-ticker-wrap">
        <TradingViewWidget
          scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js"
          className="landing-ticker"
          config={{
            symbols: BINANCE_SYMBOLS.map(s => ({ proName: s.proName, title: s.title })),
            showSymbolLogo: true,
            colorTheme: tvTheme,
            isTransparent: true,
            displayMode: 'adaptive',
            locale: tvLocale,
          }}
        />
      </div>

      <LandingNav />
      <HeroSection />
      <LogoMarquee />
      <FeaturesGridSection />
      <BentoSection />
      <AiAgentsSection />
      <HowItWorksSection />
      <ProductShowcase />
      <PricingSection />

      <section id="markets" className="landing-section">
        <ScrollReveal className="landing-section-head">
          <p className="landing-kicker">{t('landing.markets.kicker')}</p>
          <h2>{t('landing.markets.title')}</h2>
          <p>{t('landing.markets.subtitle')}</p>
        </ScrollReveal>
        <div className="landing-market-widget glass">
          <TradingViewWidget
            scriptSrc="https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js"
            className="landing-market-tv"
            style={{ minHeight: 480 }}
            config={{
              colorTheme: tvTheme,
              dateRange: '1D',
              showChart: true,
              locale: tvLocale,
              isTransparent: true,
              showSymbolLogo: true,
              width: '100%',
              height: '100%',
              plotLineColorGrowing: 'rgba(0, 176, 80, 1)',
              plotLineColorFalling: 'rgba(239, 68, 68, 1)',
              gridLineColor: theme === 'dark' ? 'rgba(0,176,80,0.08)' : 'rgba(52,199,89,0.06)',
              scaleFontColor: theme === 'dark' ? 'rgba(156, 168, 159, 1)' : 'rgba(138, 147, 142, 1)',
              belowLineFillColorGrowing: 'rgba(0, 176, 80, 0.18)',
              belowLineFillColorFalling: 'rgba(239, 68, 68, 0.12)',
              symbolActiveColor: 'rgba(0, 176, 80, 0.14)',
              tabs: [{ title: t('landing.markets.tabCrypto'), symbols: MARKET_SYMBOLS.map(s => ({ s: s.s, d: s.d, base: s.base })) }],
            }}
          />
        </div>
      </section>

      <ProductShowcase />
      <TestimonialsSection />

      <section id="strategy" className="landing-section landing-section-alt">
        <div className="landing-split">
          <ScrollReveal className="landing-split-copy">
            <p className="landing-kicker">{t('landing.strategy.kicker')}</p>
            <h2>{t('landing.strategy.title')}</h2>
            <p className="landing-lead">{t('landing.strategy.lead')}</p>
            <ul className="landing-check-list">
              {(['combo', 'regime', 'webhook', 'risk'] as const).map(k => (
                <li key={k}>
                  <TrendingUp size={16} />
                  <div>
                    <strong>{t(`landing.strategy.points.${k}.title`)}</strong>
                    <span>{t(`landing.strategy.points.${k}.desc`)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </ScrollReveal>
          <GlassCard className="landing-strategy-panel" green delay={0.1}>
            <div className="landing-strategy-tags">
              {(['trend', 'breakout', 'mean', 'momentum'] as const).map(k => (
                <span key={k}>{t(`landing.strategy.tags.${k}`)}</span>
              ))}
            </div>
            <p className="landing-strategy-note">{t('landing.strategy.note')}</p>
          </GlassCard>
        </div>
      </section>

      <section id="security" className="landing-section">
        <div className="landing-split landing-split-reverse">
          <GlassCard className="landing-security-card" delay={0.05}>
            <ShieldCheck size={32} className="text-green" style={{ margin: '0 auto 12px' }} />
            <h3>{t('landing.security.cardTitle')}</h3>
            <p>{t('landing.security.cardDesc')}</p>
          </GlassCard>
          <ScrollReveal className="landing-split-copy">
            <p className="landing-kicker">{t('landing.security.kicker')}</p>
            <h2>{t('landing.security.title')}</h2>
            <ul className="landing-check-list">
              {(['api', 'dual', 'principal', 'audit'] as const).map(k => (
                <li key={k}>
                  <ShieldCheck size={16} />
                  <div>
                    <strong>{t(`landing.security.points.${k}.title`)}</strong>
                    <span>{t(`landing.security.points.${k}.desc`)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </ScrollReveal>
        </div>
      </section>

      <FaqSection />

      <section className="landing-cta">
        <GlassCard className="landing-cta-inner" green>
          <h2>{t('landing.cta.title')}</h2>
          <p>{t('landing.cta.subtitle')}</p>
          <div className="landing-hero-actions" style={{ justifyContent: 'center' }}>
            <Link to={token ? '/dashboard' : '/register'} className="btn btn-primary ripple-btn">
              {token ? t('landing.nav.console') : t('landing.cta.button')}
            </Link>
          </div>
        </GlassCard>
      </section>

      <LandingFooter />
    </div>
  )
}
