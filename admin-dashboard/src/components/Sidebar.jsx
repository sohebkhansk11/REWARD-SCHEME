import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Key, Users, Shield, Dot } from 'lucide-react'

const NAV = [
  { to: '/',       icon: LayoutDashboard, label: 'Dashboard'      },
  { to: '/tokens', icon: Key,             label: 'Token Manager'  },
  { to: '/pools',  icon: Users,           label: 'Pool Oversight' },
]

export default function Sidebar() {
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
      <div className="px-5 py-4 border-t border-slate-700/60">
        <div className="flex items-center gap-2">
          <Dot className="w-5 h-5 text-emerald-400 -ml-1 animate-pulse" />
          <span className="text-xs text-slate-400">API: localhost:8000</span>
        </div>
        <p className="text-xs text-slate-600 mt-1 pl-4">v1.0.0</p>
      </div>
    </aside>
  )
}
