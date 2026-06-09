import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider } from './context/ToastContext'
import { AuthProvider, useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import TokenManager from './pages/TokenManager'
import PoolOversight from './pages/PoolOversight'
import UserDirectory from './pages/UserDirectory'
import Statistics from './pages/Statistics'
import ReferralQueue from './pages/ReferralQueue'
import Diagnostics from './pages/Diagnostics'
import DevTools from './pages/DevTools'

// Dev Tools route is only accessible when the build was compiled with
// VITE_ENABLE_DEV_MODE=true.  Any other value redirects to the dashboard.
const IS_DEV_MODE = import.meta.env.VITE_ENABLE_DEV_MODE === 'true'

// Redirect to /login when no valid JWT is present
function ProtectedRoute({ children }) {
  const { isAuthed } = useAuth()
  return isAuthed ? children : <Navigate to="/login" replace />
}

// Redirect logged-in admins away from /login
function PublicRoute({ children }) {
  const { isAuthed } = useAuth()
  return isAuthed ? <Navigate to="/" replace /> : children
}

// Redirect to dashboard if VITE_ENABLE_DEV_MODE is not exactly 'true'
function DevModeRoute({ children }) {
  return IS_DEV_MODE ? children : <Navigate to="/" replace />
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            {/* Public — login page */}
            <Route
              path="/login"
              element={
                <PublicRoute>
                  <Login />
                </PublicRoute>
              }
            />

            {/* Protected — all admin pages */}
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="tokens"      element={<TokenManager />} />
              <Route path="pools"       element={<PoolOversight />} />
              <Route path="users"       element={<UserDirectory />} />
              <Route path="statistics"  element={<Statistics />} />
              <Route path="referrals"   element={<ReferralQueue />} />
              <Route path="diagnostics" element={<Diagnostics />} />
              <Route path="dev-tools"   element={<DevModeRoute><DevTools /></DevModeRoute>} />
              <Route path="*"           element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  )
}
