import { useState, useEffect, useCallback } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

const BASE_URL = import.meta.env.VITE_API_URL || 'https://reward-scheme-api.onrender.com'

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function decompose(diffMs) {
  const d = Math.max(0, diffMs)
  return {
    d: Math.floor(d / 86400000),
    h: Math.floor((d % 86400000) / 3600000),
    m: Math.floor((d % 3600000) / 60000),
    s: Math.floor((d % 60000) / 1000),
  }
}

// Animated flip digit
function Digit({ value }) {
  const str = String(value).padStart(2, '0')
  return (
    <div className="relative overflow-hidden" style={{ height: '1.15em' }}>
      <AnimatePresence mode="popLayout">
        <motion.span
          key={str}
          initial={{ y: '-100%', opacity: 0 }}
          animate={{ y: '0%',   opacity: 1 }}
          exit={{    y: '100%', opacity: 0 }}
          transition={{ duration: 0.25, ease: [0.25, 1, 0.5, 1] }}
          className="block tabular-nums"
        >
          {str}
        </motion.span>
      </AnimatePresence>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// CountdownTimer
//
// Two-flag rule (from backend):
//   preparation_valid = true   →  T-2H preparation job has run
//   countdown_active  = true   →  admin hasn't paused the countdown
//
// ONLY when BOTH flags are true does the live countdown show.
// Otherwise a static "Next draw: Sunday 7 PM IST" message is rendered.
// This prevents a client-side computed timer from ticking away when the
// draw hasn't actually been prepared yet.
// ─────────────────────────────────────────────────────────────────────────────
export default function CountdownTimer() {
  const [countdownActive, setCountdownActive] = useState(false)
  const [drawTimeMs,      setDrawTimeMs]      = useState(null)   // epoch ms
  const [t, setT] = useState({ d: 0, h: 0, m: 0, s: 0 })

  // ── Poll /draw/countdown every 30 s ───────────────────────────────────────
  // Uses the authoritative two-flag response from the backend.
  const pollCountdown = useCallback(async () => {
    try {
      const res  = await fetch(`${BASE_URL}/draw/countdown`)
      if (!res.ok) return
      const data = await res.json()

      // Both flags must be true to activate the countdown display
      const active = !!(data.countdown_active && data.preparation_valid)
      setCountdownActive(active)
      setDrawTimeMs(
        active && data.draw_time_utc
          ? new Date(data.draw_time_utc).getTime()
          : null
      )
    } catch {
      // Network error — keep existing display state, don't flash the UI
    }
  }, [])

  useEffect(() => {
    pollCountdown()                               // immediate on mount
    const id = setInterval(pollCountdown, 30_000) // then every 30 s
    return () => clearInterval(id)
  }, [pollCountdown])

  // ── Tick every second while countdown is active ───────────────────────────
  useEffect(() => {
    if (!countdownActive || drawTimeMs == null) return
    const update = () => setT(decompose(drawTimeMs - Date.now()))
    update()                                // immediate so no 1-s flicker
    const id = setInterval(update, 1000)
    return () => clearInterval(id)
  }, [countdownActive, drawTimeMs])

  // ── Not active ────────────────────────────────────────────────────────────
  if (!countdownActive || drawTimeMs == null) {
    return (
      <div className="text-center space-y-1.5">
        <p className="text-neon-cyan/60 text-xs font-mono tracking-[0.2em] uppercase">
          Next Draw
        </p>
        <p className="text-white/70 text-lg font-bold">
          Sunday &middot; 7:00 PM IST
        </p>
        <p className="text-white/25 text-[10px] font-mono tracking-wide">
          Countdown starts 2 h before draw
        </p>
      </div>
    )
  }

  // ── Active: live animated countdown ──────────────────────────────────────
  const units = [
    { label: 'DAYS', val: t.d },
    { label: 'HRS',  val: t.h },
    { label: 'MINS', val: t.m },
    { label: 'SECS', val: t.s },
  ]

  return (
    <div className="flex items-end justify-center gap-1">
      {units.map(({ label, val }, i) => (
        <div key={label} className="flex items-end gap-1">
          <div className="flex flex-col items-center">
            <div
              className="font-mono font-black text-5xl leading-none tracking-tight text-neon-cyan"
              style={{ minWidth: '2.8rem', textAlign: 'center' }}
            >
              <Digit value={val} />
            </div>
            <span className="mt-1.5 text-[9px] font-mono font-bold tracking-[0.2em] text-white/30">
              {label}
            </span>
          </div>
          {i < units.length - 1 && (
            <motion.span
              className="font-mono font-black text-3xl text-neon-cyan/50 mb-6 leading-none"
              animate={{ opacity: [1, 0.2, 1] }}
              transition={{ duration: 1, repeat: Infinity }}
            >
              :
            </motion.span>
          )}
        </div>
      ))}
    </div>
  )
}
