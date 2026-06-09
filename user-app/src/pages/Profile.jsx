import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  User, Phone, Lock, Eye, EyeOff, CheckCircle2,
  Clock, MapPin, Ticket, RefreshCw, AlertCircle, Gift,
} from 'lucide-react'
import Background from '../components/Background'
import GlassCard from '../components/GlassCard'
import NeonButton from '../components/NeonButton'
import BottomNav from '../components/BottomNav'
import { useUser } from '../context/UserContext'
import {
  getUsers, getUser, updateProfile, changePassword, rejoinWaitlist,
  requestReferralPayout,
} from '../api/client'

// ─── IST date formatter ───────────────────────────────────────────────────────
function formatIST(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleString('en-IN', {
    timeZone:  'Asia/Kolkata',
    day:       '2-digit',
    month:     'short',
    year:      'numeric',
    hour:      '2-digit',
    minute:    '2-digit',
    second:    '2-digit',
    hour12:    false,
  }).replace(',', '') + ' IST'
}

// ─── Section heading ──────────────────────────────────────────────────────────
function SectionLabel({ children }) {
  return (
    <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase mb-3">
      {children}
    </p>
  )
}

// ─── Feedback banner ──────────────────────────────────────────────────────────
function Feedback({ ok, msg }) {
  if (!msg) return null
  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
      className="rounded-xl px-4 py-3 text-xs font-mono"
      style={{
        background: ok ? 'rgba(0,255,136,0.07)' : 'rgba(239,68,68,0.08)',
        border:     ok ? '1px solid rgba(0,255,136,0.20)' : '1px solid rgba(239,68,68,0.20)',
        color:      ok ? '#00ff88' : '#f87171',
      }}
    >
      {ok ? '✓ ' : '⚠ '}{msg}
    </motion.div>
  )
}

// ─── Password field with show/hide ────────────────────────────────────────────
function PwField({ label, value, onChange, autoComplete }) {
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
          autoComplete={autoComplete}
          className="neon-input w-full pr-11"
          placeholder="••••••••"
        />
        <button
          type="button"
          onClick={() => setShow(v => !v)}
          className="absolute right-3.5 top-1/2 -translate-y-1/2 text-white/25 hover:text-white/55 transition-colors"
          tabIndex={-1}
        >
          {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
export default function Profile() {
  const { user, login, token, refresh } = useUser()

  // ── Waitlist position ──────────────────────────────────────────────────────
  const [waitlistPos,  setWaitlistPos]  = useState(null)
  const [loadingPos,   setLoadingPos]   = useState(false)

  const fetchWaitlistPosition = useCallback(async () => {
    if (user?.status !== 'Waitlist') return
    setLoadingPos(true)
    try {
      const res = await getUsers({ limit: 300 })
      const sorted = (res.data || [])
        .filter(u => u.status === 'Waitlist')
        .sort((a, b) => new Date(a.join_date) - new Date(b.join_date))
      const pos = sorted.findIndex(u => u.id === user.id) + 1
      setWaitlistPos(pos > 0 ? pos : null)
    } catch { setWaitlistPos(null) }
    finally { setLoadingPos(false) }
  }, [user?.id, user?.status])

  useEffect(() => { fetchWaitlistPosition() }, [fetchWaitlistPosition])

  // ── Personal details ───────────────────────────────────────────────────────
  const [dName,      setDName]      = useState(user?.name   ?? '')
  const [dMobile,    setDMobile]    = useState(user?.mobile ?? '')
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [detailsFb,  setDetailsFb]  = useState({ ok: false, msg: '' })

  // Track the values as they were when the form last saved (or on mount).
  // The Save button is disabled whenever the current values match these — no
  // point submitting a no-op update.
  const [initName,   setInitName]   = useState(user?.name   ?? '')
  const [initMobile, setInitMobile] = useState(user?.mobile ?? '')
  const detailsDirty = dName.trim() !== initName || dMobile.trim() !== initMobile

  const handleSaveDetails = async e => {
    e.preventDefault()
    if (!dName.trim())   { setDetailsFb({ ok: false, msg: 'Name cannot be empty.' }); return }
    if (!dMobile.trim()) { setDetailsFb({ ok: false, msg: 'Mobile cannot be empty.' }); return }
    setDetailsLoading(true)
    setDetailsFb({ ok: false, msg: '' })
    try {
      const res = await updateProfile({ name: dName.trim(), mobile: dMobile.trim() })
      login(res.data.user, res.data.access_token)
      // Reset baseline so button disables again after a successful save
      setInitName(dName.trim())
      setInitMobile(dMobile.trim())
      setDetailsFb({ ok: true, msg: 'Details updated successfully.' })
    } catch (err) {
      setDetailsFb({ ok: false, msg: err.response?.data?.detail ?? 'Update failed.' })
    } finally { setDetailsLoading(false) }
  }

  // ── Change password ────────────────────────────────────────────────────────
  const [oldPw,    setOldPw]    = useState('')
  const [newPw,    setNewPw]    = useState('')
  const [confPw,   setConfPw]   = useState('')
  const [pwLoading, setPwLoading] = useState(false)
  const [pwFb,     setPwFb]     = useState({ ok: false, msg: '' })

  const handleChangePassword = async e => {
    e.preventDefault()
    if (newPw.length < 6)    { setPwFb({ ok: false, msg: 'New password must be at least 6 characters.' }); return }
    if (newPw !== confPw)    { setPwFb({ ok: false, msg: 'Passwords do not match.' }); return }
    setPwLoading(true)
    setPwFb({ ok: false, msg: '' })
    try {
      await changePassword(oldPw, newPw)
      setOldPw(''); setNewPw(''); setConfPw('')
      setPwFb({ ok: true, msg: 'Password changed successfully.' })
    } catch (err) {
      setPwFb({ ok: false, msg: err.response?.data?.detail ?? 'Password change failed.' })
    } finally { setPwLoading(false) }
  }

  // ── Re-join ────────────────────────────────────────────────────────────────
  const [rejoinToken,   setRejoinToken]   = useState('')
  const [rejoinLoading, setRejoinLoading] = useState(false)
  const [rejoinFb,      setRejoinFb]      = useState({ ok: false, msg: '' })

  const handleRejoin = async e => {
    e.preventDefault()
    if (!rejoinToken.trim()) { setRejoinFb({ ok: false, msg: 'Paste a DEP-XXXXXX token to continue.' }); return }
    setRejoinLoading(true)
    setRejoinFb({ ok: false, msg: '' })
    try {
      const res = await rejoinWaitlist(rejoinToken.trim().toUpperCase())
      login(res.data.user, res.data.access_token)
      setRejoinFb({ ok: true, msg: 'You have re-joined the waitlist at Level 1! 🎉' })
      setRejoinToken('')
    } catch (err) {
      setRejoinFb({ ok: false, msg: err.response?.data?.detail ?? 'Re-join failed.' })
    } finally { setRejoinLoading(false) }
  }

  // ── Referral program ──────────────────────────────────────────────────────
  // Uses the PUBLIC /users/{id} endpoint — no JWT required — so a stale or
  // expired token can never trigger the 401-interceptor logout on Profile mount.
  const [refProfile,     setRefProfile]     = useState(user)
  const [refLoading,     setRefLoading]     = useState(false)
  const [payoutLoading,  setPayoutLoading]  = useState(false)
  const [refFb,          setRefFb]          = useState({ ok: false, msg: '' })

  const refreshRefProfile = useCallback(async () => {
    if (!user?.id) return
    setRefLoading(true)
    try {
      const res = await getUser(user.id)   // public endpoint — safe on mount
      setRefProfile(res.data)
      refresh(res.data)                    // sync localStorage (user object only)
    } catch { /* silent – stale display is better than a crash */ }
    finally { setRefLoading(false) }
  }, [user?.id, refresh])

  useEffect(() => { refreshRefProfile() }, [refreshRefProfile])

  // Coerce to plain number for comparisons and display
  const refBalance = Number(refProfile?.accumulated_referral_bonus_inr ?? 0)

  const handleRequestPayout = async () => {
    setPayoutLoading(true)
    setRefFb({ ok: false, msg: '' })
    try {
      const res = await requestReferralPayout()
      setRefFb({
        ok:  true,
        msg: res.data.message ?? 'Request submitted — Pending Admin Approval.',
      })
      await refreshRefProfile()   // show updated (deducted) balance immediately
    } catch (err) {
      const status = err.response?.status
      setRefFb({
        ok:  false,
        msg: status === 409
          ? 'You already have a pending payout request. Wait for admin to approve it.'
          : err.response?.data?.detail ?? 'Request failed. Please try again.',
      })
    } finally { setPayoutLoading(false) }
  }

  const status = user?.status ?? 'Waitlist'

  return (
    <div className="min-h-dvh pb-28 relative">
      <Background />

      {/* ── Sticky header ──────────────────────────────────────── */}
      <div
        className="sticky top-0 z-30 px-5 pt-12 pb-4"
        style={{ background: 'rgba(3,3,24,0.75)', backdropFilter: 'blur(20px)' }}
      >
        <p className="text-[10px] font-mono tracking-[0.3em] text-white/30 uppercase">My Account</p>
        <h1 className="text-2xl font-black text-white">
          @{user?.username ?? '—'}
        </h1>
      </div>

      <div className="px-5 space-y-5">

        {/* ══ WAITLIST STATUS CARD (Waitlist users) ════════════════ */}
        {status === 'Waitlist' && (
          <GlassCard animate className="p-5">
            <SectionLabel>Waitlist Status</SectionLabel>

            {/* Position badge */}
            <div className="flex items-center gap-4 mb-4">
              <motion.div
                className="flex-shrink-0 w-16 h-16 rounded-2xl flex flex-col items-center justify-center"
                style={{
                  background: 'rgba(255,170,0,0.08)',
                  border: '1.5px solid rgba(255,170,0,0.35)',
                  boxShadow: '0 0 20px rgba(255,170,0,0.12)',
                }}
                animate={{ boxShadow: ['0 0 12px rgba(255,170,0,0.10)', '0 0 24px rgba(255,170,0,0.28)', '0 0 12px rgba(255,170,0,0.10)'] }}
                transition={{ duration: 2.4, repeat: Infinity }}
              >
                {loadingPos ? (
                  <motion.div className="w-5 h-5 rounded-full"
                    style={{ border: '2px solid rgba(255,170,0,0.2)', borderTopColor: '#ffaa00' }}
                    animate={{ rotate: 360 }}
                    transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
                  />
                ) : (
                  <>
                    <span className="text-xl font-black" style={{ color: '#ffaa00', lineHeight: 1 }}>
                      #{waitlistPos ?? '—'}
                    </span>
                    <span className="text-[8px] font-mono text-white/30 mt-0.5">IN LINE</span>
                  </>
                )}
              </motion.div>

              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-white/80">On Waitlist</p>
                <p className="text-[11px] text-white/35 mt-0.5 leading-relaxed">
                  You'll enter an active pool as soon as a vacancy opens after the next Sunday draw.
                </p>
              </div>
            </div>

            {/* Dates */}
            <div className="space-y-2.5 pt-3"
              style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <div className="flex items-center gap-2.5">
                <MapPin className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'rgba(255,255,255,0.25)' }} />
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[10px] font-mono text-white/30 uppercase tracking-wider">Joined</span>
                  <span className="text-[11px] font-mono text-white/60">
                    {formatIST(user?.join_date)}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2.5">
                <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'rgba(0,255,136,0.45)' }} />
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[10px] font-mono text-white/30 uppercase tracking-wider">Paid</span>
                  <span className="text-[11px] font-mono" style={{ color: 'rgba(0,255,136,0.70)' }}>
                    {formatIST(user?.join_date)}
                  </span>
                </div>
              </div>
            </div>
          </GlassCard>
        )}

        {/* ══ ACTIVE STANDING MINI-CARD ════════════════════════════ */}
        {status === 'Active' && (
          <GlassCard animate className="p-4 flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(0,240,255,0.08)', border: '1px solid rgba(0,240,255,0.25)' }}>
              <span className="text-xl font-black" style={{ color: '#00f0ff' }}>
                L{user?.current_level}
              </span>
            </div>
            <div>
              <p className="text-xs font-mono font-bold text-white/70">ACTIVE IN POOL</p>
              <p className="text-[11px] text-white/35 mt-0.5">
                Level {user?.current_level} · Week {user?.current_level} of 6
              </p>
            </div>
          </GlassCard>
        )}

        {/* ══ RE-JOIN CARD (Eliminated_Won only) ══════════════════ */}
        {status === 'Eliminated_Won' && (
          <motion.div
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4 }}
          >
            <div
              className="rounded-2xl p-5 relative overflow-hidden"
              style={{
                background: 'rgba(191,0,255,0.06)',
                border: '1px solid rgba(191,0,255,0.35)',
                boxShadow: '0 0 24px rgba(191,0,255,0.12)',
              }}
            >
              <div className="absolute inset-0 pointer-events-none"
                style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(191,0,255,0.08), transparent 60%)' }} />

              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xl">🏆</span>
                  <p className="text-sm font-black" style={{ color: '#d580ff' }}>Vault Winner!</p>
                </div>
                <p className="text-[11px] text-white/40 mb-4 leading-relaxed">
                  You've successfully collected from this vault. Ready to re-enter and win again?
                </p>

                <SectionLabel>Reactivate &amp; Re-Join</SectionLabel>

                <form onSubmit={handleRejoin} className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="block text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
                      New Deposit Token
                    </label>
                    <div className="relative">
                      <input
                        className="neon-input w-full pr-10 font-mono tracking-widest uppercase text-sm"
                        placeholder="DEP-XXXXXX"
                        value={rejoinToken}
                        onChange={e => setRejoinToken(e.target.value.toUpperCase())}
                        autoComplete="off"
                        spellCheck={false}
                      />
                      <Ticket
                        className="absolute right-3.5 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none"
                        style={{ color: rejoinToken ? '#bf00ff' : 'rgba(255,255,255,0.2)' }}
                      />
                    </div>
                    <p className="text-[10px] text-white/25 font-mono pl-1">
                      Obtain a new DEP-XXXXXX token from the admin to re-enter at Level 1.
                    </p>
                  </div>

                  <AnimatePresence>
                    {rejoinFb.msg && <Feedback ok={rejoinFb.ok} msg={rejoinFb.msg} />}
                  </AnimatePresence>

                  <motion.button
                    type="submit"
                    disabled={rejoinLoading}
                    whileTap={{ scale: 0.97 }}
                    className="w-full py-3 rounded-xl text-sm font-black tracking-widest font-mono flex items-center justify-center gap-2 transition-all"
                    style={{
                      background: rejoinLoading ? 'rgba(191,0,255,0.10)' : 'rgba(191,0,255,0.18)',
                      border: '1px solid rgba(191,0,255,0.45)',
                      color: '#d580ff',
                      boxShadow: rejoinLoading ? 'none' : '0 0 18px rgba(191,0,255,0.20)',
                    }}
                  >
                    {rejoinLoading
                      ? <><RefreshCw className="w-4 h-4 animate-spin" /> ACTIVATING…</>
                      : '🔓 REACTIVATE & RE-JOIN'
                    }
                  </motion.button>
                </form>
              </div>
            </div>
          </motion.div>
        )}

        {/* ══ REFERRAL PROGRAM ════════════════════════════════════ */}
        <GlassCard animate className="p-5">
          <SectionLabel>Referral Program</SectionLabel>

          {refLoading ? (
            /* Spinner while fetching fresh stats */
            <div className="flex items-center justify-center py-6">
              <motion.div
                className="w-5 h-5 rounded-full"
                style={{ border: '2px solid rgba(255,170,0,0.18)', borderTopColor: '#ffaa00' }}
                animate={{ rotate: 360 }}
                transition={{ duration: 0.8, repeat: Infinity, ease: 'linear' }}
              />
            </div>
          ) : (
            <>
              {/* ── Stat row ──────────────────────────────────────── */}
              <div className="flex gap-3 mb-4">
                {/* Friends referred */}
                <div
                  className="flex-1 rounded-xl p-3 text-center"
                  style={{
                    background: 'rgba(255,170,0,0.06)',
                    border:     '1px solid rgba(255,170,0,0.18)',
                  }}
                >
                  <p className="text-2xl font-black tabular-nums" style={{ color: '#ffaa00' }}>
                    {refProfile?.total_referrals_count ?? 0}
                  </p>
                  <p className="text-[10px] font-mono text-white/30 uppercase tracking-wider mt-0.5">
                    Friends Referred
                  </p>
                </div>

                {/* Accumulated pending bonus */}
                <div
                  className="flex-1 rounded-xl p-3 text-center"
                  style={{
                    background: refBalance >= 1000
                      ? 'rgba(0,255,136,0.06)'
                      : 'rgba(255,255,255,0.03)',
                    border: refBalance >= 1000
                      ? '1px solid rgba(0,255,136,0.22)'
                      : '1px solid rgba(255,255,255,0.07)',
                  }}
                >
                  <p
                    className="text-2xl font-black tabular-nums"
                    style={{ color: refBalance >= 1000 ? '#00ff88' : 'rgba(255,255,255,0.35)' }}
                  >
                    ₹{refBalance.toLocaleString('en-IN')}
                  </p>
                  <p className="text-[10px] font-mono text-white/30 uppercase tracking-wider mt-0.5">
                    Pending Bonus
                  </p>
                </div>
              </div>

              {/* ── Rule hint ─────────────────────────────────────── */}
              <div
                className="rounded-xl px-3 py-2.5 mb-4"
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border:     '1px solid rgba(255,255,255,0.06)',
                }}
              >
                <p className="text-[10px] font-mono text-white/35 leading-relaxed">
                  Earn a bonus for every friend you refer who joins the scheme.
                  A minimum of{' '}
                  <span style={{ color: 'rgba(255,170,0,0.80)' }}>₹1,000 accumulated bonus</span>{' '}
                  is required to submit a payout request.
                  Approved payouts are collected in cash from the admin.
                </p>
              </div>

              {/* ── Feedback banner ───────────────────────────────── */}
              <AnimatePresence>
                {refFb.msg && <Feedback ok={refFb.ok} msg={refFb.msg} />}
              </AnimatePresence>

              {/* ── Request payout button ─────────────────────────── */}
              <motion.button
                onClick={handleRequestPayout}
                disabled={payoutLoading || refBalance < 1000}
                whileTap={payoutLoading || refBalance < 1000 ? {} : { scale: 0.97 }}
                className="mt-3 w-full py-3 rounded-xl text-sm font-black tracking-widest font-mono flex items-center justify-center gap-2 transition-all"
                style={{
                  background: refBalance < 1000
                    ? 'rgba(255,170,0,0.04)'
                    : 'rgba(255,170,0,0.14)',
                  border: `1px solid rgba(255,170,0,${refBalance < 1000 ? '0.12' : '0.42'})`,
                  color:  refBalance < 1000 ? 'rgba(255,170,0,0.28)' : '#ffaa00',
                  boxShadow: refBalance < 1000 ? 'none' : '0 0 18px rgba(255,170,0,0.15)',
                  cursor: payoutLoading || refBalance < 1000 ? 'not-allowed' : 'pointer',
                }}
              >
                {payoutLoading ? (
                  <><RefreshCw className="w-4 h-4 animate-spin" /> SUBMITTING…</>
                ) : refBalance < 1000 ? (
                  `🔒 ₹${(1000 - refBalance).toLocaleString('en-IN')} MORE TO UNLOCK`
                ) : (
                  <><Gift className="w-4 h-4" /> REQUEST BONUS PAYOUT</>
                )}
              </motion.button>
            </>
          )}
        </GlassCard>

        {/* ══ PERSONAL DETAILS ════════════════════════════════════ */}
        <GlassCard animate className="p-5">
          <SectionLabel>Personal Details</SectionLabel>
          <form onSubmit={handleSaveDetails} className="space-y-4">

            {/* Name */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
                <User className="w-3 h-3" /> Full Name
              </label>
              <input
                className="neon-input w-full"
                value={dName}
                onChange={e => setDName(e.target.value)}
                placeholder="Enter your name"
                autoComplete="name"
              />
            </div>

            {/* Mobile */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-1.5 text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
                <Phone className="w-3 h-3" /> Mobile Number
              </label>
              <input
                className="neon-input w-full"
                value={dMobile}
                onChange={e => setDMobile(e.target.value)}
                placeholder="+91 XXXXX XXXXX"
                inputMode="tel"
                autoComplete="tel"
              />
            </div>

            {/* Username — immutable */}
            <div className="space-y-1.5 opacity-50">
              <label className="flex items-center gap-1.5 text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
                <Lock className="w-3 h-3" /> Username
                <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded-md font-mono normal-case"
                  style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.25)' }}>
                  cannot be changed
                </span>
              </label>
              <input
                className="neon-input w-full font-mono tracking-wider cursor-not-allowed"
                value={user?.username ?? ''}
                readOnly
                disabled
                style={{ color: 'rgba(255,255,255,0.30)' }}
              />
            </div>

            <AnimatePresence>
              {detailsFb.msg && <Feedback ok={detailsFb.ok} msg={detailsFb.msg} />}
            </AnimatePresence>

            <NeonButton type="submit" disabled={detailsLoading || !detailsDirty}>
              <span className="text-sm tracking-widest">
                {detailsLoading ? 'SAVING…' : detailsDirty ? 'SAVE DETAILS' : 'NO CHANGES'}
              </span>
            </NeonButton>
          </form>
        </GlassCard>

        {/* ══ CHANGE PASSWORD ═════════════════════════════════════ */}
        <GlassCard animate className="p-5">
          <SectionLabel>Change Password</SectionLabel>
          <form onSubmit={handleChangePassword} className="space-y-4">

            <PwField
              label="Current Password"
              value={oldPw}
              onChange={e => setOldPw(e.target.value)}
              autoComplete="current-password"
            />
            <PwField
              label="New Password"
              value={newPw}
              onChange={e => setNewPw(e.target.value)}
              autoComplete="new-password"
            />
            <PwField
              label="Confirm New Password"
              value={confPw}
              onChange={e => setConfPw(e.target.value)}
              autoComplete="new-password"
            />

            {/* Strength hint */}
            {newPw.length > 0 && newPw.length < 6 && (
              <p className="text-[10px] font-mono text-amber-400/70 flex items-center gap-1">
                <AlertCircle className="w-3 h-3" /> Min. 6 characters
              </p>
            )}

            <AnimatePresence>
              {pwFb.msg && <Feedback ok={pwFb.ok} msg={pwFb.msg} />}
            </AnimatePresence>

            <NeonButton
              type="submit"
              disabled={pwLoading || newPw.length < 6 || newPw !== confPw || !oldPw}
            >
              <span className="text-sm tracking-widest">
                {pwLoading ? 'UPDATING…' : 'UPDATE PASSWORD'}
              </span>
            </NeonButton>
          </form>
        </GlassCard>

      </div>
      <BottomNav />
    </div>
  )
}
