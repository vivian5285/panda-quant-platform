import { useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { notificationApi } from '../api'
import { useI18n } from '../i18n'

export default function NotificationDropdown() {
  const t = useI18n(s => s.t)
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState(0)
  const [items, setItems] = useState<any[]>([])

  const load = () => {
    notificationApi.unreadCount().then(r => setCount(r.count || 0)).catch(() => {})
    notificationApi.list(false).then(setItems).catch(() => {})
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="notif-wrap">
      <button type="button" className="btn btn-ghost btn-icon notif-btn" onClick={() => { setOpen(!open); load() }} title={t('app.notifications')}>
        <Bell size={18} />
        {count > 0 && <span className="notif-badge">{count > 9 ? '9+' : count}</span>}
      </button>
      {open && (
        <div className="notif-panel glass">
          <div className="notif-head">
            <strong>{t('app.notifications')}</strong>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => notificationApi.markAllRead().then(load)}>{t('common.markAllRead')}</button>
          </div>
          <div className="notif-list">
            {items.length === 0 ? <p className="text-muted" style={{ padding: 16, fontSize: 13 }}>{t('common.noData')}</p> : items.slice(0, 20).map(n => (
              <button key={n.id} type="button" className={`notif-item ${n.is_read ? '' : 'unread'}`} onClick={() => notificationApi.markRead(n.id).then(load)}>
                <strong>{n.title}</strong>
                <span>{n.message}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
