import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Shield, Lock, Zap } from 'lucide-react'

/* ── Scan line ────────────────────────────────────────────────── */
function ScanLine() {
  return (
    <motion.div
      className="absolute inset-x-0 h-px pointer-events-none"
      style={{ background: 'linear-gradient(90deg,transparent,rgba(0,240,255,0.6),transparent)', top: 0 }}
      animate={{ top: ['0%', '100%'] }}
      transition={{ duration: 1.8, repeat: Infinity, ease: 'linear', repeatDelay: 0.3 }}
    />
  )
}

/* ── One slot column ─────────────────────────────────────────── */
function Slot({ names, winner, active, stopped, label, accent }) {
  const [current, setCurrent] = useState(names[0] ?? '---')
  const [speed, setSpeed] = useState(55)
  const intRef = useRef(null)
  const idxRef = useRef(0)

  useEffect(() => {
    if (!active || stopped) {
      clearInterval(intRef.current)
      if (stopped && winner) setCurrent(winner)
      return
    }
    const tick = () => {
      idxRef.current = (idxRef.current + 1) % names.length
      setCurrent(names[idxRef.current])
    }
    clearInterval(intRef.current)
    intRef.current = setInterval(tick, speed)
    return () => clearInterval(intRef.current)
  }, [active, stopped, speed, names, winner])

  // Slow down over time
  useEffect(() => {
    if (!active || stopped) return
    const sid = setInterval(() => setSpeed(s => Math.min(s + 28, 420)), 550)
    return () => clearInterval(sid)
  }, [active, stopped])

  const c = accent === 'purple'
    ? { border: 'rgba(191,0,255,0.35)', glow: stopped ? '0 0 28px rgba(191,0,255,0.6)' : 'none', text: stopped ? '#d580ff' : '#fff', tshadow: stopped ? '0 0 12px #bf00ff' : 'none', badge: 'rgba(191,0,255,0.12)', badgeText: '#d580ff', badgeBorder: 'rgba(191,0,255,0.3)' }
    : { border: 'rgba(0,240,255,0.35)', glow: stopped ? '0 0 28px rgba(0,240,255,0.6)' : 'none', text: stopped ? '#00f0ff' : '#fff', tshadow: stopped ? '0 0 12px #00f0ff' : 'none', badge: 'rgba(0,240,255,0.08)', badgeText: '#00f0ff', badgeBorder: 'rgba(0,240,255,0.25)' }

  return (
    <div className="flex-1 flex flex-col gap-2 min-w-0">
      <div className="rounded-lg px-2 py-1 text-center text-[10px] font-mono font-bold tracking-widest border"
        style={{ background: c.badge, color: c.badgeText, borderColor: c.badgeBorder }}>
        {label}
      </div>
      <motion.div
        className="relative overflow-hidden rounded-2xl flex items-center justify-center"
        style={{ minHeight: 110, background: 'rgba(0,0,0,0.45)', border: `1px solid ${c.border}`, boxShadow: c.glow }}
        animate={stopped ? { scale: [1, 1.03, 1] } : {}}
        transition={{ duration: 0.35 }}
      >
        <ScanLine />
        <AnimatePresence mode="popLayout">
          <motion.p
            key={current}
            initial={{ y: -28, opacity: 0, filter: 'blur(6px)' }}
            animate={{ y: 0,   opacity: 1, filter: 'blur(0px)' }}
            exit={{    y: 28,  opacity: 0 }}
            transition={{ duration: 0.14 }}
            className="font-mono font-black text-lg text-center tracking-widest px-2 break-all"
            style={{ color: c.text, textShadow: c.tshadow }}
          >
            {current}
          </motion.p>
        </AnimatePresence>
        {stopped && (
          <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="absolute top-2 right-2">
            <Lock className="w-3.5 h-3.5 text-emerald-400" strokeWidth={2.5} />
          </motion.div>
        )}
      </motion.div>
    </div>
  )
}

/* ── Main Component ──────────────────────────────────────────── */
const BOOT_LINES = [
  '> CONNECTING TO LOTTERY NODE...',
  '> FETCHING POOL PARTICIPANTS...',
  '> INITIALIZING RNG PROTOCOL...',
  '> ENCRYPTION KEY: VERIFIED ✓',
]

const MOCK_NAMES = [
  'NEXUS_X07','CIPHER_Z03','VOID_PRIME','NOVA_CORE','GHOST_NET',
  'DELTA_HEX','FLUX_ARK','PRISM_BIT','ECHO_SYS','APEX_RAW','ZERO_NODE','VECTOR_PRO',
]

export default function DrawAnimation({ participants, winner1, winner2, onComplete }) {
  const names = (participants?.length >= 2 ? participants : MOCK_NAMES)
  const w1 = winner1 || names[Math.floor(Math.random() * 6)]
  const w2 = winner2 || names[6 + Math.floor(Math.random() * Math.min(6, names.length - 6))]

  const [phase, setPhase] = useState('boot')   // boot | draw | done
  const [progress, setProgress] = useState(0)
  const [s1Stopped, setS1Stopped] = useState(false)
  const [s2Stopped, setS2Stopped] = useState(false)
  const [showWinners, setShowWinners] = useState(false)
  const [visibleLines, setVisibleLines] = useState(0)

  // Boot text reveal
  useEffect(() => {
    BOOT_LINES.forEach((_, i) => {
      setTimeout(() => setVisibleLines(i + 1), i * 500)
    })
  }, [])

  // Progress bar
  useEffect(() => {
    if (phase !== 'boot') return
    const id = setInterval(() => setProgress(p => Math.min(p + 1.8, 100)), 35)
    return () => clearInterval(id)
  }, [phase])

  // Phase timeline
  useEffect(() => {
    const t = [
      setTimeout(() => setPhase('draw'),            2400),
      setTimeout(() => setS1Stopped(true),          7200),
      setTimeout(() => setS2Stopped(true),          8100),
      setTimeout(() => setShowWinners(true),        8900),
      setTimeout(() => { setPhase('done'); onComplete?.() }, 11500),
    ]
    return () => t.forEach(clearTimeout)
  }, [onComplete])

  return (
    <motion.div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center p-5 overflow-hidden"
      style={{ background: 'rgba(2,2,22,0.97)' }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {/* Background particle blobs */}
      <motion.div className="absolute top-0 left-0 w-80 h-80 rounded-full blur-[100px] pointer-events-none opacity-20"
        style={{ background: 'radial-gradient(circle,#0070ff,transparent)' }}
        animate={{ scale: [1, 1.2, 1], x: [0, 30, 0] }} transition={{ duration: 8, repeat: Infinity }} />
      <motion.div className="absolute bottom-0 right-0 w-80 h-80 rounded-full blur-[100px] pointer-events-none opacity-15"
        style={{ background: 'radial-gradient(circle,#bf00ff,transparent)' }}
        animate={{ scale: [1, 1.3, 1], x: [0, -30, 0] }} transition={{ duration: 10, repeat: Infinity }} />

      <div className="w-full max-w-xs space-y-7">
        {/* Header */}
        <div className="text-center space-y-2">
          <motion.div className="flex justify-center" animate={{ rotate: 360 }}
            transition={{ duration: 5, repeat: Infinity, ease: 'linear' }}>
            <div className="w-14 h-14 rounded-full flex items-center justify-center border-2"
              style={{ borderColor: 'rgba(0,240,255,0.4)', boxShadow: '0 0 24px rgba(0,240,255,0.35)' }}>
              <Shield className="w-6 h-6 text-neon-cyan" strokeWidth={1.5} />
            </div>
          </motion.div>
          <p className="text-[10px] font-mono tracking-[0.25em] text-white/40 uppercase">RewardScheme · Lottery Node</p>
          <h2 className="text-3xl font-black text-white tracking-tight">SECURE DRAW</h2>
        </div>

        {/* Boot phase */}
        <AnimatePresence>
          {phase === 'boot' && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.3 } }}
              className="space-y-4">
              <div className="space-y-1.5">
                <div className="flex justify-between text-[10px] font-mono text-white/40">
                  <span>INITIALIZING</span><span>{Math.round(progress)}%</span>
                </div>
                <div className="h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
                  <motion.div className="h-full rounded-full"
                    style={{ width: `${progress}%`, background: 'linear-gradient(90deg,#00f0ff,#0070ff,#bf00ff)' }} />
                </div>
              </div>
              <div className="space-y-2">
                {BOOT_LINES.slice(0, visibleLines).map((line, i) => (
                  <motion.p key={i} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.3 }}
                    className="text-xs font-mono text-emerald-400/80">{line}</motion.p>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Draw slots */}
        <AnimatePresence>
          {phase !== 'boot' && (
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
              <div className="flex gap-3">
                <Slot names={names.slice(0, Math.ceil(names.length / 2))} winner={w1}
                  active label="TIER 1 · L1–L3" accent="cyan"
                  stopped={s1Stopped} />
                <Slot names={names.slice(Math.ceil(names.length / 2))} winner={w2}
                  active label="TIER 2 · L4–L6" accent="purple"
                  stopped={s2Stopped} />
              </div>
              <motion.p className="text-center text-[11px] font-mono text-white/35"
                animate={{ opacity: [0.35, 0.9, 0.35] }} transition={{ duration: 1.4, repeat: Infinity }}>
                {!s1Stopped ? 'DRAWING IN PROGRESS…' : !s2Stopped ? 'TIER 1 LOCKED…' : 'RESULTS CONFIRMED'}
              </motion.p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Winner cards */}
        <AnimatePresence>
          {showWinners && (
            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
              {[
                { winner: w1, tier: 'TIER 1 WINNER', accent: '#00f0ff', bg: 'rgba(0,240,255,0.06)', border: 'rgba(0,240,255,0.25)' },
                { winner: w2, tier: 'TIER 2 WINNER', accent: '#bf00ff', bg: 'rgba(191,0,255,0.06)', border: 'rgba(191,0,255,0.25)' },
              ].map(({ winner, tier, accent, bg, border }) => (
                <motion.div key={winner}
                  initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                  className="rounded-2xl p-4 flex items-center justify-between"
                  style={{ background: bg, border: `1px solid ${border}`, boxShadow: `0 0 24px ${border}` }}>
                  <div>
                    <p className="text-[10px] font-mono tracking-widest mb-0.5" style={{ color: `${accent}80` }}>{tier}</p>
                    <p className="font-mono font-black text-lg tracking-widest"
                      style={{ color: accent, textShadow: `0 0 12px ${accent}` }}>
                      @{winner}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] text-white/30 font-mono">NET PAYOUT</p>
                    <p className="text-lg font-black text-emerald-400">₹4,500</p>
                  </div>
                </motion.div>
              ))}

              {onComplete && (
                <motion.button
                  whileTap={{ scale: 0.96 }}
                  onClick={onComplete}
                  className="w-full btn-primary py-3.5 rounded-2xl mt-2 flex items-center justify-center gap-2"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.8 }}
                >
                  <Zap className="w-4 h-4" /> CLOSE DRAW
                </motion.button>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
