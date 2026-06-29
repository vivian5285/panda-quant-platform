import GlassCard from './GlassCard'
import { useI18n } from '../i18n'
import { Bot, Users } from 'lucide-react'

export default function DualPathIntro() {
  const { t } = useI18n()

  return (
    <GlassCard className="p-5 section-mb-lg dual-path-intro">
      <h3 className="card-heading section-mb-sm">{t('perfFee.dualPathTitle')}</h3>
      <div className="dual-path-grid">
        <div className="dual-path-item">
          <Bot size={20} />
          <div>
            <strong>{t('perfFee.pathHostTitle')}</strong>
            <p className="text-muted text-sm">{t('perfFee.pathHostDesc')}</p>
          </div>
        </div>
        <div className="dual-path-item">
          <Users size={20} />
          <div>
            <strong>{t('perfFee.pathMarketTitle')}</strong>
            <p className="text-muted text-sm">{t('perfFee.pathMarketDesc')}</p>
          </div>
        </div>
      </div>
    </GlassCard>
  )
}
