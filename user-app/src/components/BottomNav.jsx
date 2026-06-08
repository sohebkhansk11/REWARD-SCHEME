import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Wallet, Dices, UserCircle } from 'lucide-react'
import { motion } from 'framer-motion'

const TABS = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Home'    },
  { to: '/wallet',    icon: Wallet,          label: 'Wallet'  },
  { to: '/draw',      icon: Dices,           label: 'Draw'    },
  { to: '/profile',   icon: UserCircle,      label: 'Account' },
]

export default function BottomNav() {
  return (
    <nav
      className="fixed bottom-0 inset-x-0 z-40 flex justify-around items-center px-2 py-3"
      style={{
        background: 'rgba(3,3,24,0.92)',
        backdropFilter: 'blur(24px)',
        borderTop: '1px solid rgba(0,240,255,0.08)',
      }}
    >
      {TABS.map(({ to, icon: Icon, label }) => (
        <NavLink key={to} to={to} end>
          {({ isActive }) => (
            <motion.div
              whileTap={{ scale: 0.88 }}
              className="flex flex-col items-center gap-1 px-4 py-1"
            >
              <div
                className="p-2 rounded-xl transition-all"
                style={isActive ? {
                  background: 'rgba(0,240,255,0.10)',
                  boxShadow:  '0 0 12px rgba(0,240,255,0.30)',
                } : {}}
              >
                <Icon
                  className="w-5 h-5 transition-colors"
                  style={{ color: isActive ? '#00f0ff' : 'rgba(255,255,255,0.35)' }}
                  strokeWidth={isActive ? 2.5 : 1.5}
                />
              </div>
              <span
                className="text-[10px] font-mono font-semibold tracking-widest transition-colors"
                style={{ color: isActive ? '#00f0ff' : 'rgba(255,255,255,0.30)' }}
              >
                {label}
              </span>
            </motion.div>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
