import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { LogOut, RefreshCw, Hexagon, Wifi, WifiOff } from 'lucide-react'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import CountdownTimer from '../components/CountdownTimer'
import BottomNav from '../components/BottomNav'
import { useUser } from '../context/UserContext'
import { getUser } from '../api/client'

const STATUS_COLORS = {
  Active:        { bg: 'rgba(0,255,136,0.1)',  border: 'rgba(0,255,136,0.3)',  text: '#00ff88' },
  Waitlist:      { bg: 'rgba(255,170,0,0.1)',  border: 'rgba(255,170,0,0.3)',  text: '#ffaa00' },
  Eliminated:    { bg: 'rgba(255,50,50,0.1)',  border: 'rgba(255,50,50,0.3)',  text: '#ff4444' },
  Eliminated_Won:{ bg: 'rgba(191,0,255,0.1)',  border: 'rgba(191,0,255,0.3)',  text: '#d580ff' },
}

function LevelBadge({ level }) {
  const colors = ['','#00f0ff','#00f0ff','#54b4ff','#ffaa00','#ff6600','#bf00ff']
  const c = colors[level] ?? '#ffffff'
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative">
        <Hexagon className="w-14 h-14" style={{ color: c, filter: `drop-shadow(0 0 8px ${c})` }} strokeWidth={1.5} />
        <span className="absolute inset-0 flex items-center justify-center text-xl font-black"
          style={{ color: c, textShadow: `0 0 10px ${c}` }}>
          {level}
        </span>
      </div>
      <span className="text-[10px] font-mono tracking-[0.2em] text-white/35 uppercase">Level</span>
    </div>
  )
}

export default function Dashboard() {
  const { user, logout, refresh } = useUser()
  const nav = useNavigate()
  const [apiOk, setApiOk] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchFresh = async (silent = false) => {
    if (!user?.id) return
    if (!silent) setRefreshing(true)
    try {
      const res = await getUser(user.id)
      refresh(res.data)
      setApiOk(true)
    } catch { setApiOk(false) }
    finally { setRefreshing(false) }
  }

  useEffect(() => { fetchFresh(true) }, [])

  const handleLogout = () => { logout(); nav('/', { replace: true }) }

  const status = user?.status ?? 'Waitlist'
  const sc = STATUS_COLORS[status] ?? STATUS_COLORS.Waitlist

  return (
    <div className="min-h-dvh pb-28 relative">
      <Background />

      {/* Header */}
      <div className="sticky top-0 z-30 px-5 pt-12 pb-4 flex items-center justify-between"
        style={{ background: 'rgba(3,3,24,0.7)', backdropFilter: 'blur(20px)' }}>
        <div className="min-w-0">
          <p className="text-[10px] font-mono tracking-[0.25em] text-white/30 uppercase">Welcome back</p>
          <p className="font-mono font-bold text-white truncate" style={{ textShadow: '0 0 10px rgba(0,240,255,0.4)' }}>
            @{user?.username ?? '---'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div title={apiOk ? 'API Connected' : 'API Offline'}>
            {apiOk
              ? <Wifi className="w-4 h-4 text-emerald-400" />
              : <WifiOff className="w-4 h-4 text-red-400" />
            }
          </div>
          <motion.button whileTap={{ scale: 0.9 }} onClick={() => fetchFresh()}
            className="p-2 rounded-xl" style={{ background: 'rgba(255,255,255,0.05)' }}>
            <RefreshCw className={`w-4 h-4 text-white/50 ${refreshing ? 'animate-spin' : ''}`} />
          </motion.button>
          <motion.button whileTap={{ scale: 0.9 }} onClick={handleLogout}
            className="p-2 rounded-xl" style={{ background: 'rgba(255,255,255,0.05)' }}>
            <LogOut className="w-4 h-4 text-white/50" />
          </motion.button>
        </div>
      </div>

      <div className="px-5 space-y-4">
        {/* Pool + Level card */}
        <GlassCard className="p-5" animate>
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-mono tracking-[0.2em] text-white/30 uppercase mb-1">Active Pool</p>
              <p className="text-2xl font-black text-white truncate">
                {user?.current_pool_id ? `Pool #${user.current_pool_id}` : 'Not Assigned'}
              </p>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-[11px] font-mono font-bold px-2.5 py-1 rounded-full border"
                  style={{ background: sc.bg, borderColor: sc.border, color: sc.text }}>
                  {status.replace('_', ' ')}
                </span>
                {user?.weekly_payment_status && (
                  <span className="text-[11px] font-mono font-bold px-2.5 py-1 rounded-full border"
                    style={user.weekly_payment_status === 'Paid'
                      ? { background: 'rgba(0,255,136,0.08)', borderColor: 'rgba(0,255,136,0.3)', color: '#00ff88' }
                      : { background: 'rgba(255,80,80,0.08)', borderColor: 'rgba(255,80,80,0.3)', color: '#ff5555' }
                    }>
                    {user.weekly_payment_status === 'Paid' ? '✓ PAID' : '✗ UNPAID'}
                  </span>
                )}
              </div>
            </div>
            <LevelBadge level={user?.current_level ?? 1} />
          </div>
        </GlassCard>

        {/* Countdown */}
        <GlassCard className="p-6" animate>
          <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase text-center mb-5">
            Next Draw · Sunday 7 PM
          </p>
          <CountdownTimer />
          <motion.p
            className="text-center mt-5 text-[10px] font-mono tracking-widest"
            style={{ color: 'rgba(0,240,255,0.4)' }}
            animate={{ opacity: [0.4, 0.8, 0.4] }}
            transition={{ duration: 2.5, repeat: Infinity }}
          >
            ◈ DRAW PROTOCOL ACTIVE ◈
          </motion.p>
        </GlassCard>

        {/* User info */}
        <GlassCard className="p-5" animate>
          <p className="text-[10px] font-mono tracking-[0.2em] text-white/30 uppercase mb-3">Account Details</p>
          <div className="space-y-2.5">
            {[
              { label: 'Name',   value: user?.name ?? '—' },
              { label: 'Mobile', value: user?.mobile ? `${user.mobile.slice(0, 4)}••••${user.mobile.slice(-3)}` : '—' },
              { label: 'Joined', value: user?.join_date ? new Date(user.join_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—' },
            ].map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-xs font-mono text-white/35">{label}</span>
                <span className="text-sm font-mono font-semibold text-white/70">{value}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>

      <BottomNav />
    </div>
  )
}
