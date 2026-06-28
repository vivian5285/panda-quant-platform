import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './store/auth'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Trading from './pages/Trading'
import Strategies from './pages/Strategies'
import Signals from './pages/Signals'
import AnalyticsPage from './pages/AnalyticsPage'
import Help from './pages/Help'
import Settings from './pages/Settings'
import Trades from './pages/Trades'
import Logs from './pages/Logs'
import ApiManage from './pages/ApiManage'
import Referrals from './pages/Referrals'
import Settlements from './pages/Settlements'
import Admin from './pages/Admin'
import Withdraw from './pages/Withdraw'
import Profile from './pages/Profile'
import Privacy from './pages/Privacy'
import Terms from './pages/Terms'
import OAuthCallback from './pages/OAuthCallback'

function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth(s => s.token)
  const isAdmin = useAuth(s => s.isAdmin)
  if (!token) return <Navigate to="/login" />
  if (!isAdmin()) return <Navigate to="/dashboard" />
  return <>{children}</>
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth(s => s.token)
  return token ? <>{children}</> : <Navigate to="/login" />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/auth/callback" element={<OAuthCallback />} />
        <Route path="/help" element={<Help />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
        <Route path="/trading" element={<PrivateRoute><Trading /></PrivateRoute>} />
        <Route path="/strategies" element={<PrivateRoute><Strategies /></PrivateRoute>} />
        <Route path="/signals" element={<PrivateRoute><Signals /></PrivateRoute>} />
        <Route path="/analytics" element={<PrivateRoute><AnalyticsPage /></PrivateRoute>} />
        <Route path="/billing" element={<Navigate to="/settlements" replace />} />
        <Route path="/trades" element={<PrivateRoute><Trades /></PrivateRoute>} />
        <Route path="/logs" element={<PrivateRoute><Logs /></PrivateRoute>} />
        <Route path="/api" element={<PrivateRoute><ApiManage /></PrivateRoute>} />
        <Route path="/referrals" element={<PrivateRoute><Referrals /></PrivateRoute>} />
        <Route path="/settlements" element={<PrivateRoute><Settlements /></PrivateRoute>} />
        <Route path="/withdraw" element={<PrivateRoute><Withdraw /></PrivateRoute>} />
        <Route path="/settings" element={<PrivateRoute><Settings /></PrivateRoute>} />
        <Route path="/profile" element={<PrivateRoute><Profile /></PrivateRoute>} />
        <Route path="/admin" element={<AdminRoute><Admin /></AdminRoute>} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  )
}
