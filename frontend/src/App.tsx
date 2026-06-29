import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

import { useAuth } from './store/auth'

import AuthBootstrap from './components/AuthBootstrap'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Register from './pages/Register'
import OAuthCallback from './pages/OAuthCallback'
import Help from './pages/Help'
import Privacy from './pages/Privacy'
import Terms from './pages/Terms'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Trading = lazy(() => import('./pages/Trading'))
const Positions = lazy(() => import('./pages/Positions'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const Trades = lazy(() => import('./pages/Trades'))
const ApiManage = lazy(() => import('./pages/ApiManage'))
const Referrals = lazy(() => import('./pages/Referrals'))
const Settlements = lazy(() => import('./pages/Settlements'))
const RiskControl = lazy(() => import('./pages/RiskControl'))
const Admin = lazy(() => import('./pages/Admin'))
const Withdraw = lazy(() => import('./pages/Withdraw'))
const Profile = lazy(() => import('./pages/Profile'))
const StrategyAdvantages = lazy(() => import('./pages/StrategyAdvantages'))

function PageFallback() {
  return (
    <div className="page-loading-fallback" role="status" aria-live="polite">
      …
    </div>
  )
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth(s => s.token)
  const isAdmin = useAuth(s => s.isAdmin)
  if (!token) return <Navigate to="/login" />
  if (!isAdmin()) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

/** User console — admins are redirected to the admin console */
function UserRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth(s => s.token)
  const isAdmin = useAuth(s => s.isAdmin)
  if (!token) return <Navigate to="/login" />
  if (isAdmin()) return <Navigate to="/admin" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthBootstrap />
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/auth/callback" element={<OAuthCallback />} />
          <Route path="/help" element={<Help />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/dashboard" element={<UserRoute><Dashboard /></UserRoute>} />
          <Route path="/trading" element={<UserRoute><Trading /></UserRoute>} />
          <Route path="/positions" element={<UserRoute><Positions /></UserRoute>} />
          <Route path="/analytics" element={<UserRoute><AnalyticsPage /></UserRoute>} />
          <Route path="/trades" element={<UserRoute><Trades /></UserRoute>} />
          <Route path="/risk" element={<UserRoute><RiskControl /></UserRoute>} />
          <Route path="/api" element={<UserRoute><ApiManage /></UserRoute>} />
          <Route path="/referrals" element={<UserRoute><Referrals /></UserRoute>} />
          <Route path="/settlements" element={<UserRoute><Settlements /></UserRoute>} />
          <Route path="/withdraw" element={<UserRoute><Withdraw /></UserRoute>} />
          <Route path="/profile" element={<UserRoute><Profile /></UserRoute>} />
          <Route path="/admin" element={<AdminRoute><Admin /></AdminRoute>} />
          <Route path="/settings" element={<UserRoute><Navigate to="/profile" replace /></UserRoute>} />
          <Route path="/logs" element={<UserRoute><Navigate to="/trades?tab=logs" replace /></UserRoute>} />
          <Route path="/billing" element={<UserRoute><Navigate to="/settlements" replace /></UserRoute>} />
          <Route path="/strategies" element={<UserRoute><StrategyAdvantages /></UserRoute>} />
          <Route path="/signals" element={<UserRoute><Navigate to="/analytics" replace /></UserRoute>} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
