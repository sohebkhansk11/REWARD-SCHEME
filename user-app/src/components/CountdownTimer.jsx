import { useState, useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

const BASE_URL = import.meta.env.VITE_API_URL || 'https://reward-scheme-api.onrender.com'

/**
 * Returns the epoch-ms of the next Sunday at 19:00:00 IST (UTC+5:30)
 * relative to a given `nowMs` value so the calculation is testable.
 */
function nextSundayDraw(nowMs) {
  // IST = UTC + 5h 30m = UTC + 19800 s
  const IST_OFFSET_MS = 5.5 * 3600 * 1000
  const nowIST = nowMs + IST_OFFSET_MS                        // ms in IST epoch
  const d = new Date(nowIST)

  const day  = d.getUTCDay()   // 0=Sun … 6=Sat (in IST space)
  const hour = d.getUTCHours()
  const min  = d.getUTCMinutes()
  const sec  = d.getUTCSeconds()

  // Days until next Sunday
  let daysUntil = (7 - day) % 7
  // If it is already Sunday but before 19:00 IST, use today
  if (day === 0 && (hour < 19 || (hour === 19 && min === 0 && sec === 0))) {
    daysUntil = 0
  } else if (daysUntil === 0) {
    daysUntil = 7  // already past 19:00 on Sunday — next week
  }

  // Build target in IST epoch, then convert back to UTC epoch
  const target = new Date(nowIST)
  target.setUTCDate(d.getUTCDate() + daysUntil)
  target.setUTCHours(19, 0, 0, 0)
  return target.getTime() - IST_OFFSET_MS   // UTC epoch ms
}

function decompose(diffMs) {
  const d = Math.max(0, diffMs)
  return {
    d: Math.floor(d / 86400000),
    h: Math.floor((d % 86400000) / 3600000),
    m: Math.floor((d % 3600000) / 60000),
    s: Math.floor((d % 60000) / 1000),
  }
}

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

export default function CountdownTimer() {
  // clockOffset: server_epoch_ms - client_epoch_ms
  // Allows us to correct for client clock drift.
  const offsetRef = useRef(0)
  const [synced, setSynced] = useState(false)

  // Fetch server time once on mount and calculate offset
  useEffect(() => {
    let cancelled = false
    const fetchServerTime = async () => {
      try {
        const clientBefore = Date.now()
        const res = await fetch(`${BASE_URL}/time`)
        const clientAfter = Date.now()
        if (cancelled) return

        const { epoch_ms } = await res.json()
        // Mid-point correction to account for network latency
        const rtt = clientAfter - clientBefore
        const clientMid = clientBefore + rtt / 2
        offsetRef.current = epoch_ms - clientMid
      } catch {
        // If the fetch fails, fall back to local clock (offset stays 0)
      } finally {
        if (!cancelled) setSynced(true)
      }
    }
    fetchServerTime()
    return () => { cancelled = true }
  }, [])

  const nowCorrected = () => Date.now() + offsetRef.current

  const [t, setT] = useState(() => {
    const now = nowCorrected()
    return decompose(nextSundayDraw(now) - now)
  })

  useEffect(() => {
    const id = setInterval(() => {
      const now = nowCorrected()
      setT(decompose(nextSundayDraw(now) - now))
    }, 1000)
    return () => clearInterval(id)
  }, [synced]) // restart after sync so first tick uses corrected offset

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
