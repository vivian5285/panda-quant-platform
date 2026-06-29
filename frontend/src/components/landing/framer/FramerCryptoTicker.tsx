import { useEffect, useState } from 'react'
import { useI18n } from '../../../i18n'
import { publicApi } from '../../../api'

type TickerItem = {
  symbol: string
  base: string
  price: number
  change_pct: number
}

function formatPrice(price: number) {
  if (price >= 1000) return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (price >= 1) return price.toFixed(2)
  if (price >= 0.01) return price.toFixed(4)
  return price.toFixed(6)
}

function formatChange(pct: number) {
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

export default function FramerCryptoTicker() {
  const t = useI18n(s => s.t)
  const [items, setItems] = useState<TickerItem[]>([])
  const [live, setLive] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      publicApi.marketTicker()
        .then((data: { items: TickerItem[] }) => {
          if (cancelled) return
          if (data.items?.length) {
            setItems(data.items)
            setLive(true)
          }
        })
        .catch(() => { if (!cancelled) setLive(false) })
    }
    load()
    const timer = setInterval(load, 15000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [])

  const loop = items.length ? [...items, ...items] : []

  return (
    <div className="framer-market-ticker-bar">
      <div className="framer-crypto-ticker" aria-label={t('framer.ticker.label')}>
      <div className="framer-crypto-ticker-live">
        <span className={`framer-crypto-ticker-dot${live ? ' on' : ''}`} />
        {t('framer.ticker.live')}
      </div>
      <div className="framer-crypto-ticker-mask">
        <div className={`framer-crypto-ticker-track${loop.length ? '' : ' is-empty'}`}>
          {loop.length > 0 ? loop.map((item, i) => (
            <div key={`${item.symbol}-${i}`} className="framer-crypto-ticker-item">
              <span className="framer-crypto-ticker-base">{item.base}</span>
              <span className="framer-crypto-ticker-pair">/USDT</span>
              <span className="framer-crypto-ticker-price">${formatPrice(item.price)}</span>
              <span className={`framer-crypto-ticker-change${item.change_pct >= 0 ? ' up' : ' down'}`}>
                {formatChange(item.change_pct)}
              </span>
            </div>
          )) : (
            <span className="framer-crypto-ticker-loading">{t('framer.ticker.loading')}</span>
          )}
        </div>
      </div>
      </div>
    </div>
  )
}
