import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Zap, RefreshCw, ChevronRight, Shield } from 'lucide-react'
import Background from '../components/Background'
import NeonInput from '../components/NeonInput'
import NeonButton from '../components/NeonButton'
import GlassCard from '../components/GlassCard'
import { generateUsername, typewriterReveal } from '../utils/username'
import { registerUser, findUserByMobile, findUserByUsername } from '../api/client'
import { useUser } from '../context/UserContext'

export default function Auth() {
  const nav = useNavigate()
  const { login } = useUser()

  const [mode, setMode] = useState('register')   // register | login
  const [name, setName] = useState('')
  const [mobile, setMobile] = useState('')
  const [username, setUsername] = useState('')
  const [displayUsername, setDisplayUsername] = useState('')
  const [referralUsername, setReferralUsername] = useState('')
  const [generating, setGenerating] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    const u = generateUsername()
    setUsername(u)
    await typewriterReveal(u, setDisplayUsername)
    setGenerating(false)
  }

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    if (!mobile.trim()) { setError('Mobile number is required'); return }

    setLoading(true)
    try {
      if (mode === 'login') {
        const res = await findUserByMobile(mobile.trim())
        if (!res.data.length) { setError('No account found with this mobile number'); setLoading(false); return }
        login(res.data[0])
        nav('/dashboard', { replace: true })
      } else {
        if (!name.trim()) { setError('Name is required'); setLoading(false); return }
        const payload = { name: name.trim(), mobile: mobile.trim(), username: username || undefined }
        if (referralUsername.trim()) {
          const refRes = await findUserByUsername(referralUsername.trim())
          if (!refRes.data.length) { setError('Referral username not found'); setLoading(false); return }
          payload.referred_by_user_id = refRes.data[0].id
        }
        const res = await registerUser(payload)
        login(res.data)
        nav('/dashboard', { replace: true })
      }
    } catch (err) {
      setError(err.response?.data?.detail ?? 'Something went wrong. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-5 py-10 relative overflow-hidden">
      <Background />

      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="flex flex-col items-center mb-10 gap-3"
      >
        <motion.div
          className="w-16 h-16 rounded-2xl flex items-center justify-center border"
          style={{ background: 'rgba(0,240,255,0.07)', borderColor: 'rgba(0,240,255,0.25)', boxShadow: '0 0 30px rgba(0,240,255,0.2)' }}
          animate={{ boxShadow: ['0 0 20px rgba(0,240,255,0.15)', '0 0 40px rgba(0,240,255,0.4)', '0 0 20px rgba(0,240,255,0.15)'] }}
          transition={{ duration: 3, repeat: Infinity }}
        >
          <Shield className="w-8 h-8" style={{ color: '#00f0ff' }} strokeWidth={1.5} />
        </motion.div>
        <div className="text-center">
          <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase">Reward Scheme</p>
          <h1 className="text-2xl font-black text-white tracking-tight mt-0.5">WEALTH PROTOCOL</h1>
        </div>
      </motion.div>

      {/* Mode tabs */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="flex rounded-2xl p-1 mb-6 w-full max-w-xs"
        style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        {['register', 'login'].map(m => (
          <button
            key={m}
            onClick={() => { setMode(m); setError('') }}
            className="flex-1 py-2.5 rounded-xl text-sm font-bold tracking-widest font-mono uppercase transition-all duration-200"
            style={mode === m ? {
              background: 'rgba(0,240,255,0.12)',
              color: '#00f0ff',
              boxShadow: '0 0 14px rgba(0,240,255,0.2)',
            } : { color: 'rgba(255,255,255,0.3)' }}
          >
            {m === 'register' ? 'New Vault' : 'Return'}
          </button>
        ))}
      </motion.div>

      {/* Form */}
      <GlassCard className="w-full max-w-xs p-6 space-y-4" animate>
        <form onSubmit={handleSubmit} className="space-y-4">
          <AnimatePresence>
            {mode === 'register' && (
              <motion.div
                key="name"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.25 }}
              >
                <NeonInput
                  label="Full Name"
                  placeholder="Enter your name"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  autoComplete="name"
                />
              </motion.div>
            )}
          </AnimatePresence>

          <NeonInput
            label="Mobile Number"
            placeholder="+91 XXXXX XXXXX"
            value={mobile}
            onChange={e => setMobile(e.target.value)}
            inputMode="tel"
            autoComplete="tel"
          />

          <AnimatePresence>
            {mode === 'register' && (
              <motion.div
                key="username"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.25 }}
                className="space-y-2"
              >
                <label className="block text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
                  Username
                </label>
                <div className="relative">
                  <div
                    className="neon-input font-mono tracking-widest text-neon-cyan min-h-[50px] flex items-center pr-12"
                    style={{ cursor: 'text', minHeight: 50 }}
                  >
                    {displayUsername || (
                      <span className="text-white/20 font-sans tracking-normal text-sm">Auto-generate or type below…</span>
                    )}
                  </div>
                </div>
                <input
                  className="neon-input font-mono text-sm"
                  placeholder="Or type custom username…"
                  value={username}
                  onChange={e => { setUsername(e.target.value); setDisplayUsername(e.target.value) }}
                  autoComplete="username"
                />
                <motion.button
                  type="button"
                  onClick={handleGenerate}
                  disabled={generating}
                  whileTap={{ scale: 0.96 }}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-bold font-mono tracking-wider border transition-all"
                  style={{
                    background: 'rgba(191,0,255,0.07)',
                    borderColor: 'rgba(191,0,255,0.3)',
                    color: generating ? 'rgba(191,0,255,0.5)' : '#d580ff',
                    boxShadow: generating ? 'none' : '0 0 12px rgba(191,0,255,0.15)',
                  }}
                >
                  {generating
                    ? <><RefreshCw className="w-4 h-4 animate-spin" /> ENCRYPTING…</>
                    : <><Zap className="w-4 h-4" /> AUTO-GENERATE USERNAME</>
                  }
                </motion.button>

                <NeonInput
                  label="Referral Username (optional)"
                  placeholder="Who referred you?"
                  value={referralUsername}
                  onChange={e => setReferralUsername(e.target.value)}
                  autoComplete="off"
                />
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {error && (
              <motion.p
                initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="text-xs text-red-400 font-mono text-center py-1"
              >
                ⚠ {error}
              </motion.p>
            )}
          </AnimatePresence>

          <NeonButton type="submit" disabled={loading} className="mt-2">
            <span className="flex items-center justify-center gap-2 text-sm tracking-widest">
              {loading ? 'CONNECTING…' : mode === 'register' ? 'ACTIVATE VAULT' : 'ENTER VAULT'}
              {!loading && <ChevronRight className="w-4 h-4" />}
            </span>
          </NeonButton>
        </form>
      </GlassCard>

      <p className="mt-8 text-[10px] font-mono text-white/15 text-center tracking-widest">
        SECURED BY 256-BIT ENCRYPTION
      </p>
    </div>
  )
}
