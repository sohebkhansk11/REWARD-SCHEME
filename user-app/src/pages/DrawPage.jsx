import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useUser } from '../context/UserContext'
import { getUsers } from '../api/client'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import BottomNav from '../components/BottomNav'
import CountdownTimer from '../components/CountdownTimer'

// ─── Payout matrix ────────────────────────────────────────────────────────────
// L1–L6: exact values from the Smart Pairing algorithm.
// L7–L12: extended projection displayed to show the long-game potential.
const PAYOUT_TABLE = [
  { level: 1,  net: 2000  },
  { level: 2,  net: 3000  },
  { level: 3,  net: 4000  },
  { level: 4,  net: 5500  },
  { level: 5,  net: 6500  },
  { level: 6,  net: 8000  },
  { level: 7,  net: 10000 },
  { level: 8,  net: 12500 },
  { level: 9,  net: 15500 },
  { level: 10, net: 19000 },
  { level: 11, net: 23000 },
  { level: 12, net: 28000 },
]

const INR = (v) => `₹${Number(v).toLocaleString('en-IN')}`

// ─── Tier accent colours ──────────────────────────────────────────────────────
const TIER_COLOR = [
  '#00f0ff','#00c8ff','#0090ff',   // L1-L3 cyan
  '#bf00ff','#9900dd','#ff00aa',   // L4-L6 purple
  '#ff4400','#ff6600','#ff8800',   // L7-L9 orange
  '#ffaa00','#ffcc00','#ffe500',   // L10-L12 gold
]

// ─── Floating coin ─────────────────────────────────────────────────────────────
function FloatingCoin({ dx, dy, delay }) {
  return (
    <motion.span
      className="absolute text-base pointer-events-none select-none"
      style={{ left: '50%', top: '50%', marginLeft: -8, marginTop: -8 }}
      initial={{ opacity: 0, x: 0, y: 0, scale: 0 }}
      animate={{
        opacity: [0, 1, 1, 0],
        x: [0, dx * 0.5, dx],
        y: [0, dy * 0.5, dy],
        scale: [0, 1.1, 0.7],
        rotate: [0, 180, 360],
      }}
      transition={{
        duration: 2.8,
        delay,
        repeat: Infinity,
        repeatDelay: 1 + Math.random() * 1.5,
        ease: 'easeOut',
      }}
    >
      💰
    </motion.span>
  )
}

const COIN_POSITIONS = [
  { dx: -72, dy: -58, delay: 0    },
  { dx:  72, dy: -52, delay: 0.4  },
  { dx: -82, dy:  18, delay: 0.85 },
  { dx:  82, dy:  22, delay: 0.2  },
  { dx: -36, dy:  82, delay: 1.15 },
  { dx:  36, dy:  86, delay: 0.65 },
  { dx: -60, dy: -80, delay: 1.4  },
  { dx:  60, dy: -76, delay: 1.9  },
]

// ─── Piggy Bank Hero ───────────────────────────────────────────────────────────
function PiggyBankHero() {
  return (
    <div className="relative flex items-center justify-center" style={{ height: 190 }}>
      {/* Pulsing glow rings */}
      {[160, 130, 106].map((size, i) => (
        <motion.div
          key={i}
          className="absolute rounded-full pointer-events-none"
          style={{
            width: size,
            height: size,
            border: `1px solid rgba(255,180,0,${0.45 - i * 0.12})`,
          }}
          animate={{
            scale:   [1, 1.07 - i * 0.01, 1],
            opacity: [0.5, 1, 0.5],
          }}
          transition={{ duration: 2.2 + i * 0.5, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}

      {/* Background radial bloom */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          width: 200, height: 200,
          background: 'radial-gradient(circle, rgba(255,180,0,0.18) 0%, transparent 70%)',
        }}
        animate={{ scale: [1, 1.15, 1], opacity: [0.6, 1, 0.6] }}
        transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* Floating coins */}
      {COIN_POSITIONS.map((c, i) => <FloatingCoin key={i} {...c} />)}

      {/* Main body */}
      <motion.div
        className="relative z-10 flex items-center justify-center rounded-full"
        style={{
          width: 112,
          height: 112,
          background: 'radial-gradient(circle at 35% 35%, rgba(255,210,60,0.22), rgba(255,140,0,0.10))',
          border: '2px solid rgba(255,185,0,0.55)',
          boxShadow:
            '0 0 40px rgba(255,180,0,0.4), 0 0 80px rgba(255,140,0,0.18), inset 0 0 30px rgba(255,200,60,0.08)',
        }}
        animate={{
          y: [0, -9, 0],
          boxShadow: [
            '0 0 40px rgba(255,180,0,0.4), 0 0 80px rgba(255,140,0,0.18)',
            '0 0 60px rgba(255,180,0,0.6), 0 0 110px rgba(255,140,0,0.28)',
            '0 0 40px rgba(255,180,0,0.4), 0 0 80px rgba(255,140,0,0.18)',
          ],
        }}
        transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }}
      >
        {/* Coin slot */}
        <motion.div
          className="absolute top-2.5 left-1/2 -translate-x-1/2 rounded-full"
          style={{ width: 22, height: 5, background: 'rgba(255,180,0,0.65)', boxShadow: '0 0 6px rgba(255,180,0,0.5)' }}
          animate={{ scaleX: [1, 1.4, 1] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* Pig emoji */}
        <span style={{ fontSize: 56, filter: 'drop-shadow(0 0 14px rgba(255,180,0,0.65))' }}>
          🐷
        </span>
      </motion.div>
    </div>
  )
}

// ─── Winner row ────────────────────────────────────────────────────────────────
function WinnerRow({ winner, index }) {
  const row    = PAYOUT_TABLE.find(r => r.level === winner.current_level)
  const payout = row ? row.net : null
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1,  x: 0   }}
      transition={{ delay: index * 0.07 }}
      className="flex items-center gap-3 py-2.5 border-b last:border-0"
      style={{ borderColor: 'rgba(255,255,255,0.05)' }}
    >
      {/* Rank badge */}
      <div
        className="w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-[10px] font-black"
        style={{
          background: 'rgba(255,180,0,0.1)',
          border: '1px solid rgba(255,180,0,0.3)',
          color: '#ffb400',
        }}
      >
        {index + 1}
      </div>

      {/* Name + level */}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-mono font-semibold text-white/80 truncate">@{winner.username}</p>
        <p className="text-[10px] font-mono text-white/30 mt-0.5">
          Level {winner.current_level} · Vault collected
        </p>
      </div>

      {/* Payout */}
      {payout && (
        <p
          className="text-xs font-black flex-shrink-0"
          style={{ color: '#00ff88', textShadow: '0 0 8px rgba(0,255,136,0.4)' }}
        >
          +{INR(payout)}
        </p>
      )}
    </motion.div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────
export default function DrawPage() {
  const { user } = useUser()
  const userLevel  = user?.current_level ?? 1
  const userStatus = user?.status ?? null

  const [winners, setWinners]             = useState([])
  const [loadingWinners, setLoadingWinners] = useState(true)

  const fetchWinners = useCallback(async () => {
    setLoadingWinners(true)
    try {
      const res = await getUsers({ limit: 200 })
      const won = (res.data || [])
        .filter(u => u.status === 'Eliminated_Won')
        .sort((a, b) => new Date(b.join_date) - new Date(a.join_date))
        .slice(0, 10)
      setWinners(won)
    } catch {
      setWinners([])
    } finally {
      setLoadingWinners(false)
    }
  }, [])

  useEffect(() => { fetchWinners() }, [fetchWinners])

  const currentPayout = PAYOUT_TABLE.find(r => r.level === userLevel)

  return (
    <div className="min-h-dvh pb-28 relative">
      <Background />

      {/* ── Sticky header ──────────────────────────────────────── */}
      <div
        className="sticky top-0 z-30 px-5 pt-12 pb-4"
        style={{ background: 'rgba(3,3,24,0.75)', backdropFilter: 'blur(20px)' }}
      >
        <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase">Weekly Event</p>
        <h1 className="text-2xl font-black text-white">PIGGY VAULT</h1>
      </div>

      <div className="px-5 space-y-5">

        {/* ── Hero: Piggy Bank + Countdown ───────────────────── */}
        <GlassCard animate className="relative p-5 text-center overflow-hidden" neon="none">
          {/* Golden tint overlay */}
          <div
            className="absolute inset-0 rounded-2xl pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(255,180,0,0.09), transparent 65%)' }}
          />

          <p className="text-[10px] font-mono tracking-[0.25em] text-white/30 uppercase mb-1 relative z-10">
            Next Draw
          </p>

          <div className="relative z-10">
            <PiggyBankHero />
          </div>

          <p className="text-[11px] font-mono text-white/30 mb-3 relative z-10">
            Every Sunday · 7:00 PM IST
          </p>

          <div className="relative z-10">
            <CountdownTimer />
          </div>
        </GlassCard>

        {/* ── User current standing (Active members only) ────── */}
        <AnimatePresence>
          {userStatus === 'Active' && (
            <motion.div
              key="standing"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1,  y: 0  }}
              exit={{    opacity: 0,  y: -8  }}
              transition={{ duration: 0.35 }}
            >
              <div
                className="rounded-2xl p-5 relative overflow-hidden"
                style={{
                  background: 'rgba(8,8,40,0.65)',
                  border: '1px solid rgba(255,180,0,0.38)',
                  boxShadow: '0 0 28px rgba(255,180,0,0.12)',
                }}
              >
                {/* Side glow */}
                <div
                  className="absolute inset-y-0 left-0 w-1 rounded-l-2xl"
                  style={{ background: 'linear-gradient(180deg,#ffb400,#ff8800)' }}
                />
                <div
                  className="absolute inset-0 pointer-events-none rounded-2xl"
                  style={{
                    background:
                      'radial-gradient(ellipse at 5% 50%, rgba(255,180,0,0.08), transparent 55%)',
                  }}
                />

                <div className="flex items-start justify-between mb-4 pl-3">
                  <div>
                    <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase">
                      Your Current Standing
                    </p>
                    <div className="flex items-baseline gap-2 mt-1">
                      <motion.span
                        className="text-4xl font-black"
                        style={{ color: '#ffb400', textShadow: '0 0 24px rgba(255,180,0,0.55)' }}
                        animate={{ textShadow: ['0 0 16px rgba(255,180,0,0.4)', '0 0 32px rgba(255,180,0,0.7)', '0 0 16px rgba(255,180,0,0.4)'] }}
                        transition={{ duration: 2, repeat: Infinity }}
                      >
                        L{userLevel}
                      </motion.span>
                      <span className="text-xs text-white/35 font-mono">
                        Week {userLevel} of 6
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] font-mono text-white/30 uppercase">Win Now =</p>
                    <p
                      className="text-xl font-black mt-0.5"
                      style={{ color: '#00ff88', textShadow: '0 0 14px rgba(0,255,136,0.45)' }}
                    >
                      {currentPayout ? INR(currentPayout.net) : '—'}
                    </p>
                  </div>
                </div>

                {/* 6-pip progress */}
                <div className="pl-3 space-y-2">
                  <div className="flex gap-1.5">
                    {[1, 2, 3, 4, 5, 6].map(l => (
                      <div key={l} className="flex-1 space-y-1">
                        <motion.div
                          className="h-2 rounded-full"
                          style={{
                            background:
                              l < userLevel
                                ? 'linear-gradient(90deg,#ffb400,#ff8800)'
                                : l === userLevel
                                ? 'linear-gradient(90deg,#ffe066,#ffb400)'
                                : 'rgba(255,255,255,0.07)',
                            boxShadow: l === userLevel ? '0 0 8px rgba(255,180,0,0.55)' : 'none',
                          }}
                          animate={
                            l === userLevel
                              ? { boxShadow: ['0 0 4px rgba(255,180,0,0.4)', '0 0 14px rgba(255,180,0,0.7)', '0 0 4px rgba(255,180,0,0.4)'] }
                              : {}
                          }
                          transition={{ duration: 1.5, repeat: Infinity }}
                        />
                        <p className="text-[8px] font-mono text-center"
                          style={{ color: l <= userLevel ? 'rgba(255,180,0,0.6)' : 'rgba(255,255,255,0.12)' }}>
                          L{l}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Waitlist status card */}
        {userStatus === 'Waitlist' && (
          <GlassCard animate className="p-4 flex items-center gap-3">
            <span className="text-2xl">⏳</span>
            <div>
              <p className="text-xs font-mono font-bold text-white/70">ON WAITLIST</p>
              <p className="text-[11px] text-white/35 mt-0.5 leading-relaxed">
                You'll enter an active pool as soon as a vacancy opens after the next Sunday draw.
              </p>
            </div>
          </GlassCard>
        )}

        {/* ── How the draw works ─────────────────────────────── */}
        <GlassCard animate className="p-5">
          <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-4">
            How the Draw Works
          </p>
          <div className="space-y-3.5">
            {[
              { icon: '🎯', label: 'Low-Tier Draw',   color: '#00f0ff', desc: 'One winner randomly selected from members at Level 1–3' },
              { icon: '🏆', label: 'High-Tier Draw',  color: '#bf00ff', desc: 'One winner randomly selected from members at Level 4–6' },
              { icon: '🔄', label: 'Instant Replace', color: '#ffb400', desc: 'Both slots filled immediately from the paid Waitlist' },
              { icon: '📈', label: 'Level Advance',   color: '#00ff88', desc: 'Every surviving member moves up one level after the draw' },
            ].map(({ icon, label, color, desc }) => (
              <div key={label} className="flex gap-3 items-start">
                <span className="text-xl flex-shrink-0 mt-0.5">{icon}</span>
                <div>
                  <p className="text-xs font-mono font-semibold" style={{ color }}>{label}</p>
                  <p className="text-[11px] text-white/35 mt-0.5 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* ── Payout matrix L1–L12 ───────────────────────────── */}
        <GlassCard animate className="p-5" neon="none">
          <div className="flex items-center justify-between mb-4">
            <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase">
              Payout Matrix
            </p>
            <span className="text-[10px] font-mono text-white/20">Net after ₹500 platform fee</span>
          </div>

          <div className="grid grid-cols-4 gap-1.5">
            {PAYOUT_TABLE.map(({ level, net }) => {
              const color     = TIER_COLOR[level - 1]
              const isMe      = level === userLevel && userStatus === 'Active'
              const isPast    = level < userLevel  && userStatus === 'Active'

              return (
                <motion.div
                  key={level}
                  className="rounded-xl p-2.5 text-center relative"
                  style={{
                    background: isMe
                      ? 'rgba(255,180,0,0.12)'
                      : isPast
                      ? 'rgba(255,255,255,0.04)'
                      : 'rgba(255,255,255,0.025)',
                    border: isMe
                      ? '1px solid rgba(255,180,0,0.5)'
                      : `1px solid rgba(255,255,255,${isPast ? '0.07' : '0.04'})`,
                  }}
                  animate={isMe
                    ? { boxShadow: ['0 0 8px rgba(255,180,0,0.2)', '0 0 20px rgba(255,180,0,0.45)', '0 0 8px rgba(255,180,0,0.2)'] }
                    : {}}
                  transition={{ duration: 1.8, repeat: Infinity }}
                >
                  {isMe && (
                    <span
                      className="absolute -top-2 left-1/2 -translate-x-1/2 text-[8px] font-black px-1.5 py-0.5 rounded-full"
                      style={{ background: '#ffb400', color: '#000' }}
                    >
                      YOU
                    </span>
                  )}
                  <p className="text-[9px] font-mono" style={{ color: `${color}88` }}>L{level}</p>
                  <p className="text-xs font-black mt-0.5"
                    style={{
                      color: isMe ? '#ffb400' : isPast ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.65)',
                      textShadow: isMe ? '0 0 8px rgba(255,180,0,0.4)' : 'none',
                    }}>
                    {net >= 1000 ? `₹${net / 1000}k` : `₹${net}`}
                  </p>
                </motion.div>
              )
            })}
          </div>

          <p className="text-[10px] text-white/15 font-mono mt-3 text-center">
            L7–L12 represent extended pool projections
          </p>
        </GlassCard>

        {/* ── Recent Winners ─────────────────────────────────── */}
        <GlassCard animate className="p-5" neon="none">
          <div className="flex items-center justify-between mb-4">
            <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase">
              🏆 Recent Winners
            </p>
            <motion.button
              whileTap={{ scale: 0.9 }}
              onClick={fetchWinners}
              className="text-[10px] font-mono text-white/25 hover:text-white/50 transition-colors px-2 py-1"
            >
              ↺ Refresh
            </motion.button>
          </div>

          {loadingWinners ? (
            <div className="py-8 flex items-center justify-center">
              <motion.div
                className="w-6 h-6 rounded-full"
                style={{ border: '2px solid rgba(255,180,0,0.15)', borderTopColor: '#ffb400' }}
                animate={{ rotate: 360 }}
                transition={{ duration: 0.75, repeat: Infinity, ease: 'linear' }}
              />
            </div>
          ) : winners.length === 0 ? (
            <div className="py-8 text-center space-y-2">
              <motion.p
                className="text-3xl"
                animate={{ y: [0, -5, 0] }}
                transition={{ duration: 2, repeat: Infinity }}
              >
                🐷
              </motion.p>
              <p className="text-xs font-mono text-white/20">No winners recorded yet</p>
              <p className="text-[10px] text-white/12">The first vault burst happens this Sunday!</p>
            </div>
          ) : (
            <div>
              {winners.map((w, i) => (
                <WinnerRow key={w.id} winner={w} index={i} />
              ))}
            </div>
          )}
        </GlassCard>

      </div>

      <BottomNav />
    </div>
  )
}
