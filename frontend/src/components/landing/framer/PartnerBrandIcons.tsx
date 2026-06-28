/** Recognizable partner brand marks — grayscale via parent filter, full color on hover */

export function BinanceLogo({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 128 128" fill="none" aria-hidden>
      <path
        fill="#F0B90B"
        d="M38.2 53.0 64 27.2l25.8 25.8 14.9-14.9L64 7.4 23.3 48.1l14.9 14.9Zm51.6 21.8L64 100.6 38.2 74.8l-14.9 14.9L64 120.6l40.7-40.7-14.9-14.9ZM23.3 64l14.9-14.9 14.9 14.9-14.9 14.9L23.3 64Zm80.7 0-14.9-14.9-14.9 14.9 14.9 14.9L104 64ZM64 41.9l14.9 14.9L64 71.7 49.1 56.8 64 41.9Z"
      />
    </svg>
  )
}

export function TradingViewLogo({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 160 40" fill="none" aria-hidden>
      <path
        fill="#2962FF"
        d="M6 32V8l8.2 6.1L22 8l7.8 6.1L38 8v24H6Z"
      />
      <path fill="#131722" d="M14.2 8.8 22 13.8l7.8-5V32H14.2V8.8Z" opacity="0.9" />
      <path
        fill="#131722"
        d="M48 12.5h5.2l8.4 12.1V12.5H67v19h-5.1L53.5 19.3V31.5H48V12.5Zm22.1 0h5v19h-5v-19Zm2.5 0c4.8 0 8.6 3.6 8.6 8.1 0 4.1-3.2 7.4-7.3 7.9l8.9 3h-5.9l-7.2-2.8v2.8h-5.1V12.5Zm-.3 4.2v7.5c2.8-.2 4.9-1.8 4.9-3.8 0-2-2-3.7-4.9-3.7Zm18.8-4.2h9.1c5.5 0 9.4 3.5 9.4 9.5s-3.9 9.5-9.4 9.5h-9.1V12.5Zm5 4.3v10.9h3.8c3.1 0 5.1-2 5.1-5.4 0-3.5-2-5.5-5.1-5.5h-3.8Z"
      />
    </svg>
  )
}

export function RedisLogo({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 160 48" fill="none" aria-hidden>
      <ellipse cx="24" cy="12" rx="18" ry="6" fill="#A41E11" />
      <path d="M6 12v8c0 3.3 8.1 6 18 6s18-2.7 18-6v-8" stroke="#DC382D" strokeWidth="2.5" fill="none" />
      <path d="M6 24v8c0 3.3 8.1 6 18 6s18-2.7 18-6v-8" stroke="#DC382D" strokeWidth="2.5" fill="none" />
      <ellipse cx="24" cy="36" rx="18" ry="6" fill="#A41E11" opacity="0.85" />
      <path
        fill="#DC382D"
        d="M52 34V14h6.8l7.2 12.4L73.2 14H80v20h-5.6V22.8L68.2 34h-4.9l-6.2-11.2V34H52Zm32.5-14.6c5.8 0 10.2 4.2 10.2 10.2S90.3 40 84.5 40c-5.8 0-10.2-4.2-10.2-10.2S78.7 19.4 84.5 19.4Zm0 4.8c-2.8 0-4.8 2.2-4.8 5.4s2 5.4 4.8 5.4 4.8-2.2 4.8-5.4-2-5.4-4.8-5.4Zm18.2-4.8h5.6l8.4 20h-5.9l-1.4-3.6h-8.4l-1.4 3.6h-5.7l8.4-20Zm1.2 6.2-2.8 7.2h5.6l-2.8-7.2Z"
      />
    </svg>
  )
}

export function FastAPILogo({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 160 48" fill="none" aria-hidden>
      <circle cx="24" cy="24" r="20" fill="#009688" />
      <path
        fill="#fff"
        d="M24 10 14 28h7l-1 10 12-18h-7l-1-10Z"
      />
      <path
        fill="#009688"
        d="M52 34V14h8.5c6.8 0 11.5 4.2 11.5 10.2 0 5.4-4.2 9.8-10.4 9.8H52Zm5.2-4.5h3c3.4 0 5.6-2.2 5.6-5.5 0-3.2-2.2-5.3-5.6-5.3h-3V29.5Zm28.3-15.1c5.8 0 10.2 4.2 10.2 10.2S91.3 35 85.5 35c-5.8 0-10.2-4.2-10.2-10.2S79.7 14.4 85.5 14.4Zm0 4.8c-2.8 0-4.8 2.2-4.8 5.4s2 5.4 4.8 5.4 4.8-2.2 4.8-5.4-2-5.4-4.8-5.4Zm18.2-4.8h5.6l8.4 20h-5.9l-1.4-3.6h-8.4l-1.4 3.6h-5.7l8.4-20Zm1.2 6.2-2.8 7.2h5.6l-2.8-7.2Z"
      />
    </svg>
  )
}

const ICONS = {
  binance: BinanceLogo,
  tradingview: TradingViewLogo,
  redis: RedisLogo,
  fastapi: FastAPILogo,
} as const

export type PartnerBrandId = keyof typeof ICONS

export function PartnerBrandIcon({ id, className }: { id: PartnerBrandId; className?: string }) {
  const Icon = ICONS[id]
  return <Icon className={className} />
}
