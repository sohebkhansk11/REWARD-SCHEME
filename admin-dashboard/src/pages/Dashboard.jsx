import { useState, useEffect, useCallback } from 'react'
// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Added CalendarDays icon + AnimatePresence for the new day-aware LiveClock.
import { IndianRupee, Users, LayoutGrid, Clock, RefreshCw, Zap, AlertCircle, CalendarDays } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import Spinner from '../components/Spinner'
import { getStats, getPools, checkWaitlist, getBrain5Lpi, BASE_URL } from '../api/client'
import { useToast } from '../context/ToastContext'

const INR = v =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)

// ── Brain 5 LPI Health Chip ───────────────────────────────────────────────────
function LpiChip({ lpi }) {
  if (lpi == null) return null
  const v = parseFloat(lpi)
  const cfg =
    v < 14 ? { label: `LPI ${v.toFixed(1)}% · Healthy`,  cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' } :
    v < 25 ? { label: `LPI ${v.toFixed(1)}% · Caution`,  cls: 'bg-amber-50   text-amber-700   border-amber-200'   } :
    v < 50 ? { label: `LPI ${v.toFixed(1)}% · Elevated`, cls: 'bg-orange-50  text-orange-700  border-orange-200'  } :
             { label: `LPI ${v.toFixed(1)}% · Critical`, cls: 'bg-red-50     text-red-700     border-red-200'     }
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${cfg.cls}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
      {cfg.label}
    </span>
  )
}

// ── Live Day + Time watch (Framer Motion) ─────────────────────────────────────
// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Point 2 of the consistency/integrity request: surface the DAY alongside the time
// and represent the watch more beautifully with Framer Motion.
//
// IMPORTANT (integrity note): this watch is the ADMIN's LOCAL browser clock and is
// DISPLAY-ONLY — it drives no system event.  Every draw-lifecycle event runs off the
// server's UTC wall-clock via APScheduler.  We therefore label it "Local" so the
// admin never mistakes this widget for the clock that governs the draw.
function LiveClock({ now }) {
  const weekday  = now.toLocaleDateString('en-IN', { weekday: 'long' })
  const datePart = now.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
  const hh = String(now.getHours()).padStart(2, '0')
  const mm = String(now.getMinutes()).padStart(2, '0')
  const ss = String(now.getSeconds()).padStart(2, '0')

  // One animated digit cell — flips upward whenever its value changes.
  const Digit = ({ value }) => (
    <span className="relative inline-block w-[0.62em] h-[1.25em] overflow-hidden text-center align-baseline">
      <AnimatePresence initial={false} mode="popLayout">
        <motion.span
          key={value}
          initial={{ y: '110%', opacity: 0 }}
          animate={{ y: '0%',   opacity: 1 }}
          exit={{    y: '-110%', opacity: 0 }}
          transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          className="absolute inset-0 inline-block"
        >
          {value}
        </motion.span>
      </AnimatePresence>
    </span>
  )

  return (
    <motion.div
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0,  scale: 1 }}
      transition={{ type: 'spring', stiffness: 280, damping: 22 }}
      className="hidden sm:flex items-stretch rounded-xl overflow-hidden border border-slate-200 shadow-sm bg-white"
    >
      {/* Day + date panel */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-br from-violet-50 to-indigo-50 border-r border-slate-200">
        <CalendarDays className="w-3.5 h-3.5 text-violet-500 flex-shrink-0" />
        <div className="leading-tight">
          <AnimatePresence mode="wait">
            <motion.div
              key={weekday}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{    opacity: 0, y: -6 }}
              transition={{ duration: 0.3 }}
              className="text-[11px] font-bold text-violet-700 leading-none"
            >
              {weekday}
            </motion.div>
          </AnimatePresence>
          <div className="text-[10px] text-slate-400 tabular-nums mt-0.5">{datePart}</div>
        </div>
      </div>

      {/* Time panel */}
      <div className="flex items-center gap-1.5 px-3 py-1.5">
        <motion.span
          animate={{ opacity: [1, 0.3, 1] }}
          transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
          className="flex-shrink-0"
        >
          <Clock className="w-3.5 h-3.5 text-slate-400" />
        </motion.span>
        <span className="font-mono text-sm font-semibold text-slate-700 tabular-nums flex items-center leading-none">
          <Digit value={hh[0]} /><Digit value={hh[1]} />
          <span className="px-px text-slate-400">:</span>
          <Digit value={mm[0]} /><Digit value={mm[1]} />
          <span className="px-px text-slate-400">:</span>
          <Digit value={ss[0]} /><Digit value={ss[1]} />
        </span>
        <span className="text-[9px] font-semibold text-slate-300 uppercase tracking-wider ml-0.5">Local</span>
      </div>
    </motion.div>
  )
}

export default function Dashboard() {
  const toast = useToast()
  const [stats, setStats] = useState(null)
  const [pools, setPools] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [waitlistLoading, setWaitlistLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error,   setError]   = useState(null)
  const [lpiData, setLpiData] = useState(null)
  const [clock,   setClock]   = useState(new Date())

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    setError(null)
    try {
      const [statsRes, poolsRes, lpiRes] = await Promise.allSettled([
        getStats(), getPools(), getBrain5Lpi(),
      ])
      if (statsRes.status === 'fulfilled') setStats(statsRes.value.data)
      if (poolsRes.status === 'fulfilled') setPools(poolsRes.value.data)
      if (lpiRes.status  === 'fulfilled') setLpiData(lpiRes.value.data)
      if (statsRes.status === 'rejected') {
        const err = statsRes.reason
        const msg = err.code === 'ERR_NETWORK'
          ? `Cannot reach API at ${BASE_URL} — is the backend running?`
          : err.response?.data?.detail ?? 'Failed to load dashboard data'
        setError(msg)
      }
      setLastUpdated(new Date())
    } catch (err) {
      const msg = err.code === 'ERR_NETWORK'
        ? `Cannot reach API at ${BASE_URL} — is the backend running?`
        : err.response?.data?.detail ?? 'Failed to load dashboard data'
      setError(msg)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  // Live clock — ticks every second
  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  // Auto-refresh every 30 s (silent — no loading spinner)
  useEffect(() => {
    const id = setInterval(() => fetchAll(true), 30_000)
    return () => clearInterval(id)
  }, [fetchAll])

  const handleWaitlistCheck = async () => {
    setWaitlistLoading(true)
    try {
      const res = await checkWaitlist()
      toast(res.data.message, res.data.pool_created ? 'success' : 'info')
      // Surface Phase 3 condensation events to the browser console (#203)
      if ((res.data.phase3_transfers ?? 0) > 0) {
        console.warn('[Phase 3 Condensation]', {
          transfers: res.data.phase3_transfers,
          events:    res.data.phase3_events,
          dissolved: res.data.phase3_dissolved,
        })
      }
      fetchAll(true)
    } catch (err) {
      if (err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')) {
        toast('Server is processing heavy load. Please wait or refresh.', 'error')
      } else {
        toast(err.response?.data?.detail ?? 'Waitlist check failed', 'error')
      }
    } finally {
      setWaitlistLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner className="w-8 h-8" />
      </div>
    )
  }

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          <div className="flex items-center gap-2.5 mt-1 flex-wrap">
            <p className="text-sm text-slate-400">
              {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Loading…'}
            </p>
            <LpiChip lpi={lpiData?.lpi} />
          </div>
        </div>
        <div className="flex items-center gap-2.5 flex-shrink-0">
          {/* Live day + time watch (Framer Motion) — see LiveClock note above */}
          <LiveClock now={clock} />
          <button
            onClick={() => fetchAll(true)}
            disabled={refreshing}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Metric cards */}
      {stats && (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-5">
          <MetricCard
            icon={IndianRupee}
            label="Total Capital Collected"
            value={INR(stats.total_capital_inr)}
            sub="Burned Deposit tokens"
            iconBg="bg-emerald-50"
            iconColor="text-emerald-600"
          />
          <MetricCard
            icon={Users}
            label="Active Users"
            value={stats.active_users}
            sub={`${stats.eliminated_count} eliminated`}
            iconBg="bg-blue-50"
            iconColor="text-blue-600"
          />
          <MetricCard
            icon={LayoutGrid}
            label="Pools Running"
            value={stats.active_pools}
            sub="Active pools"
            iconBg="bg-violet-50"
            iconColor="text-violet-600"
          />
          <MetricCard
            icon={Clock}
            label="Waitlist Queue"
            value={stats.waitlist_count}
            sub="Paid members waiting"
            iconBg="bg-amber-50"
            iconColor="text-amber-600"
          />
        </div>
      )}

      <div className="grid grid-cols-3 gap-5">
        {/* Pool Status */}
        <div className="col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="font-semibold text-slate-800">Active Pools</h2>
            <span className="text-xs text-slate-400">{pools.filter(p => p.status === 'Active').length} pools</span>
          </div>
          {pools.length === 0 ? (
            <div className="px-6 py-12 text-center text-slate-400 text-sm">No pools yet</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Pool</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                  <th className="text-center px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Members</th>
                </tr>
              </thead>
              <tbody>
                {pools.map((pool, i) => (
                  <tr key={pool.id} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}>
                    <td className="px-6 py-3 font-semibold text-slate-800">{pool.name}</td>
                    <td className="px-6 py-3"><StatusBadge status={pool.status} /></td>
                    <td className="px-6 py-3 text-center">
                      <span className={`font-mono font-semibold tabular-nums ${
                        (pool.total_members ?? 0) >= 12 ? 'text-emerald-600' :
                        (pool.total_members ?? 0) >= 8  ? 'text-amber-600'  :
                        'text-red-500'
                      }`}>
                        {pool.total_members ?? 0}/12
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Quick Actions */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100">
            <h2 className="font-semibold text-slate-800">Quick Actions</h2>
          </div>
          <div className="p-6 space-y-3">
            <button
              onClick={handleWaitlistCheck}
              disabled={waitlistLoading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-semibold shadow-sm shadow-blue-200 disabled:opacity-60 transition"
            >
              {waitlistLoading ? <Spinner className="w-4 h-4" /> : <Zap className="w-4 h-4" />}
              Check Waitlist Threshold
            </button>

            {stats && (
              <div className="mt-4 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Tokens Issued</span>
                  <span className="font-semibold text-slate-800">{stats.total_tokens_issued}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Active Tokens</span>
                  <span className="font-semibold text-slate-800">{stats.active_tokens}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Waitlist Progress</span>
                  <span className="font-semibold text-slate-800">{stats.waitlist_count}/24</span>
                </div>
                <div className="w-full bg-slate-100 rounded-full h-2 mt-1">
                  <div
                    className="bg-amber-400 h-2 rounded-full transition-all"
                    style={{ width: `${Math.min(100, (stats.waitlist_count / 24) * 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
