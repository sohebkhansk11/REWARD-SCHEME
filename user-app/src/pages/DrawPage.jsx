import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Dices, Radio } from 'lucide-react'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import NeonButton from '../components/NeonButton'
import BottomNav from '../components/BottomNav'
import DrawAnimation from '../components/DrawAnimation'

export default function DrawPage() {
  const [running, setRunning] = useState(false)

  return (
    <div className="min-h-dvh pb-28 relative">
      <Background />

      {/* Header */}
      <div className="sticky top-0 z-30 px-5 pt-12 pb-4"
        style={{ background: 'rgba(3,3,24,0.7)', backdropFilter: 'blur(20px)' }}>
        <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase">Live Event</p>
        <h1 className="text-2xl font-black text-white">THE DRAW</h1>
      </div>

      <div className="px-5 space-y-4">
        {/* Live status */}
        <GlassCard animate className="p-4 flex items-center gap-3">
          <motion.div
            className="w-2.5 h-2.5 rounded-full bg-emerald-400 flex-shrink-0"
            animate={{ opacity: [1, 0.2, 1], scale: [1, 0.8, 1] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
          <div>
            <p className="text-xs font-mono font-bold text-white">DRAW PROTOCOL STANDBY</p>
            <p className="text-[11px] text-white/30 font-mono mt-0.5">Admin triggers the live draw every Sunday at 7 PM IST</p>
          </div>
          <Radio className="w-5 h-5 text-white/20 ml-auto flex-shrink-0" />
        </GlassCard>

        {/* How it works */}
        <GlassCard animate className="p-5">
          <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-4">Dual-Draw Algorithm</p>
          <div className="space-y-4">
            {[
              { label: 'Tier 1 Winner',  desc: 'Randomly selected from members at Level 1–3', color: '#00f0ff' },
              { label: 'Tier 2 Winner',  desc: 'Randomly selected from members at Level 4–6', color: '#bf00ff' },
              { label: 'Net Payout',     desc: '₹5,000 gross − ₹500 platform fee = ₹4,500 each', color: '#00ff88' },
              { label: 'Replacement',   desc: 'Each winner is replaced by the next Waitlist member at Level 1', color: '#ffaa00' },
            ].map(({ label, desc, color }) => (
              <div key={label} className="flex gap-3">
                <div className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
                <div>
                  <p className="text-xs font-mono font-bold text-white/70">{label}</p>
                  <p className="text-[11px] text-white/35 mt-0.5 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* Demo draw */}
        <GlassCard animate className="p-5 space-y-4">
          <div>
            <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-1">Simulation Mode</p>
            <p className="text-xs text-white/40">Preview the draw animation with sample pool data.</p>
          </div>

          <NeonButton onClick={() => setRunning(true)}>
            <span className="flex items-center justify-center gap-2 text-sm tracking-widest">
              <Dices className="w-4 h-4" /> LAUNCH DEMO DRAW
            </span>
          </NeonButton>
        </GlassCard>

        {/* Past draws placeholder */}
        <GlassCard animate className="p-5">
          <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-3">Recent Draws</p>
          <div className="py-6 text-center">
            <p className="text-sm text-white/20 font-mono">No draws recorded yet</p>
            <p className="text-xs text-white/15 mt-1">Draw history will appear here after the first live event</p>
          </div>
        </GlassCard>
      </div>

      {/* Full-screen draw overlay */}
      <AnimatePresence>
        {running && (
          <DrawAnimation onComplete={() => setRunning(false)} />
        )}
      </AnimatePresence>

      <BottomNav />
    </div>
  )
}
