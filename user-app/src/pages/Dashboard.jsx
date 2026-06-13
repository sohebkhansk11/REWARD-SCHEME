import { useEffect, useState, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { LogOut, RefreshCw, Hexagon, Wifi, WifiOff } from 'lucide-react'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import CountdownTimer from '../components/CountdownTimer'
import BottomNav from '../components/BottomNav'
import FlashBanner from '../components/FlashBanner'
import { useUser } from '../context/UserContext'
import { getUser, getWaitlistRank } from '../api/client'

const STATUS_COLORS = {
  Active:        { bg: 'rgba(0,255,136,0.1)',  border: 'rgba(0,255,136,0.3)',  text: '#00ff88' },
  Waitlist:      { bg: 'rgba(255,170,0,0.1)',  border: 'rgba(255,170,0,0.3)',  text: '#ffaa00' },
  Eliminated:    { bg: 'rgba(255,50,50,0.1)',  border: 'rgba(255,50,50,0.3)',  text: '#ff4444' },
  Eliminated_Won:{ bg: 'rgba(191,0,255,0.1)',  border: 'rgba(191,0,255,0.3)',  text: '#d580ff' },
}

function LevelBadge({ level, paymentStatus }) {
  const colors = ['','#00f0ff','#00f0ff','#54b4ff','#ffaa00','#ff6600','#bf00ff']
  const c      = colors[Math.min(level, 6)] ?? '#ffffff'
  const isPaid = paymentStatus === 'Paid'

  return (
    <div className="flex flex-col items-center gap-0.5">
      <div className="relative">
        <Hexagon className="w-14 h-14" style={{ color: c, filter: `drop-shadow(0 0 8px ${c})` }} strokeWidth={1.5} />
        <span className="absolute inset-0 flex items-center justify-center text-xl font-black"
          style={{ color: c, textShadow: `0 0 10px ${c}` }}>
          {level}
        </span>
      </div>
      <span className="text-[10px] font-mono tracking-[0.2em] text-white/35 uppercase">Level</span>
      {paymentStatus && (
        <motion.span
          className="text-[9px] font-black font-mono tracking-widest px-2 py-0.5 rounded-full mt-0.5"
          style={isPaid
            ? { background: 'rgba(0,255,136,0.12)', color: '#00ff88', border: '1px solid rgba(0,255,136,0.25)' }
            : { background: 'rgba(255,80,80,0.10)', color: '#ff5555', border: '1px solid rgba(255,80,80,0.25)' }
          }
          animate={isPaid ? {} : { opacity: [1, 0.45, 1] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        >
          {isPaid ? '✓ PAID' : '✗ UNPAID'}
        </motion.span>
      )}
    </div>
  )
}

// ─── Vault Open Animation Overlay ─────────────────────────────────────────────
// Shows briefly on first Dashboard load for Active-status users as a
// motivational "you're in the vault" moment.
function VaultOpenOverlay({ visible, onDone }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
          onAnimationComplete={() => {
            // Auto-dismiss after the full animation sequence (~2.8 s)
            setTimeout(onDone, 2800)
          }}
        >
          {/* Dark overlay */}
          <motion.div
            className="absolute inset-0"
            style={{ background: 'rgba(3,3,24,0.85)' }}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.85, 0.85, 0] }}
            transition={{ duration: 2.8, times: [0, 0.15, 0.75, 1] }}
          />

          {/* Concentric glow rings */}
          {[180, 140, 100, 65].map((size, i) => (
            <motion.div
              key={size}
              className="absolute rounded-full"
              style={{
                width: size,
                height: size,
                border: `1.5px solid rgba(0,240,255,${0.55 - i * 0.1})`,
                boxShadow: `0 0 ${20 + i * 10}px rgba(0,240,255,${0.25 - i * 0.04})`,
              }}
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: [0, 1.15, 1], opacity: [0, 0.9, 0.6] }}
              transition={{ duration: 0.7, delay: i * 0.12, ease: [0.22, 1, 0.36, 1] }}
            />
          ))}

          {/* Radiating light beams */}
          {[0, 45, 90, 135, 180, 225, 270, 315].map((angle, i) => (
            <motion.div
              key={angle}
              className="absolute"
              style={{
                width: 2,
                height: 120,
                borderRadius: 4,
                background: 'linear-gradient(to top, transparent, rgba(0,240,255,0.6))',
                transformOrigin: 'bottom center',
                transform: `rotate(${angle}deg)`,
                bottom: '50%',
                left: '50%',
                marginLeft: -1,
              }}
              initial={{ scaleY: 0, opacity: 0 }}
              animate={{ scaleY: [0, 1, 0], opacity: [0, 0.7, 0] }}
              transition={{ duration: 1.4, delay: 0.3 + i * 0.05, ease: 'easeOut' }}
            />
          ))}

          {/* Central vault icon */}
          <motion.div
            className="relative z-10 flex flex-col items-center gap-3"
            initial={{ scale: 0.4, opacity: 0 }}
            animate={{ scale: [0.4, 1.1, 1], opacity: [0, 1, 1, 0] }}
            transition={{ duration: 2.6, times: [0, 0.25, 0.55, 1], ease: [0.22, 1, 0.36, 1] }}
          >
            <div
              className="w-20 h-20 rounded-2xl flex items-center justify-center text-4xl"
              style={{
                background: 'rgba(0,240,255,0.10)',
                border:     '2px solid rgba(0,240,255,0.50)',
                boxShadow:  '0 0 40px rgba(0,240,255,0.35)',
              }}
            >
              🔓
            </div>
            <motion.p
              className="font-mono font-black text-xs tracking-[0.35em] uppercase"
              style={{ color: '#00f0ff', textShadow: '0 0 12px rgba(0,240,255,0.6)' }}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: [0, 1, 1, 0] }}
              transition={{ duration: 2.4, delay: 0.3, times: [0, 0.2, 0.7, 1] }}
            >
              Vault Active
            </motion.p>
          </motion.div>

          {/* Outer pulse ring */}
          <motion.div
            className="absolute rounded-full"
            style={{
              width: 260,
              height: 260,
              border: '1px solid rgba(0,240,255,0.18)',
            }}
            initial={{ scale: 0.3, opacity: 0 }}
            animate={{ scale: [0.3, 1.6], opacity: [0.6, 0] }}
            transition={{ duration: 1.8, delay: 0.2, ease: 'easeOut' }}
          />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const { user, logout, refresh } = useUser()
  const nav      = useNavigate()
  const location = useLocation()    // key changes on every navigation — used as effect dep

  const [apiOk,          setApiOk]          = useState(true)
  const [refreshing,     setRefreshing]     = useState(false)
  const [showVault,      setShowVault]      = useState(false)
  const [rankData,       setRankData]       = useState(null)    // { rank, wl_number, total_waiting, status }
  const [rankLoading,    setRankLoading]    = useState(false)
  // IRCTC WL promotion tracking (Phase 4)
  const [prevRank,       setPrevRank]       = useState(null)   // last known rank to detect promotions
  const [promotedToast,  setPromotedToast]  = useState(null)   // "Promoted!" message
  const promotedTimerRef = useRef(null)

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

  // Fetch live waitlist rank — called on every navigation to the Dashboard
  // so the position is always current without a hard reload.
  const fetchRank = async () => {
    setRankLoading(true)
    try {
      const res = await getWaitlistRank()
      if (res.data?.rank != null) {
        const newRank = res.data.rank
        // Detect promotion (rank decreased since last poll)
        if (prevRank !== null && newRank < prevRank) {
          const promoted = prevRank - newRank
          setPromotedToast(
            `🎉 Promoted! ${res.data.wl_number ?? `WL-${newRank}`} ← WL-${prevRank} (+${promoted} spots)`
          )
          clearTimeout(promotedTimerRef.current)
          promotedTimerRef.current = setTimeout(() => setPromotedToast(null), 5_000)
        }
        setPrevRank(newRank)
        setRankData(res.data)
      }
    } catch { /* non-fatal */ }
    finally { setRankLoading(false) }
  }

  // Combined refresh — called by the header button and on every navigation
  const handleRefresh = () => {
    fetchFresh()
    if (user?.status === 'Waitlist') fetchRank()
  }

  // Re-run on every navigation to /dashboard via location.key.
  // React Router v6 gives each navigation a unique key, so this effect fires
  // whether the component just mounted OR the user tapped Home a second time.
  useEffect(() => {
    fetchFresh(true)
    if (user?.status === 'Active') {
      const key = `vault_shown_${user.id}`
      if (!sessionStorage.getItem(key)) { sessionStorage.setItem(key, '1'); setShowVault(true) }
    }
    if (user?.status === 'Waitlist') fetchRank()
  }, [location.key])  // eslint-disable-line

  // Auto-refresh every 30 s — keeps level, payment status, and pool info live
  useEffect(() => {
    const id = setInterval(() => {
      fetchFresh(true)
      if (user?.status === 'Waitlist') fetchRank()
    }, 30_000)
    return () => clearInterval(id)
  }, [user?.status])  // eslint-disable-line

  const handleLogout = () => { logout(); nav('/', { replace: true }) }

  const status = user?.status ?? 'Waitlist'
  const sc     = STATUS_COLORS[status] ?? STATUS_COLORS.Waitlist

  // Prefer human-readable pool name; fall back gracefully
  const poolDisplay = user?.current_pool_name
    ?? (user?.current_pool_id ? `Pool #${user.current_pool_id}` : 'Not Assigned')

  return (
    <div className="min-h-dvh pb-28 relative">
      <Background />

      {/* Vault open animation — Active users only, once per session */}
      <VaultOpenOverlay visible={showVault} onDone={() => setShowVault(false)} />

      {/* Header */}
      <div
        className="sticky top-0 z-30 px-5 pt-12 pb-4 flex items-center justify-between"
        style={{ background: 'rgba(3,3,24,0.7)', backdropFilter: 'blur(20px)' }}
      >
        <div className="min-w-0">
          <p className="text-[10px] font-mono tracking-[0.25em] text-white/30 uppercase">Welcome back</p>
          <p className="font-mono font-bold text-white truncate" style={{ textShadow: '0 0 10px rgba(0,240,255,0.4)' }}>
            @{user?.username ?? '---'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div title={apiOk ? 'API Connected' : 'API Offline'}>
            {apiOk
              ? <Wifi    className="w-4 h-4 text-emerald-400" />
              : <WifiOff className="w-4 h-4 text-red-400" />
            }
          </div>
          <motion.button whileTap={{ scale: 0.9 }} onClick={handleRefresh}
            className="p-2 rounded-xl" style={{ background: 'rgba(255,255,255,0.05)' }}>
            <RefreshCw className={`w-4 h-4 text-white/50 ${refreshing || rankLoading ? 'animate-spin' : ''}`} />
          </motion.button>
          <motion.button whileTap={{ scale: 0.9 }} onClick={handleLogout}
            className="p-2 rounded-xl" style={{ background: 'rgba(255,255,255,0.05)' }}>
            <LogOut className="w-4 h-4 text-white/50" />
          </motion.button>
        </div>
      </div>

      {/* Flash Notification Banners — polled from backend every 60s */}
      <FlashBanner />

      <div className="px-5 space-y-4">
        {/* Pool + Level card */}
        <GlassCard className="p-5" animate>
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-mono tracking-[0.2em] text-white/30 uppercase mb-1">Active Pool</p>
              {/* Uses actual pool name from backend — no more hardcoded "Pool #ID" */}
              <p className="text-2xl font-black text-white truncate">
                {poolDisplay}
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
            <LevelBadge level={user?.current_level ?? 1} paymentStatus={user?.weekly_payment_status} />
          </div>
        </GlassCard>

        {/* ── Waitlist Position Badge ──────────────────────────────────────
            Visible only when status === 'Waitlist'.
            Shows a loading skeleton while the first fetch is in flight,
            then the live rank with a subtle refresh indicator thereafter.
        ────────────────────────────────────────────────────────────────── */}
        {status === 'Waitlist' && (
          <GlassCard className="p-6" animate>

            {/* Card header row */}
            <div className="flex items-center justify-between mb-4">
              <p className="text-[10px] font-mono tracking-[0.25em] text-white/30 uppercase">
                Your Waitlist Position
              </p>
              {/* Spinning indicator whenever a fetch is in progress */}
              {rankLoading && (
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                >
                  <RefreshCw className="w-3.5 h-3.5 text-amber-400/60" />
                </motion.div>
              )}
            </div>

            {/* ── Loading skeleton (first fetch only) ── */}
            {rankLoading && !rankData && (
              <div className="animate-pulse space-y-4">
                <div className="mx-auto h-24 w-52 rounded-2xl"
                  style={{ background: 'rgba(255,170,0,0.07)', border: '1px solid rgba(255,170,0,0.1)' }} />
                <div className="h-2 rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }} />
                <div className="h-3 w-4/5 mx-auto rounded" style={{ background: 'rgba(255,255,255,0.04)' }} />
              </div>
            )}

            {/* ── Live rank display ── */}
            {rankData && (
              <>
                {/* THE MASSIVE BADGE — central hero element */}
                <div
                  className="flex flex-col items-center py-5 mb-5 rounded-2xl"
                  style={{
                    background: 'rgba(255,170,0,0.05)',
                    border:     '1px solid rgba(255,170,0,0.18)',
                    boxShadow:  '0 0 32px rgba(255,170,0,0.06) inset',
                  }}
                >
                  <span className="text-[9px] font-mono tracking-[0.35em] text-white/25 uppercase mb-2">
                    Your Queue Number
                  </span>

                  {/* IRCTC-style WL-XX hero — re-animates on rank change (Phase 4) */}
                  <motion.span
                    key={rankData.rank}
                    className="font-black tabular-nums leading-none"
                    style={{
                      fontSize:   '4.5rem',   // slightly smaller than 8xl to fit WL-XX
                      color:      '#ffaa00',
                      textShadow: '0 0 28px rgba(255,170,0,0.65), 0 0 60px rgba(255,170,0,0.22)',
                      letterSpacing: '-0.02em',
                    }}
                    initial={{ scale: 0.7, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: 'spring', stiffness: 280, damping: 22 }}
                  >
                    {rankData.wl_number ?? `WL-${rankData.rank}`}
                  </motion.span>

                  <span className="mt-2 text-[10px] text-white/30 font-mono">
                    Queue number of{' '}
                    <strong className="text-white/50 font-semibold">
                      {rankData.total_waiting?.toLocaleString('en-IN') ?? '—'}
                    </strong>{' '}
                    waiting
                  </span>

                  {/* "Promoted!" micro-toast */}
                  <AnimatePresence>
                    {promotedToast && (
                      <motion.div
                        initial={{ opacity: 0, y: 8, scale: 0.95 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{   opacity: 0, y: -8, scale: 0.95 }}
                        transition={{ duration: 0.3 }}
                        className="mt-2 px-3 py-1.5 rounded-xl text-[10px] font-bold text-center"
                        style={{
                          background: 'rgba(0,255,136,0.12)',
                          border:     '1px solid rgba(0,255,136,0.3)',
                          color:      '#00ff88',
                        }}
                      >
                        {promotedToast}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                {/* Progress bar — shows how far along in the queue */}
                <div className="mb-4 space-y-2">
                  <div className="flex justify-between text-[9px] font-mono text-white/20 px-0.5">
                    <span>▶ Next to enter pool</span>
                    <span>Back of queue ▶</span>
                  </div>
                  <div
                    className="h-2 rounded-full overflow-hidden"
                    style={{ background: 'rgba(255,255,255,0.05)' }}
                  >
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: 'linear-gradient(90deg, #ffaa00 0%, #ff6600 100%)' }}
                      initial={{ width: '2%' }}
                      animate={{
                        width: `${Math.max(2, Math.min(99,
                          ((rankData.total_waiting - rankData.rank + 1) / rankData.total_waiting) * 100
                        ))}%`,
                      }}
                      transition={{ duration: 1.2, ease: 'easeOut' }}
                    />
                  </div>
                </div>

                {/* Helper text */}
                <p
                  className="text-center text-[11px] leading-relaxed px-1"
                  style={{ color: 'rgba(255,255,255,0.3)' }}
                >
                  Your WL number updates automatically as members ahead enter pools.
                  First-Come, First-Serve queue.
                </p>
              </>
            )}

            {/* ── Edge case: loaded but rank not available ── */}
            {!rankLoading && !rankData && (
              <div className="flex flex-col items-center gap-2 py-6">
                <p className="text-sm text-white/25 font-mono">Position unavailable</p>
                <motion.button
                  whileTap={{ scale: 0.92 }}
                  onClick={fetchRank}
                  className="text-[11px] font-mono text-amber-400/60 hover:text-amber-400 transition-colors flex items-center gap-1.5"
                >
                  <RefreshCw className="w-3 h-3" />
                  Retry
                </motion.button>
              </div>
            )}

          </GlassCard>
        )}

        {/* Countdown — with ambient vault glow when Active */}
        <GlassCard className="p-6" animate>
          <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase text-center mb-5">
            Next Draw · Sunday 7 PM
          </p>
          {/* Vault glow ring around countdown for Active users */}
          {status === 'Active' && (
            <div className="relative flex justify-center mb-4">
              <motion.div
                className="absolute rounded-full"
                style={{
                  width: 200, height: 200,
                  background: 'radial-gradient(circle, rgba(0,240,255,0.06) 0%, transparent 70%)',
                  border: '1px solid rgba(0,240,255,0.08)',
                }}
                animate={{ scale: [1, 1.06, 1], opacity: [0.6, 1, 0.6] }}
                transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
              />
            </div>
          )}
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
