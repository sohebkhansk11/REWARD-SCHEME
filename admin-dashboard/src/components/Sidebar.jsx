import { NavLink, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Key, Users, UserSearch, Shield, Dot, LogOut, Activity, BarChart3 } from 'lucide-react'
import { BASE_URL } from '../api/client'
import { useAuth } from '../context/AuthContext'

const NAV = [
  { to: '/',            icon: LayoutDashboard, label: 'Dashboard'      },
  { to: '/tokens',      icon: Key,             label: 'Token Manager'  },
  { to: '/pools',       icon: Users,           label: 'Pool Oversight' },
  { to: '/users',       icon: UserSearch,      label: 'User Directory' },
  { to: '/statistics',  icon: BarChart3,       label: 'Statistics'     },
  { to: '/diagnostics', icon: Activity,        label: 'Diagnostics'    },
]

export default function Sidebar() {
  const { logout, adminName } = useAuth()
  const nav = useNavigate()

  const handleLogout = () => {
    logout()
    nav('/login', { replace: true })
  }

  return (
    <aside className="w-60 flex-shrink-0 bg-slate-900 flex flex-col h-screen sticky top-0">
      {/* Brand */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-slate-700/60">
        <div className="bg-blue-600 p-2 rounded-lg shadow-lg shadow-blue-900/40">
          <Shield className="w-5 h-5 text-white" />
        </div>
        <div className="min-w-0">
          <p className="font-bold text-white text-sm leading-none">RewardScheme</p>
          <p className="text-slate-400 text-xs mt-0.5 uppercase tracking-widest">Admin Console</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 pt-4 space-y-0.5">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-900/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`
            }
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-slate-700/60 space-y-3">
        {/* Logged-in admin */}
        {adminName && (
          <div className="flex items-center gap-2 px-1">
            <div className="w-7 h-7 rounded-full bg-blue-700 flex items-center justify-center text-xs font-bold text-white flex-shrink-0">
              {adminName[0].toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-slate-300 truncate">{adminName}</p>
              <p className="text-[10px] text-slate-600">Administrator</p>
            </div>
          </div>
        )}

        {/* API indicator */}
        <div className="flex items-center gap-2 px-1">
          <Dot className="w-5 h-5 text-emerald-400 -ml-1 animate-pulse flex-shrink-0" />
          <span className="text-xs text-slate-600 truncate" title={BASE_URL}>
            {BASE_URL.replace(/^https?:\/\//, '')}
          </span>
        </div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-500 hover:text-red-400 hover:bg-red-950/30 transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Sign out
        </button>
      </div>
    </aside>
  )
}
