import { useState, useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Clipboard, CheckCircle2, XCircle, Zap, Lock,
  History, TrendingUp, TrendingDown, ArrowDownCircle, ArrowUpCircle,
  RefreshCw, IndianRupee,
} from 'lucide-react'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import NeonButton from '../components/NeonButton'
import BottomNav from '../components/BottomNav'
import { useUser } from '../context/UserContext'
import { redeemDeposit, getWalletHistory } from '../api/client'

// ─── Format INR ───────────────────────────────────────────────────────────────
const INR = (v) =>
  `₹${Number(v).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`

// ─── Format date to IST ───────────────────────────────────────────────────────
function formatDate(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day:    '2-digit',
    month:  'short',
    year:   'numeric',
    hour:   '2-digit',
    minute: '2-digit',
    hour12: false,
  }).replace(',', '') + ' IST'
}

// ─── Tab pill ─────────────────────────────────────────────────────────────────
function TabPill({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className="flex-1 py-2.5 rounded-xl text-xs font-black font-mono tracking-widest uppercase transition-all"
      style={{
        background: active ? 'rgba(0,240,255,0.12)' : 'transparent',
        border:     active ? '1px solid rgba(0,240,255,0.35)' : '1px solid rgba(255,255,255,0.06)',
        color:      active ? '#00f0ff' : 'rgba(255,255,255,0.30)',
        boxShadow:  active ? '0 0 12px rgba(0,240,255,0.12)' : 'none',
      }}
    >
      {children}
    </button>
  )
}

// ─── Transaction row ──────────────────────────────────────────────────────────
function TxRow({ tx }) {
  const isDeposit = tx.type === 'Deposit'
  const accent    = isDeposit ? '#ff5555' : '#00ff88'
  const Icon      = isDeposit ? ArrowDownCircle : ArrowUpCircle
  const sign      = isDeposit ? '−' : '+'

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-3 py-3"
      style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}
    >
      {/* Icon */}
      <div
        className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
        style={{
          background: isDeposit ? 'rgba(255,80,80,0.08)' : 'rgba(0,255,136,0.08)',
          border: `1px solid ${isDeposit ? 'rgba(255,80,80,0.20)' : 'rgba(0,255,136,0.20)'}`,
        }}
      >
        <Icon className="w-4 h-4" style={{ color: accent }} />
      </div>

      {/* Details */}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-mono font-bold text-white/80 truncate">{tx.code}</p>
        <p className="text-[10px] font-mono text-white/30 truncate mt-0.5">
          {tx.pool_name ? `${tx.pool_name} · ` : ''}{formatDate(tx.date)}
        </p>
      </div>

      {/* Amount */}
      <div className="text-right flex-shrink-0">
        <p className="text-sm font-black font-mono tabular-nums" style={{ color: accent }}>
          {sign}{INR(tx.amount_inr)}
        </p>
        <p
          className="text-[9px] font-mono uppercase tracking-wider mt-0.5"
          style={{ color: 'rgba(255,255,255,0.25)' }}
        >
          {tx.status}
        </p>
      </div>
    </motion.div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
export default function TokenWallet() {
  const { user, refresh, login } = useUser()
  const [activeTab, setActiveTab] = useState('deposit')

  // ── Deposit tab state ──────────────────────────────────────────────────────
  const [code,    setCode]    = useState('')
  const [loading, setLoading] = useState(false)
  const [result,  setResult]  = useState(null)   // { ok: bool, msg: string }
  const inputRef = useRef(null)

  // ── History tab state ──────────────────────────────────────────────────────
  const [histData,    setHistData]    = useState(null)
  const [histLoading, setHistLoading] = useState(false)
  const [histError,   setHistError]   = useState(null)

  const fetchHistory = useCallback(async () => {
    setHistLoading(true)
    setHistError(null)
    try {
      const res = await getWalletHistory()
      setHistData(res.data)
    } catch (err) {
      setHistError(err.response?.data?.detail ?? 'Could not load wallet history.')
    } finally {
      setHistLoading(false)
    }
  }, [])

  // Fetch history when tab is first opened
  useEffect(() => {
    if (activeTab === 'history' && !histData && !histLoading) {
      fetchHistory()
    }
  }, [activeTab, histData, histLoading, fetchHistory])

  // ── Clipboard paste ────────────────────────────────────────────────────────
  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      setCode(text.trim().toUpperCase())
      inputRef.current?.focus()
    } catch { /* permission denied — user can type manually */ }
  }

  // ── Deposit redemption ─────────────────────────────────────────────────────
  const handleRedeem = async e => {
    e.preventDefault()
    const trimmed = code.trim().toUpperCase()
    if (!trimmed) { setResult({ ok: false, msg: 'Paste or type a token code first.' }); return }
    setLoading(true)
    setResult(null)
    try {
      // Uses /auth/deposit/redeem — a user-JWT-gated endpoint.
      // This NEVER triggers the 401-logout interceptor because the user's own
      // JWT is what the endpoint requires.
      const res = await redeemDeposit(trimmed)
      // Backend returns UserJWTResponse: update both user object and JWT
      login(res.data.user, res.data.access_token)
      setResult({ ok: true, msg: `Token ${trimmed} activated! Weekly payment marked as PAID. ✓` })
      setCode('')
      // Invalidate cached history so it refreshes next time the tab opens
      setHistData(null)
    } catch (err) {
      setResult({
        ok:  false,
        msg: err.response?.data?.detail ?? 'Redemption failed. Check the code and try again.',
      })
    } finally {
      setLoading(false)
    }
  }

  const isPaid = user?.weekly_payment_status === 'Paid'

  return (
    <div className="min-h-dvh pb-28 relative">
      <Background />

      {/* Header */}
      <div
        className="sticky top-0 z-30 px-5 pt-12 pb-4"
        style={{ background: 'rgba(3,3,24,0.7)', backdropFilter: 'blur(20px)' }}
      >
        <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase">Reward Scheme</p>
        <h1 className="text-2xl font-black text-white">TOKEN WALLET</h1>
      </div>

      <div className="px-5 space-y-4">

        {/* ── Tabs ──────────────────────────────────────────────────── */}
        <div className="flex gap-2">
          <TabPill active={activeTab === 'deposit'} onClick={() => setActiveTab('deposit')}>
            <Zap className="w-3 h-3 inline-block mr-1.5 -mt-px" />
            Deposit
          </TabPill>
          <TabPill active={activeTab === 'history'} onClick={() => setActiveTab('history')}>
            <History className="w-3 h-3 inline-block mr-1.5 -mt-px" />
            History
          </TabPill>
        </div>

        {/* ══════════════════════════════════════════════════════════
            DEPOSIT TAB
            ══════════════════════════════════════════════════════════ */}
        <AnimatePresence mode="wait">
          {activeTab === 'deposit' && (
            <motion.div
              key="deposit"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
              className="space-y-4"
            >
              {/* Payment status banner */}
              <GlassCard animate className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-0.5">
                      Weekly Payment
                    </p>
                    <p
                      className="font-mono font-bold text-base"
                      style={
                        isPaid
                          ? { color: '#00ff88', textShadow: '0 0 8px #00ff88' }
                          : { color: '#ff5555' }
                      }
                    >
                      {isPaid ? '✓ PAID' : '✗ UNPAID THIS WEEK'}
                    </p>
                  </div>
                  <div
                    className="p-3 rounded-xl border"
                    style={
                      isPaid
                        ? { background: 'rgba(0,255,136,0.08)', borderColor: 'rgba(0,255,136,0.25)' }
                        : { background: 'rgba(255,80,80,0.08)', borderColor: 'rgba(255,80,80,0.25)' }
                    }
                  >
                    {isPaid
                      ? <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                      : <Lock        className="w-6 h-6 text-red-400" />
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
                  <p className="text-[10px] font-mono tracking-[0.2em] text-white/30 uppercase mb-1">
                    Deposit Token
                  </p>
                  <p className="text-xs text-white/40">
                    Paste the DEP-XXXXXX code given by your pool admin
                  </p>
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
                      {loading
                        ? 'ACTIVATING…'
                        : <><Zap className="w-4 h-4" /> REDEEM ₹1,000 TOKEN</>
                      }
                    </span>
                  </NeonButton>
                </form>

                {/* Result */}
                <AnimatePresence>
                  {result && (
                    <motion.div
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      className="flex items-start gap-3 rounded-xl p-4 border text-sm font-mono"
                      style={
                        result.ok
                          ? { background: 'rgba(0,255,136,0.06)', borderColor: 'rgba(0,255,136,0.25)', color: '#00ff88' }
                          : { background: 'rgba(255,80,80,0.06)', borderColor: 'rgba(255,80,80,0.25)', color: '#ff6666' }
                      }
                    >
                      {result.ok
                        ? <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
                        : <XCircle      className="w-5 h-5 flex-shrink-0 mt-0.5" />
                      }
                      <p className="leading-relaxed">{result.msg}</p>
                    </motion.div>
                  )}
                </AnimatePresence>
              </GlassCard>

              {/* How It Works */}
              <GlassCard animate className="p-5">
                <p className="text-[10px] font-mono tracking-widest text-white/30 uppercase mb-3">
                  How It Works
                </p>
                <div className="space-y-3">
                  {[
                    { n: '01', t: 'Receive a Deposit Token from your pool admin each week.' },
                    { n: '02', t: 'Paste the DEP-XXXXXX code above and tap Redeem.' },
                    { n: '03', t: 'Your ₹1,000 weekly instalment is marked as PAID.' },
                    { n: '04', t: 'Paid members are eligible for the Sunday 7 PM draw.' },
                  ].map(({ n, t }) => (
                    <div key={n} className="flex gap-3">
                      <span className="text-[11px] font-mono font-black text-neon-cyan/50 mt-0.5 flex-shrink-0">
                        {n}
                      </span>
                      <p className="text-xs text-white/40 leading-relaxed">{t}</p>
                    </div>
                  ))}
                </div>
              </GlassCard>
            </motion.div>
          )}

          {/* ══════════════════════════════════════════════════════════
              HISTORY TAB
              ══════════════════════════════════════════════════════════ */}
          {activeTab === 'history' && (
            <motion.div
              key="history"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
              className="space-y-4"
            >
              {/* Lifetime totals */}
              {histData && (
                <div className="grid grid-cols-2 gap-3">
                  {/* Total deposited */}
                  <GlassCard animate className="p-4 text-center">
                    <div
                      className="w-8 h-8 rounded-xl flex items-center justify-center mx-auto mb-2"
                      style={{ background: 'rgba(255,80,80,0.10)', border: '1px solid rgba(255,80,80,0.25)' }}
                    >
                      <TrendingDown className="w-4 h-4 text-red-400" />
                    </div>
                    <p
                      className="text-xl font-black tabular-nums"
                      style={{ color: '#ff6666' }}
                    >
                      {INR(histData.total_deposited_all_time)}
                    </p>
                    <p className="text-[9px] font-mono uppercase tracking-widest text-white/30 mt-1">
                      Total Deposited
                    </p>
                  </GlassCard>

                  {/* Total won */}
                  <GlassCard animate className="p-4 text-center">
                    <div
                      className="w-8 h-8 rounded-xl flex items-center justify-center mx-auto mb-2"
                      style={{ background: 'rgba(0,255,136,0.10)', border: '1px solid rgba(0,255,136,0.25)' }}
                    >
                      <TrendingUp className="w-4 h-4 text-emerald-400" />
                    </div>
                    <p
                      className="text-xl font-black tabular-nums"
                      style={{ color: '#00ff88', textShadow: histData.total_won_all_time > 0 ? '0 0 10px rgba(0,255,136,0.4)' : 'none' }}
                    >
                      {INR(histData.total_won_all_time)}
                    </p>
                    <p className="text-[9px] font-mono uppercase tracking-widest text-white/30 mt-1">
                      Total Won
                    </p>
                  </GlassCard>

                  {/* Net position */}
                  {histData.total_deposited_all_time > 0 && (
                    <div className="col-span-2">
                      <GlassCard animate className="p-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <IndianRupee className="w-3.5 h-3.5 text-white/30" />
                            <span className="text-[10px] font-mono text-white/40 uppercase tracking-widest">
                              Net Position
                            </span>
                          </div>
                          {(() => {
                            const net = histData.total_won_all_time - histData.total_deposited_all_time
                            const positive = net >= 0
                            return (
                              <span
                                className="text-sm font-black font-mono tabular-nums"
                                style={{ color: positive ? '#00ff88' : '#ff6666' }}
                              >
                                {positive ? '+' : ''}{INR(net)}
                              </span>
                            )
                          })()}
                        </div>
                      </GlassCard>
                    </div>
                  )}
                </div>
              )}

              {/* Transaction list */}
              <GlassCard animate className="p-5">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-[10px] font-mono tracking-[0.2em] text-white/30 uppercase">
                    Transaction Ledger
                  </p>
                  <motion.button
                    whileTap={{ scale: 0.9 }}
                    onClick={fetchHistory}
                    disabled={histLoading}
                    className="p-1.5 rounded-lg"
                    style={{ background: 'rgba(255,255,255,0.05)' }}
                  >
                    <RefreshCw
                      className={`w-3.5 h-3.5 text-white/40 ${histLoading ? 'animate-spin' : ''}`}
                    />
                  </motion.button>
                </div>

                {/* Loading */}
                {histLoading && (
                  <div className="flex items-center justify-center py-10">
                    <motion.div
                      className="w-5 h-5 rounded-full"
                      style={{ border: '2px solid rgba(0,240,255,0.15)', borderTopColor: '#00f0ff' }}
                      animate={{ rotate: 360 }}
                      transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
                    />
                  </div>
                )}

                {/* Error */}
                {histError && !histLoading && (
                  <div
                    className="rounded-xl p-4 text-xs font-mono text-center"
                    style={{ background: 'rgba(255,80,80,0.06)', color: '#ff6666', border: '1px solid rgba(255,80,80,0.15)' }}
                  >
                    ⚠ {histError}
                  </div>
                )}

                {/* Empty state */}
                {histData && histData.transactions.length === 0 && !histLoading && (
                  <div className="text-center py-10">
                    <History className="w-8 h-8 mx-auto mb-3 text-white/10" />
                    <p className="text-xs font-mono text-white/25">No transactions yet.</p>
                    <p className="text-[10px] font-mono text-white/15 mt-1">
                      Redeem your first deposit token to get started.
                    </p>
                  </div>
                )}

                {/* Transactions */}
                {histData && histData.transactions.length > 0 && (
                  <div>
                    {histData.transactions.map((tx) => (
                      <TxRow key={tx.id} tx={tx} />
                    ))}
                  </div>
                )}
              </GlassCard>
            </motion.div>
          )}
        </AnimatePresence>

      </div>

      <BottomNav />
    </div>
  )
}
