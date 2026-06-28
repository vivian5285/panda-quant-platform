import { useEffect, useRef } from 'react'

interface Props {
  scriptSrc: string
  config: Record<string, unknown>
  className?: string
  style?: React.CSSProperties
}

export default function TradingViewWidget({ scriptSrc, config, className, style }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const configKey = JSON.stringify(config)

  useEffect(() => {
    const host = containerRef.current
    if (!host) return

    host.innerHTML = ''

    const wrapper = document.createElement('div')
    wrapper.className = 'tradingview-widget-container'

    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'

    const script = document.createElement('script')
    script.type = 'text/javascript'
    script.src = scriptSrc
    script.async = true
    script.innerHTML = configKey

    wrapper.appendChild(widget)
    wrapper.appendChild(script)
    host.appendChild(wrapper)

    return () => {
      host.innerHTML = ''
    }
  }, [scriptSrc, configKey])

  return <div ref={containerRef} className={className} style={style} />
}
