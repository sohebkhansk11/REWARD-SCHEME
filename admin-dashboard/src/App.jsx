import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider } from './context/ToastContext'
import { AuthProvider, useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import TokenManager from './pages/TokenManager'
import PoolOversight from './pages/PoolOversight'
import UserDirectory from './pages/UserDirectory'
import ReferralQueue from './pages/ReferralQueue'
import Diagnostics from './pages/Diagnostics'
import SystemSettings from './pages/SystemSettings'
import NotFound from './pages/NotFound'
// Code-split heavy Recharts pages — loaded only when first visited
const Statistics        = lazy(() => import('./pages/Statistics'))
const DevTools          = lazy(() => import('./pages/DevTools'))
const WinningLedger     = lazy(() => import('./pages/WinningLedger'))
const DrawEngine        = lazy(() => import('./pages/DrawEngine'))
const CommandCenter     = lazy(() => import('./pages/CommandCenter'))
const HydraulicPipeline = lazy(() => import('./pages/HydraulicPipeline'))

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

const _suspenseFallback = (
  <div className="flex items-center justify-center h-full text-slate-500 text-sm">
    Loading...
  </div>
)

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Suspense fallback={_suspenseFallback}>
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
                <Route path="statistics"         element={<Statistics />} />
                <Route path="command-center"     element={<CommandCenter />} />
                <Route path="hydraulic-pipeline" element={<HydraulicPipeline />} />
                <Route path="draw-engine"        element={<DrawEngine />} />
                <Route path="winning-ledger" element={<WinningLedger />} />
                <Route path="referrals"      element={<ReferralQueue />} />
                <Route path="diagnostics" element={<Diagnostics />} />
                <Route path="settings"    element={<SystemSettings />} />
                <Route path="dev-tools"   element={<DevModeRoute><DevTools /></DevModeRoute>} />
                <Route path="*"           element={<NotFound />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  )
}
