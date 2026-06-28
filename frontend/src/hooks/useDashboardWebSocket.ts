import { useEffect, useRef } from 'react'

export function useDashboardWebSocket(onMessage: (data: unknown) => void) {
  const ref = useRef<WebSocket | null>(null)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) return

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const isDev = window.location.port === '5173' || window.location.hostname === 'localhost'
    const wsUrl = isDev
      ? `${proto}://${window.location.hostname}:8000/api/ws/dashboard?token=${encodeURIComponent(token)}`
      : `${proto}://${window.location.host}/api/ws/dashboard?token=${encodeURIComponent(token)}`

    const ws = new WebSocket(wsUrl)
    ref.current = ws

    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data))
      } catch { /* ignore */ }
    }

    return () => {
      ws.close()
      ref.current = null
    }
  }, [onMessage])
}
