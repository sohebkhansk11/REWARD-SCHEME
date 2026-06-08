import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Lock } from 'lucide-react'
import { useUser } from '../context/UserContext'
import { getUsers } from '../api/client'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import BottomNav from '../components/BottomNav'
import CountdownTimer from '../components/CountdownTimer'

// ─── Payout matrix ────────────────────────────────────────────────────────────
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

// ─── Indian Rupee format: ₹ 5,500 💸 ─────────────────────────────────────────
const INR = (v) => `₹ ${Number(v).toLocaleString('en-IN')} 💸`

// ─── Tier accent colours ──────────────────────────────────────────────────────
const TIER_COLOR = [
  '#00f0ff','#00c8ff','#0090ff',
  '#bf00ff','#9900dd','#ff00aa',
  '#ff4400','#ff6600','#ff8800',
  '#ffaa00','#ffcc00','#ffe500',
]

// ─── Floating gem particle ────────────────────────────────────────────────────
function GemParticle({ dx, dy, delay }) {
  return (
    <motion.span
      className="absolute text-sm pointer-events-none select-none"
      style={{ left: '50%', top: '50%', marginLeft: -8, marginTop: -8 }}
      initial={{ opacity: 0, x: 0, y: 0, scale: 0 }}
      animate={{
        opacity: [0, 0.9, 0.9, 0],
        x: [0, dx * 0.5, dx],
        y: [0, dy * 0.5, dy],
        scale: [0, 1.1, 0.6],
      }}
      transition={{
        duration: 2.6,
        delay,
        repeat: Infinity,
        repeatDelay: 1.2 + Math.random() * 1.5,
        ease: 'easeOut',
      }}
    >
      💎
    </motion.span>
  )
}

const GEM_POSITIONS = [
  { dx: -70, dy: -55, delay: 0    },
  { dx:  70, dy: -50, delay: 0.4  },
  { dx: -80, dy:  16, delay: 0.85 },
  { dx:  80, dy:  20, delay: 0.2  },
  { dx: -34, dy:  80, delay: 1.15 },
  { dx:  34, dy:  84, delay: 0.65 },
  { dx: -58, dy: -78, delay: 1.4  },
  { dx:  58, dy: -74, delay: 1.9  },
]

// ─── Premium Vault Hero ───────────────────────────────────────────────────────
function VaultHero() {
  return (
    <div className="relative flex items-center justify-center" style={{ height: 200 }}>

      {/* Outer ambient glow */}
      <motion.div
        className="absolute rounded-full pointer-events-none"
        style={{
          width: 210, height: 210,
          background: 'radial-gradient(circle, rgba(0,240,255,0.10) 0%, transparent 70%)',
        }}
        animate={{ scale: [1, 1.18, 1], opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* Rotating outer ring */}
      <motion.div
        className="absolute rounded-2xl pointer-events-none"
        style={{
          width: 154, height: 154,
          border: '1px solid rgba(0,240,255,0.18)',
        }}
        animate={{ rotate: 360 }}
        transition={{ duration: 18, repeat: Infinity, ease: 'linear' }}
      />

      {/* Pulsing inner ring */}
      {[140, 122].map((size, i) => (
        <motion.div
          key={i}
          className="absolute rounded-2xl pointer-events-none"
          style={{
            width: size, height: size,
            border: `1px solid rgba(0,240,255,${0.30 - i * 0.10})`,
          }}
          animate={{ scale: [1, 1.04, 1], opacity: [0.6, 1, 0.6] }}
          transition={{ duration: 2.2 + i * 0.6, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}

      {/* Floating gems */}
      {GEM_POSITIONS.map((g, i) => <GemParticle key={i} {...g} />)}

      {/* ── Vault body ────────────────────────────────────────────── */}
      <motion.div
        className="relative z-10 rounded-2xl flex items-center justify-center overflow-hidden"
        style={{
          width: 112, height: 112,
          background: 'linear-gradient(145deg, rgba(22,32,60,0.98) 0%, rgba(8,12,32,1) 100%)',
          border: '2px solid rgba(0,240,255,0.50)',
          boxShadow:
            '0 0 40px rgba(0,240,255,0.30), 0 0 90px rgba(0,200,255,0.12), ' +
            'inset 0 1px 0 rgba(255,255,255,0.08), inset 0 -1px 0 rgba(0,0,0,0.5)',
        }}
        animate={{
          y: [0, -8, 0],
          boxShadow: [
            '0 0 30px rgba(0,240,255,0.25), 0 0 70px rgba(0,200,255,0.10)',
            '0 0 55px rgba(0,240,255,0.55), 0 0 110px rgba(0,200,255,0.22)',
            '0 0 30px rgba(0,240,255,0.25), 0 0 70px rgba(0,200,255,0.10)',
          ],
        }}
        transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
      >
        {/* Metallic sheen */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              'linear-gradient(135deg, rgba(255,255,255,0.06) 0%, transparent 50%, rgba(0,0,0,0.15) 100%)',
          }}
        />

        {/* Rotating dial ring */}
        <motion.div
          className="absolute rounded-full"
          style={{
            width: 78, height: 78,
            border: '1.5px solid rgba(0,240,255,0.35)',
            borderDasharray: '4 6',
          }}
          animate={{ rotate: -360 }}
          transition={{ duration: 12, repeat: Infinity, ease: 'linear' }}
        />

        {/* Inner dial */}
        <motion.div
          className="absolute rounded-full"
          style={{
            width: 52, height: 52,
            background: 'rgba(0,240,255,0.04)',
            border: '1px solid rgba(0,240,255,0.22)',
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: 8, repeat: Infinity, ease: 'linear' }}
        />

        {/* Lock icon centre */}
        <motion.div
          className="relative z-10 flex items-center justify-center"
          animate={{ scale: [1, 1.06, 1] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
        >
          <Lock
            className="w-8 h-8"
            style={{
              color: '#00f0ff',
              filter: 'drop-shadow(0 0 10px rgba(0,240,255,0.8)) drop-shadow(0 0 20px rgba(0,240,255,0.4))',
            }}
            strokeWidth={1.5}
          />
        </motion.div>

        {/* Corner bolt markers */}
        {[
          'top-2 left-2', 'top-2 right-2',
          'bottom-2 left-2', 'bottom-2 right-2'
        ].map((pos, i) => (
          <div
            key={i}
            className={`absolute w-1.5 h-1.5 rounded-full ${pos}`}
            style={{ background: 'rgba(0,240,255,0.40)', boxShadow: '0 0 4px rgba(0,240,255,0.5)' }}
          />
        ))}
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
      <div
        className="w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-[10px] font-black"
        style={{
          background: 'rgba(0,240,255,0.08)',
          border: '1px solid rgba(0,240,255,0.25)',
          color: '#00f0ff',
        }}
      >
        {index + 1}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-mono font-semibold text-white/80 truncate">@{winner.username}</p>
        <p className="text-[10px] font-mono text-white/30 mt-0.5">Level {winner.current_level} · Vault collected</p>
      </div>
      {payout && (
        <p className="text-xs font-black flex-shrink-0 font-mono"
          style={{ color: '#00ff88', textShadow: '0 0 8px rgba(0,255,136,0.4)' }}>
          +₹ {payout.toLocaleString('en-IN')}
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
    } catch { setWinners([]) }
    finally { setLoadingWinners(false) }
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
        <h1 className="text-2xl font-black text-white">BACHAT VAULT</h1>
      </div>

      <div className="px-5 space-y-5">

        {/* ── Hero: Vault + Countdown ─────────────────────────── */}
        <GlassCard animate className="relative p-5 text-center overflow-hidden" neon="none">
          <div
            className="absolute inset-0 rounded-2xl pointer-events-none"
            style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(0,240,255,0.07), transparent 65%)' }}
          />
          <p className="text-[10px] font-mono tracking-[0.25em] text-white/30 uppercase mb-1 relative z-10">
            Next Draw
          </p>
          <div className="relative z-10">
            <VaultHero />
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
                  border: '1px solid rgba(0,240,255,0.30)',
                  boxShadow: '0 0 24px rgba(0,240,255,0.10)',
                }}
              >
                <div className="absolute inset-y-0 left-0 w-1 rounded-l-2xl"
                  style={{ background: 'linear-gradient(180deg,#00f0ff,#0090ff)' }} />
                <div className="absolute inset-0 pointer-events-none rounded-2xl"
                  style={{ background: 'radial-gradient(ellipse at 5% 50%, rgba(0,240,255,0.07), transparent 55%)' }} />

                <div className="flex items-start justify-between mb-4 pl-3">
                  <div>
                    <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase">
                      Your Standing
                    </p>
                    <div className="flex items-baseline gap-2 mt-1">
                      <motion.span
                        className="text-4xl font-black"
                        style={{ color: '#00f0ff', textShadow: '0 0 24px rgba(0,240,255,0.6)' }}
                        animate={{ textShadow: ['0 0 16px rgba(0,240,255,0.4)', '0 0 32px rgba(0,240,255,0.8)', '0 0 16px rgba(0,240,255,0.4)'] }}
                        transition={{ duration: 2, repeat: Infinity }}
                      >
                        L{userLevel}
                      </motion.span>
                      <span className="text-xs text-white/35 font-mono">Week {userLevel} of 6</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] font-mono text-white/30 uppercase">Win Now</p>
                    <p className="text-lg font-black mt-0.5 font-mono"
                      style={{ color: '#00ff88', textShadow: '0 0 14px rgba(0,255,136,0.45)' }}>
                      {currentPayout ? `₹ ${currentPayout.net.toLocaleString('en-IN')}` : '—'}
                    </p>
                  </div>
                </div>

                {/* 6-pip progress */}
                <div className="pl-3">
                  <div className="flex gap-1.5">
                    {[1, 2, 3, 4, 5, 6].map(l => (
                      <div key={l} className="flex-1 space-y-1">
                        <motion.div
                          className="h-2 rounded-full"
                          style={{
                            background:
                              l < userLevel  ? 'linear-gradient(90deg,#00f0ff,#0090ff)' :
                              l === userLevel ? 'linear-gradient(90deg,#66f5ff,#00f0ff)' :
                              'rgba(255,255,255,0.07)',
                            boxShadow: l === userLevel ? '0 0 8px rgba(0,240,255,0.55)' : 'none',
                          }}
                          animate={l === userLevel
                            ? { boxShadow: ['0 0 4px rgba(0,240,255,0.3)', '0 0 14px rgba(0,240,255,0.7)', '0 0 4px rgba(0,240,255,0.3)'] }
                            : {}}
                          transition={{ duration: 1.5, repeat: Infinity }}
                        />
                        <p className="text-[8px] font-mono text-center"
                          style={{ color: l <= userLevel ? 'rgba(0,240,255,0.5)' : 'rgba(255,255,255,0.12)' }}>
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

        {/* ── Payout matrix L1–L12 ───────────────────────────── */}
        <GlassCard animate className="p-5" neon="none">
          <div className="flex items-center justify-between mb-4">
            <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase">
              Payout Matrix
            </p>
            <span className="text-[10px] font-mono text-white/20">Net after ₹ 500 fee</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {PAYOUT_TABLE.map(({ level, net }) => {
              const color  = TIER_COLOR[level - 1]
              const isMe   = level === userLevel && userStatus === 'Active'
              const isPast = level < userLevel   && userStatus === 'Active'

              return (
                <motion.div
                  key={level}
                  className="rounded-xl px-3 py-2.5 flex items-center justify-between relative"
                  style={{
                    background: isMe
                      ? 'rgba(0,240,255,0.08)'
                      : isPast ? 'rgba(255,255,255,0.03)' : 'rgba(255,255,255,0.025)',
                    border: isMe
                      ? '1px solid rgba(0,240,255,0.45)'
                      : `1px solid rgba(255,255,255,${isPast ? '0.07' : '0.04'})`,
                  }}
                  animate={isMe
                    ? { boxShadow: ['0 0 6px rgba(0,240,255,0.15)', '0 0 18px rgba(0,240,255,0.40)', '0 0 6px rgba(0,240,255,0.15)'] }
                    : {}}
                  transition={{ duration: 1.8, repeat: Infinity }}
                >
                  {/* Level label */}
                  <div className="flex items-center gap-2">
                    <div
                      className="w-6 h-6 rounded-lg flex items-center justify-center text-[9px] font-black flex-shrink-0"
                      style={{
                        background: `${color}18`,
                        border: `1px solid ${color}44`,
                        color,
                      }}
                    >
                      {level}
                    </div>
                    {isMe && (
                      <span
                        className="text-[8px] font-black px-1.5 py-0.5 rounded-full"
                        style={{ background: 'rgba(0,240,255,0.2)', color: '#00f0ff' }}
                      >
                        YOU
                      </span>
                    )}
                  </div>

                  {/* Payout */}
                  <p
                    className="text-[11px] font-black font-mono"
                    style={{
                      color: isMe ? '#00f0ff' : isPast ? 'rgba(255,255,255,0.30)' : 'rgba(255,255,255,0.60)',
                      textShadow: isMe ? '0 0 8px rgba(0,240,255,0.5)' : 'none',
                    }}
                  >
                    ₹ {net.toLocaleString('en-IN')} 💸
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
                style={{ border: '2px solid rgba(0,240,255,0.15)', borderTopColor: '#00f0ff' }}
                animate={{ rotate: 360 }}
                transition={{ duration: 0.75, repeat: Infinity, ease: 'linear' }}
              />
            </div>
          ) : winners.length === 0 ? (
            <div className="py-8 text-center space-y-2">
              <motion.div
                className="text-3xl"
                animate={{ y: [0, -5, 0] }}
                transition={{ duration: 2, repeat: Infinity }}
              >
                🏦
              </motion.div>
              <p className="text-xs font-mono text-white/20">No winners recorded yet</p>
              <p className="text-[10px] text-white/12">The first vault opens this Sunday!</p>
            </div>
          ) : (
            <div>
              {winners.map((w, i) => <WinnerRow key={w.id} winner={w} index={i} />)}
            </div>
          )}
        </GlassCard>

      </div>
      <BottomNav />
    </div>
  )
}
