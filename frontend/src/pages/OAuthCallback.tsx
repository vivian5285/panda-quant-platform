import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import AuthShell from '../components/AuthShell'
import GlassCard from '../components/GlassCard'

function parseHashParams(): URLSearchParams {
  const hash = window.location.hash.replace(/^#/, '')
  return new URLSearchParams(hash)
}

export default function OAuthCallback() {
  const t = useI18n(s => s.t)
  const [params] = useSearchParams()
  const { setAuth } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')

  useEffect(() => {
    const hashParams = parseHashParams()
    const token = hashParams.get('access_token') || params.get('access_token')
    const uid = hashParams.get('uid') || params.get('uid')
    const displayName = hashParams.get('display_name') || params.get('display_name')
    const role = hashParams.get('role') || params.get('role') || 'user'
    const err = params.get('error') || hashParams.get('error')

    if (err) {
      setError(decodeURIComponent(err))
      return
    }
    if (!token || !uid) {
      setError(t('auth.oauthFail'))
      return
    }
    setAuth(token, uid, displayName || uid, role)
    window.history.replaceState(null, '', '/auth/callback')
    navigate(role === 'admin' ? '/admin' : '/dashboard', { replace: true })
  }, [params, setAuth, navigate, t])

  return (
    <AuthShell sideTitle={t('auth.oauthRedirect')} sideSubtitle={t('brand.tagline')}>
      <GlassCard className="p-8 auth-glass-card" style={{ textAlign: 'center' }}>
        {error ? (
          <>
            <p className="form-error" style={{ marginBottom: 16 }}>{error}</p>
            <Link to="/login" className="btn btn-primary">{t('auth.login')}</Link>
          </>
        ) : (
          <p className="text-muted">{t('auth.loggingIn')}</p>
        )}
      </GlassCard>
    </AuthShell>
  )
}
