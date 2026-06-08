import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Zap, RefreshCw, ChevronRight, Shield, Eye, EyeOff, Ticket } from 'lucide-react'
import Background from '../components/Background'
import NeonInput from '../components/NeonInput'
import NeonButton from '../components/NeonButton'
import GlassCard from '../components/GlassCard'
import { generateUsername, typewriterReveal } from '../utils/username'
import { authRegister, authLogin } from '../api/client'
import { useUser } from '../context/UserContext'

// ── Password input with show/hide toggle ──────────────────────────────────────
function PasswordField({ label, value, onChange, placeholder, autoComplete }) {
  const [show, setShow] = useState(false)
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
        {label}
      </label>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          autoComplete={autoComplete}
          className="neon-input w-full pr-11"
        />
        <button
          type="button"
          onClick={() => setShow(v => !v)}
          className="absolute right-3.5 top-1/2 -translate-y-1/2 text-white/25 hover:text-white/60 transition-colors"
          tabIndex={-1}
        >
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
    </div>
  )
}

export default function Auth() {
  const nav  = useNavigate()
  const { login } = useUser()

  const [mode, setMode] = useState('register')  // 'register' | 'login'

  // ── Register fields ────────────────────────────────────────────────────────
  const [name,          setName]          = useState('')
  const [mobile,        setMobile]        = useState('')
  const [username,      setUsername]      = useState('')
  const [displayUser,   setDisplayUser]   = useState('')
  const [generating,    setGenerating]    = useState(false)
  const [password,      setPassword]      = useState('')
  const [confirmPass,   setConfirmPass]   = useState('')
  const [depositToken,  setDepositToken]  = useState('')
  const [referralUser,  setReferralUser]  = useState('')

  // ── Login fields ───────────────────────────────────────────────────────────
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')

  // ── Shared ─────────────────────────────────────────────────────────────────
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  // ── Username generator ─────────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (generating) return
    setGenerating(true)
    const u = generateUsername()
    setUsername(u)
    await typewriterReveal(u, setDisplayUser)
    setGenerating(false)
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  const handleSubmit = async e => {
    e.preventDefault()
    setError('')

    if (mode === 'login') {
      if (!loginUsername.trim() || !loginPassword) {
        setError('Username and password are required.')
        return
      }
      setLoading(true)
      try {
        const res = await authLogin(loginUsername.trim(), loginPassword)
        login(res.data.user, res.data.access_token)
        nav('/dashboard', { replace: true })
      } catch (err) {
        setError(err.response?.data?.detail ?? 'Login failed. Check your credentials.')
      } finally {
        setLoading(false)
      }
      return
    }

    // ── Registration validation ─────────────────────────────────────────────
    if (!name.trim())         { setError('Full name is required.');            return }
    if (!mobile.trim())       { setError('Mobile number is required.');        return }
    if (!username.trim())     { setError('Choose or generate a username.');    return }
    if (password.length < 6)  { setError('Password must be at least 6 characters.'); return }
    if (password !== confirmPass) { setError('Passwords do not match.');       return }
    if (!depositToken.trim()) { setError('A Deposit Token code is required to join.'); return }

    setLoading(true)
    try {
      const payload = {
        name:          name.trim(),
        mobile:        mobile.trim(),
        username:      username.trim(),
        password,
        deposit_token: depositToken.trim().toUpperCase(),
        referred_by_username: referralUser.trim() || undefined,
      }
      const res = await authRegister(payload)
      login(res.data.user, res.data.access_token)
      nav('/dashboard', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail ?? 'Registration failed. Try again.')
    } finally {
      setLoading(false)
    }
  }

  const switchMode = m => { setMode(m); setError('') }

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-5 py-10 relative overflow-hidden">
      <Background />

      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55 }}
        className="flex flex-col items-center mb-8 gap-3"
      >
        <motion.div
          className="w-16 h-16 rounded-2xl flex items-center justify-center"
          style={{
            background:  'rgba(0,240,255,0.07)',
            border:      '1px solid rgba(0,240,255,0.25)',
            boxShadow:   '0 0 30px rgba(0,240,255,0.2)',
          }}
          animate={{ boxShadow: [
            '0 0 20px rgba(0,240,255,0.15)',
            '0 0 40px rgba(0,240,255,0.45)',
            '0 0 20px rgba(0,240,255,0.15)',
          ]}}
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
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
        className="flex rounded-2xl p-1 mb-5 w-full max-w-xs"
        style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        {[
          { key: 'register', label: 'New Vault' },
          { key: 'login',    label: 'Return'    },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => switchMode(key)}
            className="flex-1 py-2.5 rounded-xl text-sm font-bold tracking-widest font-mono uppercase transition-all duration-200"
            style={mode === key ? {
              background: 'rgba(0,240,255,0.12)',
              color:      '#00f0ff',
              boxShadow:  '0 0 14px rgba(0,240,255,0.2)',
            } : { color: 'rgba(255,255,255,0.3)' }}
          >
            {label}
          </button>
        ))}
      </motion.div>

      {/* Form card */}
      <GlassCard className="w-full max-w-xs p-6" animate>
        <form onSubmit={handleSubmit} className="space-y-4">

          {/* ── LOGIN ──────────────────────────────────────────────── */}
          <AnimatePresence mode="wait">
            {mode === 'login' && (
              <motion.div
                key="login-fields"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                exit={{    opacity: 0, y:-8 }} transition={{ duration: 0.2 }}
                className="space-y-4"
              >
                <NeonInput
                  label="Username"
                  placeholder="your_username"
                  value={loginUsername}
                  onChange={e => setLoginUsername(e.target.value)}
                  autoComplete="username"
                  autoFocus
                />
                <PasswordField
                  label="Password"
                  value={loginPassword}
                  onChange={e => setLoginPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                />
              </motion.div>
            )}

            {/* ── REGISTER ───────────────────────────────────────────── */}
            {mode === 'register' && (
              <motion.div
                key="register-fields"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                exit={{    opacity: 0, y:-8 }} transition={{ duration: 0.2 }}
                className="space-y-4"
              >
                {/* Name */}
                <NeonInput
                  label="Full Name"
                  placeholder="Enter your name"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  autoComplete="name"
                />

                {/* Mobile */}
                <NeonInput
                  label="Mobile Number"
                  placeholder="+91 XXXXX XXXXX"
                  value={mobile}
                  onChange={e => setMobile(e.target.value)}
                  inputMode="tel"
                  autoComplete="tel"
                />

                {/* Username */}
                <div className="space-y-2">
                  <label className="block text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
                    Username
                  </label>
                  {/* Live typewriter display */}
                  <div
                    className="neon-input font-mono tracking-widest text-neon-cyan select-none"
                    style={{ minHeight: 50, display: 'flex', alignItems: 'center' }}
                  >
                    {displayUser || (
                      <span className="text-white/20 font-sans tracking-normal text-sm normal-case">
                        Auto-generate or type below…
                      </span>
                    )}
                  </div>
                  <input
                    className="neon-input font-mono text-sm"
                    placeholder="Or type a custom username…"
                    value={username}
                    onChange={e => { setUsername(e.target.value); setDisplayUser(e.target.value) }}
                    autoComplete="username"
                  />
                  <motion.button
                    type="button"
                    onClick={handleGenerate}
                    disabled={generating}
                    whileTap={{ scale: 0.96 }}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-bold font-mono tracking-wider border transition-all"
                    style={{
                      background:   'rgba(191,0,255,0.07)',
                      borderColor:  'rgba(191,0,255,0.3)',
                      color:        generating ? 'rgba(191,0,255,0.5)' : '#d580ff',
                      boxShadow:    generating ? 'none' : '0 0 12px rgba(191,0,255,0.15)',
                    }}
                  >
                    {generating
                      ? <><RefreshCw className="w-4 h-4 animate-spin" /> ENCRYPTING…</>
                      : <><Zap className="w-4 h-4" /> AUTO-GENERATE USERNAME</>
                    }
                  </motion.button>
                </div>

                {/* Password */}
                <PasswordField
                  label="Password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="Min. 6 characters"
                  autoComplete="new-password"
                />

                {/* Confirm Password */}
                <PasswordField
                  label="Confirm Password"
                  value={confirmPass}
                  onChange={e => setConfirmPass(e.target.value)}
                  placeholder="Repeat password"
                  autoComplete="new-password"
                />

                {/* Deposit Token */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
                    Deposit Token
                  </label>
                  <div className="relative">
                    <input
                      className="neon-input w-full pr-10 font-mono tracking-widest uppercase text-sm"
                      placeholder="DEP-XXXXXX"
                      value={depositToken}
                      onChange={e => setDepositToken(e.target.value.toUpperCase())}
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <Ticket
                      className="absolute right-3.5 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none"
                      style={{ color: depositToken ? '#00f0ff' : 'rgba(255,255,255,0.2)' }}
                    />
                  </div>
                  <p className="text-[10px] text-white/25 font-mono pl-1">
                    Obtain a DEP-XXXXXX code from the admin to activate your vault.
                  </p>
                </div>

                {/* Referral (optional) */}
                <NeonInput
                  label="Referral Username (optional)"
                  placeholder="Who invited you?"
                  value={referralUser}
                  onChange={e => setReferralUser(e.target.value)}
                  autoComplete="off"
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className="rounded-xl px-4 py-3 text-xs font-mono text-red-400 text-center"
                style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}
              >
                ⚠ {error}
              </motion.div>
            )}
          </AnimatePresence>

          {/* Submit */}
          <NeonButton type="submit" disabled={loading}>
            <span className="flex items-center justify-center gap-2 text-sm tracking-widest">
              {loading ? 'CONNECTING…' : mode === 'register' ? 'ACTIVATE VAULT' : 'ENTER VAULT'}
              {!loading && <ChevronRight className="w-4 h-4" />}
            </span>
          </NeonButton>
        </form>
      </GlassCard>

      <p className="mt-8 text-[10px] font-mono text-white/15 text-center tracking-widest">
        SECURED · JWT AUTHENTICATED
      </p>
    </div>
  )
}
