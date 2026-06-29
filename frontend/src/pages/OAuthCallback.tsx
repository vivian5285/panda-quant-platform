import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { authApi } from '../api'
import { useAuth } from '../store/auth'
import { useI18n } from '../i18n'
import { toast } from '../store/toast'
import AuthShell from '../components/AuthShell'
import GlassCard from '../components/GlassCard'
import RippleButton from '../components/ui/RippleButton'

function parseHashParams(): URLSearchParams {
  const hash = window.location.hash.replace(/^#/, '')
  return new URLSearchParams(hash)
}

function mapOAuthError(raw: string, t: (k: string) => string): string {
  const lower = raw.toLowerCase()
  if (lower.includes('disabled')) return t('auth.oauthDisabled')
  if (lower.includes('invalid oauth state')) return t('auth.oauthStateInvalid')
  if (lower.includes('oauth failed')) return t('auth.oauthFail')
  return raw
}

export default function OAuthCallback() {
  const t = useI18n(s => s.t)
  const [params] = useSearchParams()
  const { setAuth } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [challengeToken, setChallengeToken] = useState('')
  const [pending, setPending] = useState<{ uid: string; display_name: string; role: string; api_status?: string } | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const hashParams = parseHashParams()
    const err = params.get('error') || hashParams.get('error')
    if (err) {
      const msg = mapOAuthError(decodeURIComponent(err), t)
      setError(msg)
      toast.error(msg)
      return
    }

    const requiresTotp = params.get('requires_totp') === '1'
    if (requiresTotp) {
      setChallengeToken(params.get('challenge_token') || '')
      setPending({
        uid: params.get('uid') || '',
        display_name: params.get('display_name') || params.get('uid') || '',
        role: params.get('role') || 'user',
        api_status: params.get('api_status') || undefined,
      })
      window.history.replaceState(null, '', '/auth/callback')
      return
    }

    const token = hashParams.get('access_token') || params.get('access_token')
    const uid = hashParams.get('uid') || params.get('uid')
    const displayName = hashParams.get('display_name') || params.get('display_name')
    const role = hashParams.get('role') || params.get('role') || 'user'
    const apiStatus = hashParams.get('api_status') || params.get('api_status')

    if (!token || !uid) {
      const msg = t('auth.oauthFail')
      setError(msg)
      toast.error(msg)
      return
    }
    setAuth(token, uid, displayName || uid, role)
    window.history.replaceState(null, '', '/auth/callback')
    if (role === 'admin') navigate('/admin', { replace: true })
    else if (apiStatus && apiStatus !== 'active') navigate('/api', { replace: true })
    else navigate('/dashboard', { replace: true })
  }, [params, setAuth, navigate, t])

  const submitTotp = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const data = await authApi.loginTotp(challengeToken, totpCode)
      if (!data.access_token) {
        toast.error(t('auth.totpError'))
        setError(t('auth.totpError'))
        return
      }
      setAuth(data.access_token, data.uid, data.display_name, data.role)
      if (data.role === 'admin') navigate('/admin', { replace: true })
      else if (data.api_status && data.api_status !== 'active') navigate('/api', { replace: true })
      else navigate('/dashboard', { replace: true })
    } catch {
      toast.error(t('auth.totpError'))
      setError(t('auth.totpError'))
    } finally {
      setLoading(false)
    }
  }

  if (challengeToken && pending) {
    return (
      <AuthShell>
        <GlassCard className="auth-glass-card">
          <h2 className="auth-card-title">{t('auth.totpTitle')}</h2>
          <p className="text-muted auth-card-sub">{t('auth.totpSubtitle', { name: pending.display_name })}</p>
          <form onSubmit={submitTotp} className="form-stack">
            <input className="input" value={totpCode} onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
              placeholder="000000" inputMode="numeric" autoComplete="one-time-code" required />
            {error && <p className="form-error">{error}</p>}
            <RippleButton type="submit" className="btn btn-auth-primary auth-submit" disabled={loading}>
              {loading ? t('auth.loggingIn') : t('auth.totpVerify')}
            </RippleButton>
          </form>
        </GlassCard>
      </AuthShell>
    )
  }

  return (
    <AuthShell>
      <GlassCard className="auth-glass-card auth-centered">
        {error ? (
          <>
            <p className="form-error section-mb-sm">{error}</p>
            <Link to="/login" className="btn btn-auth-primary">{t('auth.login')}</Link>
          </>
        ) : (
          <p className="text-muted">{t('auth.loggingIn')}</p>
        )}
      </GlassCard>
    </AuthShell>
  )
}
