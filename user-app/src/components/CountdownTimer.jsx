import { useState, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

function getTarget() {
  const now = new Date()
  const t = new Date(now)
  const day = now.getDay()
  if (day === 0 && now.getHours() < 19) {
    t.setHours(19, 0, 0, 0)
  } else {
    t.setDate(now.getDate() + ((7 - day) % 7 || 7))
    t.setHours(19, 0, 0, 0)
  }
  return t
}

function calcRemaining() {
  const diff = Math.max(0, getTarget() - Date.now())
  return {
    d: Math.floor(diff / 86400000),
    h: Math.floor((diff % 86400000) / 3600000),
    m: Math.floor((diff % 3600000) / 60000),
    s: Math.floor((diff % 60000) / 1000),
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
  const [t, setT] = useState(calcRemaining)
  useEffect(() => {
    const id = setInterval(() => setT(calcRemaining()), 1000)
    return () => clearInterval(id)
  }, [])

  const units = [
    { label: 'DAYS',  val: t.d },
    { label: 'HRS',   val: t.h },
    { label: 'MINS',  val: t.m },
    { label: 'SECS',  val: t.s },
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
