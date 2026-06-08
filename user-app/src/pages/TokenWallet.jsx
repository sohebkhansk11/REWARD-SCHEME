import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Clipboard, CheckCircle2, XCircle, Zap, Lock } from 'lucide-react'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import NeonButton from '../components/NeonButton'
import BottomNav from '../components/BottomNav'
import { useUser } from '../context/UserContext'
import { redeemToken, getUser } from '../api/client'

export default function TokenWallet() {
  const { user, refresh } = useUser()
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)   // { ok: bool, msg: string }
  const inputRef = useRef(null)

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      setCode(text.trim().toUpperCase())
      inputRef.current?.focus()
    } catch { /* permission denied — user can type manually */ }
  }

  const handleRedeem = async e => {
    e.preventDefault()
    const trimmed = code.trim().toUpperCase()
    if (!trimmed) { setResult({ ok: false, msg: 'Paste or type a token code first' }); return }
    if (!user?.id) { setResult({ ok: false, msg: 'You must be logged in' }); return }
    setLoading(true)
    setResult(null)
    try {
      await redeemToken(trimmed, user.id)
      // Refresh user status from backend
      const fresh = await getUser(user.id)
      refresh(fresh.data)
      setResult({ ok: true, msg: `Token ${trimmed} activated! Weekly payment marked as PAID.` })
      setCode('')
    } catch (err) {
      setResult({ ok: false, msg: err.response?.data?.detail ?? 'Redemption failed. Check the code and try again.' })
    } finally {
      setLoading(false)
    }
  }

  const isPaid = user?.weekly_payment_status === 'Paid'

  return (
    <div className="min-h-dvh pb-28 relative">
      <Background />

      {/* Header */}
      <div className="sticky top-0 z-30 px-5 pt-12 pb-4"
        style={{ background: 'rgba(3,3,24,0.7)', backdropFilter: 'blur(20px)' }}>
        <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase">Reward Scheme</p>
        <h1 className="text-2xl font-black text-white">TOKEN WALLET</h1>
      </div>

      <div className="px-5 space-y-4">
        {/* Payment status banner */}
        <GlassCard animate className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-0.5">Weekly Payment</p>
              <p className="font-mono font-bold text-base" style={isPaid ? { color: '#00ff88', textShadow: '0 0 8px #00ff88' } : { color: '#ff5555' }}>
                {isPaid ? '✓ PAID' : '✗ UNPAID THIS WEEK'}
              </p>
            </div>
            <div className={`p-3 rounded-xl border`}
              style={isPaid
                ? { background: 'rgba(0,255,136,0.08)', borderColor: 'rgba(0,255,136,0.25)' }
                : { background: 'rgba(255,80,80,0.08)', borderColor: 'rgba(255,80,80,0.25)' }
              }>
              {isPaid
                ? <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                : <Lock className="w-6 h-6 text-red-400" />
              }
            </div>
          </div>
          {!isPaid && (
            <p className="text-xs text-white/30 font-mono mt-2">
              Redeem a ₹1,000 Deposit Token to unlock this week's draw entry.
            </p>
          )}
        </GlassCard>

        {/* Redeem form */}
        <GlassCard animate className="p-5 space-y-5">
          <div>
            <p className="text-[10px] font-mono tracking-[0.2em] text-white/30 uppercase mb-1">Deposit Token</p>
            <p className="text-xs text-white/40">Paste the DEP-XXXXXX code given by your pool admin</p>
          </div>

          <form onSubmit={handleRedeem} className="space-y-3">
            {/* Glowing code input */}
            <div className="relative">
              <input
                ref={inputRef}
                value={code}
                onChange={e => setCode(e.target.value.toUpperCase())}
                placeholder="DEP-XXXXXX"
                className="neon-input font-mono tracking-[0.2em] text-lg text-center pr-14"
                style={{ letterSpacing: '0.2em' }}
                autoComplete="off"
                spellCheck={false}
              />
              <motion.button
                type="button"
                onClick={handlePaste}
                whileTap={{ scale: 0.88 }}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-lg transition-colors"
                style={{ background: 'rgba(0,240,255,0.1)', color: '#00f0ff' }}
                title="Paste from clipboard"
              >
                <Clipboard className="w-4 h-4" />
              </motion.button>
            </div>

            <NeonButton type="submit" disabled={loading || !code.trim()} className="py-4">
              <span className="flex items-center justify-center gap-2 text-sm tracking-widest">
                {loading ? 'ACTIVATING…' : <><Zap className="w-4 h-4" /> REDEEM ₹1,000 TOKEN</>}
              </span>
            </NeonButton>
          </form>

          {/* Result */}
          <AnimatePresence>
            {result && (
              <motion.div
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="flex items-start gap-3 rounded-xl p-4 border text-sm font-mono"
                style={result.ok
                  ? { background: 'rgba(0,255,136,0.06)', borderColor: 'rgba(0,255,136,0.25)', color: '#00ff88' }
                  : { background: 'rgba(255,80,80,0.06)', borderColor: 'rgba(255,80,80,0.25)', color: '#ff6666' }
                }
              >
                {result.ok
                  ? <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
                  : <XCircle    className="w-5 h-5 flex-shrink-0 mt-0.5" />
                }
                <p className="leading-relaxed">{result.msg}</p>
              </motion.div>
            )}
          </AnimatePresence>
        </GlassCard>

        {/* Info */}
        <GlassCard animate className="p-5">
          <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-3">How It Works</p>
          <div className="space-y-3">
            {[
              { n: '01', t: 'Receive a Deposit Token from your pool admin each week.' },
              { n: '02', t: 'Paste the DEP-XXXXXX code above and tap Redeem.' },
              { n: '03', t: 'Your ₹1,000 weekly instalment is marked as PAID.' },
              { n: '04', t: 'Paid members are eligible for the Sunday 7 PM draw.' },
            ].map(({ n, t }) => (
              <div key={n} className="flex gap-3">
                <span className="text-[11px] font-mono font-black text-neon-cyan/50 mt-0.5 flex-shrink-0">{n}</span>
                <p className="text-xs text-white/40 leading-relaxed">{t}</p>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>

      <BottomNav />
    </div>
  )
}
