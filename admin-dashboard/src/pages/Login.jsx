import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Shield, Eye, EyeOff, MessageCircle, ArrowRight, RotateCcw } from 'lucide-react'
import { adminLogin, adminVerifyOTP } from '../api/client'
import { useAuth } from '../context/AuthContext'

// ── OTP countdown hook ─────────────────────────────────────────────────────────
function useCountdown(seconds) {
  const [remaining, setRemaining] = useState(seconds)
  useEffect(() => {
    setRemaining(seconds)
    const id = setInterval(() => setRemaining(r => Math.max(0, r - 1)), 1000)
    return () => clearInterval(id)
  }, [seconds])
  return remaining
}

// ── Step indicator ─────────────────────────────────────────────────────────────
function Steps({ current }) {
  return (
    <div className="flex items-center gap-3 mb-8">
      {[1, 2].map(n => (
        <div key={n} className="flex items-center gap-3">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-all ${
            n < current  ? 'bg-emerald-600 border-emerald-600 text-white' :
            n === current ? 'bg-blue-600 border-blue-600 text-white shadow-lg shadow-blue-900/40' :
                            'border-slate-700 text-slate-600'
          }`}>
            {n < current ? '✓' : n}
          </div>
          <span className={`text-xs font-medium ${n === current ? 'text-slate-300' : 'text-slate-600'}`}>
            {n === 1 ? 'Credentials' : 'Telegram OTP'}
          </span>
          {n < 2 && <div className={`w-8 h-px ${current > 1 ? 'bg-emerald-600' : 'bg-slate-700'}`} />}
        </div>
      ))}
    </div>
  )
}

export default function Login() {
  const { login, isAuthed } = useAuth()
  const nav = useNavigate()

  // Step 1 fields
  const [username,    setUsername]    = useState('')
  const [password,    setPassword]    = useState('')
  const [showPass,    setShowPass]    = useState(false)

  // Step 2 fields
  const [otp,         setOtp]         = useState('')
  const [tempToken,   setTempToken]   = useState('')

  const [step,        setStep]        = useState(1)
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState('')

  const otpRef = useRef(null)
  const countdown = useCountdown(step === 2 ? 300 : 0)   // 5-minute OTP timer

  // Redirect if already logged in
  useEffect(() => { if (isAuthed) nav('/', { replace: true }) }, [isAuthed, nav])

  // Focus OTP input when we reach step 2
  useEffect(() => { if (step === 2) setTimeout(() => otpRef.current?.focus(), 100) }, [step])

  // ── Step 1: verify password ────────────────────────────────────────────────
  const handleLogin = async e => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('Username and password are required.')
      return
    }
    setLoading(true)
    try {
      const res = await adminLogin(username.trim(), password)
      setTempToken(res.data.temp_token)
      setStep(2)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'Login failed. Check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  // ── Step 2: verify OTP ────────────────────────────────────────────────────
  const handleVerifyOTP = async e => {
    e.preventDefault()
    setError('')
    if (otp.length !== 6 || !/^\d{6}$/.test(otp)) {
      setError('Enter the 6-digit code from Telegram.')
      return
    }
    setLoading(true)
    try {
      const res = await adminVerifyOTP(tempToken, otp)
      login(res.data.access_token, res.data.admin_username)
      nav('/', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail ?? 'OTP verification failed.')
    } finally {
      setLoading(false)
    }
  }

  const mm = String(Math.floor(countdown / 60)).padStart(2, '0')
  const ss = String(countdown % 60).padStart(2, '0')

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      {/* Background noise */}
      <div className="fixed inset-0 pointer-events-none"
        style={{ backgroundImage: 'radial-gradient(ellipse 70% 50% at 50% 0%, rgba(59,130,246,0.07), transparent)' }} />

      <div className="w-full max-w-sm relative">

        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 bg-blue-600 rounded-2xl flex items-center justify-center shadow-2xl shadow-blue-900/50 mb-4">
            <Shield className="w-7 h-7 text-white" strokeWidth={1.5} />
          </div>
          <h1 className="text-xl font-bold text-white">RewardScheme Admin</h1>
          <p className="text-sm text-slate-500 mt-1">Secure Console Access</p>
        </div>

        {/* Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">

          <Steps current={step} />

          {/* ── Step 1 ─────────────────────────────────────────────────── */}
          {step === 1 && (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                  Username
                </label>
                <input
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-white text-sm placeholder-slate-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                  placeholder="admin"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  autoComplete="username"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPass ? 'text' : 'password'}
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 pr-11 text-white text-sm placeholder-slate-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                    placeholder="••••••••"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPass(v => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition"
                  >
                    {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <div className="bg-red-950/50 border border-red-800/60 rounded-xl px-4 py-3 text-sm text-red-400">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 disabled:cursor-not-allowed text-white font-semibold rounded-xl py-3 text-sm transition shadow-lg shadow-blue-900/30"
              >
                {loading ? (
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <><ArrowRight className="w-4 h-4" /> Continue</>
                )}
              </button>
            </form>
          )}

          {/* ── Step 2 ─────────────────────────────────────────────────── */}
          {step === 2 && (
            <form onSubmit={handleVerifyOTP} className="space-y-4">
              {/* Telegram notice */}
              <div className="flex items-start gap-3 bg-blue-950/50 border border-blue-800/40 rounded-xl p-4">
                <MessageCircle className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm text-blue-300 font-medium">Check Telegram</p>
                  <p className="text-xs text-blue-400/70 mt-0.5">
                    A 6-digit OTP has been sent to your registered Telegram account.
                  </p>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    One-Time Password
                  </label>
                  <span className={`text-xs font-mono tabular-nums ${countdown < 60 ? 'text-red-400' : 'text-slate-500'}`}>
                    {mm}:{ss}
                  </span>
                </div>
                <input
                  ref={otpRef}
                  type="text"
                  inputMode="numeric"
                  pattern="\d{6}"
                  maxLength={6}
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-white text-2xl font-mono tracking-[0.5em] text-center placeholder-slate-700 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                  placeholder="000000"
                  value={otp}
                  onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                />
              </div>

              {error && (
                <div className="bg-red-950/50 border border-red-800/60 rounded-xl px-4 py-3 text-sm text-red-400">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading || otp.length !== 6}
                className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 disabled:cursor-not-allowed text-white font-semibold rounded-xl py-3 text-sm transition shadow-lg shadow-emerald-900/30"
              >
                {loading ? (
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <><Shield className="w-4 h-4" /> Verify &amp; Enter Console</>
                )}
              </button>

              <button
                type="button"
                onClick={() => { setStep(1); setOtp(''); setError(''); setTempToken('') }}
                className="w-full flex items-center justify-center gap-2 text-sm text-slate-500 hover:text-slate-300 transition py-1"
              >
                <RotateCcw className="w-3.5 h-3.5" /> Start over
              </button>
            </form>
          )}
        </div>

        <p className="text-center text-xs text-slate-700 mt-6">
          Reward Scheme Admin Console · 2FA Protected
        </p>
      </div>
    </div>
  )
}
