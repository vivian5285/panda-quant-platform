import { useEffect, useRef } from 'react'

export function useAdminMonitorWebSocket(onMessage: (data: unknown) => void, enabled = true) {
  const ref = useRef<WebSocket | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  useEffect(() => {
    if (!enabled) return
    const token = localStorage.getItem('token')
    if (!token) return

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const isDev = window.location.port === '5173' || window.location.hostname === 'localhost'
    const wsUrl = isDev
      ? `${proto}://${window.location.hostname}:8000/api/ws/admin/monitor?token=${encodeURIComponent(token)}`
      : `${proto}://${window.location.host}/api/ws/admin/monitor?token=${encodeURIComponent(token)}`

    const ws = new WebSocket(wsUrl)
    ref.current = ws

    ws.onmessage = (ev) => {
      try {
        onMessageRef.current(JSON.parse(ev.data))
      } catch { /* ignore */ }
    }

    return () => {
      ws.close()
      ref.current = null
    }
  }, [enabled])
}
