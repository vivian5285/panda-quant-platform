import { useEffect } from 'react'
import { useAuth } from '../store/auth'
import { authApi } from '../api'

/** Sync role/profile from server on boot — backend is source of truth */
export default function AuthBootstrap() {
  const token = useAuth(s => s.token)
  const setAuth = useAuth(s => s.setAuth)
  const uid = useAuth(s => s.uid)
  const displayName = useAuth(s => s.displayName)

  useEffect(() => {
    if (!token) return
    authApi.me()
      .then(p => {
        setAuth(token, p.uid, p.display_name || displayName || p.uid, p.role)
      })
      .catch(() => {})
  }, [token])

  return null
}
