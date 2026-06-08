import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { UserProvider, useUser } from './context/UserContext'
import Auth from './pages/Auth'
import Dashboard from './pages/Dashboard'
import TokenWallet from './pages/TokenWallet'
import DrawPage from './pages/DrawPage'

function Wrap({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 18, filter: 'blur(4px)' }}
      animate={{ opacity: 1, x: 0,  filter: 'blur(0px)' }}
      exit={{    opacity: 0, x: -18, filter: 'blur(4px)' }}
      transition={{ duration: 0.27, ease: [0.25, 1, 0.5, 1] }}
    >
      {children}
    </motion.div>
  )
}

function Guard({ children }) {
  const { user } = useUser()
  if (!user) return <Navigate to="/" replace />
  return children
}

function AppRoutes() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/"          element={<Wrap><Auth /></Wrap>} />
        <Route path="/dashboard" element={<Guard><Wrap><Dashboard /></Wrap></Guard>} />
        <Route path="/wallet"    element={<Guard><Wrap><TokenWallet /></Wrap></Guard>} />
        <Route path="/draw"      element={<Guard><Wrap><DrawPage /></Wrap></Guard>} />
        <Route path="*"          element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
  )
}

export default function App() {
  return (
    <UserProvider>
      <BrowserRouter>
        <div className="max-w-[430px] mx-auto min-h-dvh relative">
          <AppRoutes />
        </div>
      </BrowserRouter>
    </UserProvider>
  )
}
