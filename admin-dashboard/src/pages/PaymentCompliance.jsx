/**
 * PaymentCompliance.jsx — Admin · Payment Compliance & Elimination Engine
 *
 * 4 tabs:
 *  1. Late Payers       — all unpaid active members + days late + fees + AI risk score
 *  2. Grace Period      — members in grace window + countdown + confirm payment button
 *  3. Elimination Risk  — members past due date, sortable by pool/level/fee
 *  4. Elimination History — EliminationEvent audit log + financial summary strip
 *
 * AI Risk Score (computed frontend):
 *   risk = (days_late_factor × 0.6) + (level_factor × 0.4)
 *   Colour: 0–0.4 = green, 0.4–0.7 = amber, 0.7–1.0 = red
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  ShieldAlert, Clock, XCircle, CheckCircle2, AlertTriangle,
  RefreshCw, DollarSign, Users, Gavel, Timer, ChevronRight,
  BadgeAlert, Info, Settings, Eye, Save, Lock, ToggleLeft, ToggleRight,
  ChevronDown,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import Modal from '../components/Modal'
import { useToast } from '../context/ToastContext'
import {
  getLatePayers, getAtRiskUsers, getGracePeriodUsers,
  getEliminationHistory, getEliminationSettings, updateEliminationSettings,
  markAtRisk, grantGracePeriod, saveSeat, executeElimination,
} from '../api/client'

const INR = v =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v ?? 0)

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function fmtCountdown(seconds) {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

// ── Risk Score Chip ──────────────────────────────────────────────────────────
function RiskChip({ score }) {
  if (score == null) return null
  const v = parseFloat(score)
  const cfg = v >= 0.7 ? { label: 'HIGH',   cls: 'bg-red-100 text-red-700 border-red-300' }
            : v >= 0.4 ? { label: 'MED',    cls: 'bg-amber-100 text-amber-700 border-amber-300' }
                       : { label: 'LOW',    cls: 'bg-emerald-100 text-emerald-700 border-emerald-300' }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${cfg.cls}`}>
      {cfg.label} {(v * 100).toFixed(0)}
    </span>
  )
}

// ── Section Tabs ─────────────────────────────────────────────────────────────
const TABS = [
  { id: 'late',     label: 'Late Payers',      icon: DollarSign,  color: 'amber'  },
  { id: 'grace',    label: 'Grace Period',     icon: Timer,       color: 'violet' },
  { id: 'risk',     label: 'Elimination Risk', icon: BadgeAlert,  color: 'red'    },
  { id: 'history',  label: 'History',          icon: Gavel,       color: 'slate'  },
  { id: 'settings', label: 'Settings',         icon: Settings,    color: 'blue'   },
]

const TAB_ACTIVE = {
  amber:  'bg-amber-600  text-white',
  violet: 'bg-violet-600 text-white',
  red:    'bg-red-600    text-white',
  slate:  'bg-slate-700  text-white',
  blue:   'bg-blue-600   text-white',
}
const TAB_INACTIVE = 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'

// ── Due-day and time dropdown options ─────────────────────────────────────────
const DUE_DAY_OPTIONS = [
  { value: 1, label: 'Monday (Day 1 after draw)'    },
  { value: 2, label: 'Tuesday (Day 2 after draw)'   },
  { value: 3, label: 'Wednesday (Day 3 after draw)' },
  { value: 4, label: 'Thursday (Day 4 after draw)'  },
  { value: 5, label: 'Friday (Day 5 after draw)'    },
  { value: 6, label: 'Saturday (Day 6 after draw)'  },
]

const DUE_HOUR_OPTIONS = [
  { value: 0,  label: '12:00 AM (Midnight)' },
  { value: 6,  label: '6:00 AM'  },
  { value: 8,  label: '8:00 AM'  },
  { value: 10, label: '10:00 AM' },
  { value: 12, label: '12:00 PM (Noon)' },
  { value: 14, label: '2:00 PM'  },
  { value: 16, label: '4:00 PM'  },
  { value: 18, label: '6:00 PM'  },
  { value: 20, label: '8:00 PM'  },
  { value: 22, label: '10:00 PM' },
  { value: 23, label: '11:00 PM' },
]

const LATE_FEE_OPTIONS = [
  { value: 0,   label: '₹0 / day  (no late fee)'       },
  { value: 25,  label: '₹25 / day  (2.5% of deposit)'  },
  { value: 50,  label: '₹50 / day  (5% of deposit)'    },
  { value: 75,  label: '₹75 / day  (7.5% of deposit)'  },
  { value: 100, label: '₹100 / day  (10% of deposit)'  },
  { value: -1,  label: 'Custom amount per day →'        },
]

const GRACE_HOURS_OPTIONS = [
  { value: 12,  label: '12 hours'  },
  { value: 24,  label: '24 hours (1 day)' },
  { value: 36,  label: '36 hours'  },
  { value: 48,  label: '48 hours (2 days)' },
  { value: 72,  label: '72 hours (3 days)' },
  { value: 96,  label: '96 hours (4 days)' },
  { value: 120, label: '120 hours (5 days)' },
  { value: 168, label: '168 hours (7 days)' },
]

// ── Confirmation countdown for Execute button ─────────────────────────────────
function ExecuteModal({ open, onClose, onConfirm, loading }) {
  const [password, setPassword] = useState('')
  const [dryRun,   setDryRun]   = useState(false)
  const [confirm,  setConfirm]  = useState('')

  useEffect(() => { if (!open) { setPassword(''); setConfirm(''); setDryRun(false) } }, [open])

  const ready = password.trim().length > 0 && (dryRun || confirm === 'ELIMINATE')

  return (
    <Modal open={open} onClose={onClose} title="Execute Elimination Cycle" maxWidth="max-w-md">
      <div className="space-y-4">
        <div className="flex gap-3 p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <XCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <p>This will permanently eliminate all members who are past due date AND have not entered or completed their grace period. <strong>This cannot be undone.</strong></p>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1">Admin Password <span className="text-red-500">*</span></label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400" placeholder="Enter your admin password" />
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)}
            className="w-4 h-4 rounded accent-violet-600" />
          <span className="text-sm text-slate-700">Dry run — preview only, no changes made</span>
        </label>

        {!dryRun && (
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1">
              Type <span className="font-mono text-red-600">ELIMINATE</span> to confirm
            </label>
            <input type="text" value={confirm} onChange={e => setConfirm(e.target.value)}
              className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-red-400" placeholder="ELIMINATE" />
          </div>
        )}

        <div className="flex gap-3 justify-end">
          <button onClick={onClose} disabled={loading} className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-xl transition">Cancel</button>
          <button onClick={() => onConfirm(password, dryRun)} disabled={!ready || loading}
            className={`flex items-center gap-2 px-5 py-2 text-sm font-bold rounded-xl text-white transition ${dryRun ? 'bg-violet-600 hover:bg-violet-700 disabled:opacity-50' : 'bg-red-600 hover:bg-red-700 disabled:opacity-40'}`}>
            {loading ? <Spinner className="w-4 h-4 text-white" /> : <Gavel className="w-4 h-4" />}
            {dryRun ? 'Preview Dry Run' : 'Execute Elimination'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// Main Component
// ═════════════════════════════════════════════════════════════════════════════

export default function PaymentCompliance() {
  const toast = useToast()
  const [tab, setTab] = useState('late')

  // ── Data state ──────────────────────────────────────────────────────────
  const [latePayers,   setLatePayers]   = useState([])
  const [atRisk,       setAtRisk]       = useState([])
  const [gracePeriod,  setGracePeriod]  = useState([])
  const [history,      setHistory]      = useState([])
  const [histSummary,  setHistSummary]  = useState(null)
  const [settings,     setSettings]     = useState(null)
  const [loading,      setLoading]      = useState(true)
  const [refreshing,   setRefreshing]   = useState(false)

  // ── Action modals ───────────────────────────────────────────────────────
  const [execOpen,     setExecOpen]     = useState(false)
  const [execLoading,  setExecLoading]  = useState(false)
  const [execResult,   setExecResult]   = useState(null)

  // Grace period confirmation
  const [graceConfirmUid, setGraceConfirmUid] = useState(null)
  const [saveSeatPw,      setSaveSeatPw]      = useState('')
  const [saveSeatLoading, setSaveSeatLoading] = useState(false)

  // ── Refresh countdown timer ─────────────────────────────────────────────
  const tickRef = useRef(null)
  useEffect(() => {
    if (!gracePeriod.length) return
    tickRef.current = setInterval(() => {
      setGracePeriod(prev => prev.map(u => ({
        ...u,
        time_remaining_seconds: u.time_remaining_seconds != null
          ? Math.max(0, u.time_remaining_seconds - 1) : null,
      })))
    }, 1000)
    return () => clearInterval(tickRef.current)
  }, [gracePeriod.length])

  // ── Fetch all data ──────────────────────────────────────────────────────
  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    try {
      const [lpRes, riskRes, graceRes, histRes, settRes] = await Promise.allSettled([
        getLatePayers({ limit: 500 }),
        getAtRiskUsers({ limit: 500 }),
        getGracePeriodUsers(),
        getEliminationHistory({ limit: 200 }),
        getEliminationSettings(),
      ])
      if (lpRes.status   === 'fulfilled') setLatePayers(lpRes.value.data.items ?? [])
      if (riskRes.status === 'fulfilled') setAtRisk(riskRes.value.data.items ?? [])
      if (graceRes.status=== 'fulfilled') setGracePeriod(graceRes.value.data.items ?? [])
      if (histRes.status === 'fulfilled') {
        setHistory(histRes.value.data.events ?? [])
        setHistSummary(histRes.value.data.summary ?? null)
      }
      if (settRes.status === 'fulfilled') setSettings(settRes.value.data)
    } catch {
      toast('Failed to load compliance data', 'error')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchAll() }, [fetchAll])

  // ── Execute elimination ─────────────────────────────────────────────────
  const handleExecute = async (password, dryRun) => {
    setExecLoading(true); setExecResult(null)
    try {
      const res = await executeElimination(password, dryRun)
      setExecResult(res.data)
      if (!dryRun) {
        toast(res.data.message, 'success')
        fetchAll(true)
      }
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Elimination failed', 'error')
    } finally {
      setExecLoading(false)
    }
  }

  // ── Mark at risk ────────────────────────────────────────────────────────
  const handleMarkAtRisk = async () => {
    try {
      const res = await markAtRisk()
      toast(res.data.message, res.data.newly_flagged > 0 ? 'warning' : 'info')
      fetchAll(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed', 'error')
    }
  }

  // ── Grant grace ─────────────────────────────────────────────────────────
  const handleGrantGrace = async (uid) => {
    try {
      const res = await grantGracePeriod(uid, 48)
      toast(res.data.message, 'info')
      fetchAll(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to grant grace', 'error')
    }
  }

  // ── Save seat ───────────────────────────────────────────────────────────
  const handleSaveSeat = async () => {
    if (!graceConfirmUid || !saveSeatPw.trim()) return
    setSaveSeatLoading(true)
    try {
      const res = await saveSeat(graceConfirmUid, saveSeatPw)
      toast(res.data.message, 'success')
      setGraceConfirmUid(null); setSaveSeatPw('')
      fetchAll(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to save seat', 'error')
    } finally {
      setSaveSeatLoading(false)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64"><Spinner className="w-8 h-8" /></div>
  )

  const tabCounts = {
    late:    latePayers.length,
    grace:   gracePeriod.length,
    risk:    atRisk.length,
    history: history.length,
  }

  return (
    <div className="p-8 space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-red-600" />
            Payment Compliance
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {atRisk.length > 0 && <span className="text-red-600 font-semibold">{atRisk.length} at-risk · </span>}
            {gracePeriod.length > 0 && <span className="text-violet-600 font-semibold">{gracePeriod.length} in grace · </span>}
            {latePayers.length} late payers total
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => fetchAll(true)} disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition">
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={handleMarkAtRisk}
            className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-xl text-sm font-semibold shadow-sm transition">
            <AlertTriangle className="w-4 h-4" />
            Scan &amp; Flag At-Risk
          </button>
          <button onClick={() => setExecOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-sm font-semibold shadow-sm transition">
            <Gavel className="w-4 h-4" />
            Execute Elimination
          </button>
        </div>
      </div>

      {/* Summary stats strip */}
      {histSummary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Total Eliminations', value: histSummary.total_eliminations.toLocaleString('en-IN'), icon: Gavel, color: 'red' },
            { label: 'Total Forfeited',    value: INR(histSummary.total_forfeited_inr),                   icon: DollarSign, color: 'orange' },
            { label: 'Late Fees Forfeited',value: INR(histSummary.total_late_fees_inr),                    icon: Clock, color: 'amber' },
            { label: 'Deposits Forfeited', value: INR(histSummary.total_deposits_forfeited),               icon: XCircle, color: 'slate' },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="bg-white rounded-xl border border-slate-100 shadow-sm px-4 py-3 flex items-center gap-3">
              <div className={`p-2 rounded-lg bg-${color}-50`}><Icon className={`w-4 h-4 text-${color}-600`} /></div>
              <div>
                <p className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider">{label}</p>
                <p className="text-base font-bold text-slate-800">{value}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 flex-wrap">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition ${
              tab === t.id ? TAB_ACTIVE[t.color] : TAB_INACTIVE
            }`}>
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
            {tabCounts[t.id] > 0 && (
              <span className={`ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
                tab === t.id ? 'bg-white/20' : 'bg-slate-100 text-slate-600'
              }`}>{tabCounts[t.id]}</span>
            )}
          </button>
        ))}
      </div>

      {/* ── TAB: Late Payers ─────────────────────────────────────────────────── */}
      {tab === 'late' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-amber-50/50">
            <p className="text-sm font-semibold text-amber-700">{latePayers.length} unpaid active members — sorted by AI risk score</p>
          </div>
          {latePayers.length === 0 ? (
            <div className="py-12 text-center text-slate-400 text-sm">No late payers — all members are paid ✓</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[800px]">
                <thead className="bg-slate-50 border-b border-slate-100">
                  <tr>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">#</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Member</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Level</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Pool</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Late Fees</th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Risk</th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {latePayers.map((u, i) => (
                    <tr key={u.id} className={`hover:bg-amber-50/40 transition-colors ${u.elimination_risk ? 'bg-red-50/30' : ''}`}>
                      <td className="px-4 py-3 text-xs text-slate-400">{i + 1}</td>
                      <td className="px-4 py-3">
                        <p className="font-semibold text-slate-800">{u.name}</p>
                        <p className="text-xs text-slate-400 font-mono">@{u.username}</p>
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold bg-blue-100 text-blue-700">L{u.current_level}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">{u.current_pool_id ? `Pool #${u.current_pool_id}` : '—'}</td>
                      <td className="px-4 py-3 text-right font-mono font-semibold text-red-700">{INR(u.late_fees_inr)}</td>
                      <td className="px-4 py-3 text-center"><RiskChip score={u.risk_score} /></td>
                      <td className="px-4 py-3 text-center">
                        {!u.grace_active && (
                          <button onClick={() => handleGrantGrace(u.id)}
                            className="px-3 py-1 text-xs font-semibold bg-violet-100 text-violet-700 rounded-lg hover:bg-violet-200 transition">
                            Grant Grace
                          </button>
                        )}
                        {u.grace_active && (
                          <span className="px-3 py-1 text-xs font-semibold bg-violet-50 text-violet-600 rounded-lg border border-violet-200">In Grace</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── TAB: Grace Period ─────────────────────────────────────────────────── */}
      {tab === 'grace' && (
        <div className="space-y-4">
          {gracePeriod.length === 0 ? (
            <div className="bg-white rounded-2xl shadow-sm border border-slate-100 py-12 text-center text-slate-400 text-sm">
              No members currently in the grace period window.
            </div>
          ) : gracePeriod.map(u => (
            <div key={u.id} className={`bg-white rounded-2xl shadow-sm border overflow-hidden transition ${
              u.expired ? 'border-red-300 bg-red-50/30' : 'border-violet-200'
            }`}>
              <div className="flex items-center justify-between px-5 py-3 border-b border-inherit">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-xl ${u.expired ? 'bg-red-100' : 'bg-violet-100'}`}>
                    <Timer className={`w-4 h-4 ${u.expired ? 'text-red-600' : 'text-violet-600'}`} />
                  </div>
                  <div>
                    <p className="font-bold text-slate-800">{u.name} <span className="font-mono text-slate-400 text-xs">@{u.username}</span></p>
                    <p className="text-xs text-slate-500">Level {u.current_level} · Late fees: {INR(u.late_fees_inr)}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className={`text-right ${u.expired ? 'text-red-600' : 'text-violet-700'}`}>
                    <p className="text-xs font-semibold uppercase tracking-wider">{u.expired ? 'EXPIRED' : 'Expires in'}</p>
                    <p className="text-lg font-mono font-bold">{u.expired ? '00:00' : fmtCountdown(u.time_remaining_seconds)}</p>
                  </div>
                  {!u.grace_fee_paid && (
                    <button onClick={() => { setGraceConfirmUid(u.id); setSaveSeatPw('') }}
                      className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-sm font-semibold transition">
                      <CheckCircle2 className="w-4 h-4" />
                      Confirm Payment
                    </button>
                  )}
                  {u.grace_fee_paid && (
                    <span className="flex items-center gap-1.5 px-4 py-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl text-sm font-semibold">
                      <CheckCircle2 className="w-4 h-4" /> Seat Saved
                    </span>
                  )}
                </div>
              </div>
              <div className="px-5 py-3 text-xs text-slate-500">
                Grace expires: <span className="font-semibold text-slate-700">{fmtDate(u.grace_expires_at)}</span>
                &nbsp;·&nbsp; Risk score: <RiskChip score={u.risk_score} />
              </div>
            </div>
          ))}

          {/* Confirm grace payment modal */}
          {graceConfirmUid && (
            <Modal open={!!graceConfirmUid} onClose={() => { setGraceConfirmUid(null); setSaveSeatPw('') }}
              title="Confirm Grace Payment" maxWidth="max-w-md">
              <div className="space-y-4">
                <p className="text-sm text-slate-600">
                  Confirm that the member has physically paid the grace fee + accumulated late fees.
                  This will clear their elimination risk and mark them as Paid.
                </p>
                <div>
                  <label className="block text-xs font-semibold text-slate-600 mb-1">Admin Password <span className="text-red-500">*</span></label>
                  <input type="password" value={saveSeatPw} onChange={e => setSaveSeatPw(e.target.value)}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-400" placeholder="Your admin password" />
                </div>
                <div className="flex gap-3 justify-end">
                  <button onClick={() => { setGraceConfirmUid(null); setSaveSeatPw('') }} disabled={saveSeatLoading}
                    className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-xl transition">Cancel</button>
                  <button onClick={handleSaveSeat} disabled={!saveSeatPw.trim() || saveSeatLoading}
                    className="flex items-center gap-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded-xl disabled:opacity-50 transition">
                    {saveSeatLoading ? <Spinner className="w-4 h-4 text-white" /> : <Save className="w-4 h-4" />}
                    Save Seat
                  </button>
                </div>
              </div>
            </Modal>
          )}
        </div>
      )}

      {/* ── TAB: Elimination Risk ─────────────────────────────────────────────── */}
      {tab === 'risk' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-red-50/50 flex items-center justify-between">
            <p className="text-sm font-semibold text-red-700">{atRisk.length} members will be eliminated in next cycle</p>
            {atRisk.length > 0 && (
              <button onClick={() => setExecOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold bg-red-600 hover:bg-red-700 text-white rounded-lg transition">
                <Gavel className="w-3.5 h-3.5" /> Execute Now
              </button>
            )}
          </div>
          {atRisk.length === 0 ? (
            <div className="py-12 text-center text-slate-400 text-sm flex flex-col items-center gap-2">
              <CheckCircle2 className="w-8 h-8 text-emerald-400" />
              No members at elimination risk
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[700px]">
                <thead className="bg-slate-50 border-b border-slate-100">
                  <tr>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">#</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Member</th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Level</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Pool</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Total Due</th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Risk</th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-red-50">
                  {atRisk.map((u, i) => (
                    <tr key={u.id} className="bg-red-50/30 hover:bg-red-50 transition-colors">
                      <td className="px-4 py-3 text-xs text-slate-400">{i + 1}</td>
                      <td className="px-4 py-3">
                        <p className="font-semibold text-slate-800">{u.name}</p>
                        <p className="text-xs text-slate-400 font-mono">@{u.username}</p>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold bg-red-100 text-red-700">L{u.current_level}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">{u.current_pool_id ? `Pool #${u.current_pool_id}` : '—'}</td>
                      <td className="px-4 py-3 text-right font-mono font-bold text-red-700">{INR(1000 + (u.late_fees_inr || 0))}</td>
                      <td className="px-4 py-3 text-center"><RiskChip score={u.risk_score} /></td>
                      <td className="px-4 py-3 text-center">
                        <button onClick={() => handleGrantGrace(u.id)}
                          className="px-3 py-1 text-xs font-semibold bg-violet-100 text-violet-700 rounded-lg hover:bg-violet-200 transition">
                          Grant Grace
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── TAB: History ─────────────────────────────────────────────────────── */}
      {tab === 'history' && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100">
            <p className="text-sm font-semibold text-slate-700">{history.length} elimination records</p>
          </div>
          {history.length === 0 ? (
            <div className="py-12 text-center text-slate-400 text-sm">No eliminations yet</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[800px]">
                <thead className="bg-slate-50 border-b border-slate-100">
                  <tr>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Member</th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Level</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Reason</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Week</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Forfeited</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {history.map(ev => (
                    <tr key={ev.id} className="hover:bg-slate-50/60">
                      <td className="px-4 py-3">
                        <p className="font-semibold text-slate-800">{ev.username}</p>
                        {ev.pool_name && <p className="text-xs text-slate-400">{ev.pool_name}</p>}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold bg-slate-100 text-slate-600">
                          L{ev.user_level_at_elimination}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                          ev.reason === 'grace_expired'
                            ? 'bg-violet-50 text-violet-700 border-violet-200'
                            : 'bg-red-50 text-red-700 border-red-200'
                        }`}>
                          {ev.reason === 'grace_expired' ? <Timer className="w-2.5 h-2.5" /> : <XCircle className="w-2.5 h-2.5" />}
                          {ev.reason === 'grace_expired' ? 'Grace Expired' : 'Non-Payment'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 font-mono">{ev.draw_week_id || '—'}</td>
                      <td className="px-4 py-3 text-right font-mono font-bold text-slate-800">{INR(ev.total_forfeited_inr)}</td>
                      <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(ev.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── TAB: Settings ─────────────────────────────────────────────────────── */}
      {tab === 'settings' && settings && (
        <SettingsPanel settings={settings} onSaved={() => fetchAll(true)} toast={toast} />
      )}

      {/* Elimination Execute Modal */}
      <ExecuteModal
        open={execOpen}
        onClose={() => { setExecOpen(false); setExecResult(null) }}
        onConfirm={handleExecute}
        loading={execLoading}
      />

      {/* Dry-run result display */}
      {execResult && execResult.dry_run && (
        <div className="bg-violet-50 border border-violet-200 rounded-2xl p-5">
          <p className="font-semibold text-violet-800 mb-2">
            Dry Run Result — would eliminate {execResult.would_eliminate} member(s)
            {execResult.grace_expired_count > 0 && ` (${execResult.grace_expired_count} grace expired)`}
          </p>
          {execResult.users?.length > 0 && (
            <ul className="text-xs text-violet-700 space-y-0.5 font-mono">
              {execResult.users.slice(0, 20).map(u => (
                <li key={u.id}>• @{u.username} L{u.level} {u.pool_id ? `Pool#${u.pool_id}` : ''} — {INR(u.late_fees)} late fees</li>
              ))}
              {execResult.users.length > 20 && <li className="text-violet-500">… and {execResult.users.length - 20} more</li>}
            </ul>
          )}
        </div>
      )}

    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
// Settings Panel — full elimination & grace period configuration
// ═════════════════════════════════════════════════════════════════════════════

function SettingsPanel({ settings: initSettings, onSaved, toast }) {
  const [form,        setForm]        = useState({ ...initSettings })
  const [password,    setPassword]    = useState('')
  const [saving,      setSaving]      = useState(false)
  const [customFee,   setCustomFee]   = useState(initSettings.late_fee_per_day_inr ?? 50)
  // Determine if the current fee value matches a preset
  const presetMatch = LATE_FEE_OPTIONS.find(o => o.value === (initSettings.late_fee_per_day_inr ?? 50) && o.value !== -1)
  const [feeMode,     setFeeMode]     = useState(presetMatch ? 'preset' : 'custom')
  const [graceMode,   setGraceMode]   = useState('preset')  // 'preset' | 'custom'
  const [customGrace, setCustomGrace] = useState(initSettings.grace_period_hours ?? 48)

  const update = (key, val) => setForm(prev => ({ ...prev, [key]: val }))

  const handleSave = async () => {
    if (!password.trim()) { toast('Admin password required', 'error'); return }
    setSaving(true)
    try {
      const payload = {
        ...form,
        late_fee_per_day_inr: feeMode === 'custom' ? customFee : form.late_fee_per_day_inr,
        grace_period_hours:   graceMode === 'custom' ? customGrace : form.grace_period_hours,
        admin_password:       password,
      }
      await updateEliminationSettings(payload)
      toast('Settings saved', 'success')
      setPassword('')
      onSaved()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to save settings', 'error')
    } finally {
      setSaving(false)
    }
  }

  const SelectRow = ({ label, hint, children }) => (
    <div className="grid grid-cols-1 sm:grid-cols-3 items-start gap-3 py-4 border-b border-slate-100 last:border-0">
      <div>
        <p className="text-sm font-semibold text-slate-700">{label}</p>
        {hint && <p className="text-xs text-slate-400 mt-0.5">{hint}</p>}
      </div>
      <div className="sm:col-span-2">{children}</div>
    </div>
  )

  const Toggle2 = ({ checked, onChange }) => (
    <button type="button" role="switch" aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors ${checked ? 'bg-emerald-500' : 'bg-slate-200'}`}>
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  )

  return (
    <div className="space-y-5">
      {/* Info banner */}
      <div className="flex gap-3 p-4 bg-blue-50 border border-blue-200 rounded-2xl text-sm text-blue-800">
        <Info className="w-4 h-4 flex-shrink-0 mt-0.5 text-blue-600" />
        <p>Changes require admin password confirmation and take effect from the next penalty cycle. Due date settings are relative to the weekly draw (Sunday T+0).</p>
      </div>

      {/* Settings card */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <h2 className="font-bold text-slate-800 flex items-center gap-2">
            <Settings className="w-4 h-4 text-blue-600" />
            Elimination & Grace Period Configuration
          </h2>
        </div>
        <div className="px-6 py-2 divide-y divide-slate-100">

          {/* Due day */}
          <SelectRow label="Payment Due Day" hint="Days after draw opens (draw = Sunday T+0)">
            <select value={form.payment_due_days ?? 4} onChange={e => update('payment_due_days', +e.target.value)}
              className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400">
              {DUE_DAY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </SelectRow>

          {/* Due hour */}
          <SelectRow label="Payment Due Time" hint="Hour of the due day (IST, 24-hour format)">
            <select value={form.payment_due_hour ?? 23} onChange={e => update('payment_due_hour', +e.target.value)}
              className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400">
              {DUE_HOUR_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </SelectRow>

          {/* Late fee rate */}
          <SelectRow label="Late Fee Rate" hint="Charged per day from T+1 until payment or elimination">
            <div className="space-y-2">
              <select
                value={feeMode === 'custom' ? -1 : (form.late_fee_per_day_inr ?? 50)}
                onChange={e => {
                  const v = +e.target.value
                  if (v === -1) { setFeeMode('custom') }
                  else { setFeeMode('preset'); update('late_fee_per_day_inr', v) }
                }}
                className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400">
                {LATE_FEE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              {feeMode === 'custom' && (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-slate-500">₹</span>
                  <input type="number" min={0} max={500} step={5} value={customFee}
                    onChange={e => { const v = Math.max(0, Math.min(500, +e.target.value || 0)); setCustomFee(v); update('late_fee_per_day_inr', v) }}
                    className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" placeholder="Custom ₹ per day" />
                  <span className="text-xs text-slate-400">/ day (max ₹500)</span>
                </div>
              )}
              <p className="text-[11px] text-slate-400">
                ₹1,000 deposit × 5% min = <strong>₹50/day</strong> minimum recommended
              </p>
            </div>
          </SelectRow>

          {/* Late fee max cap */}
          <SelectRow label="Late Fee Max Cap" hint="Maximum total late fee accumulation before member is auto-eliminated">
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">₹</span>
              <input type="number" min={50} max={2000} step={50} value={form.late_fee_max_cap_inr ?? 500}
                onChange={e => update('late_fee_max_cap_inr', Math.max(50, Math.min(2000, +e.target.value || 50)))}
                className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              <span className="text-xs text-slate-400">maximum total</span>
            </div>
          </SelectRow>

          {/* Grace period duration */}
          <SelectRow label="Grace Period Duration" hint="Window between due date and draw T-2H for seat-saving payment">
            <div className="space-y-2">
              <select
                value={graceMode === 'custom' ? -1 : (form.grace_period_hours ?? 48)}
                onChange={e => {
                  const v = +e.target.value
                  if (v === -1) { setGraceMode('custom') }
                  else { setGraceMode('preset'); update('grace_period_hours', v) }
                }}
                className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-400">
                {GRACE_HOURS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                <option value={-1}>Custom hours →</option>
              </select>
              {graceMode === 'custom' && (
                <div className="flex items-center gap-2">
                  <input type="number" min={1} max={168} step={1} value={customGrace}
                    onChange={e => { const v = Math.max(1, Math.min(168, +e.target.value || 1)); setCustomGrace(v); update('grace_period_hours', v) }}
                    className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
                  <span className="text-xs text-slate-400">hours (1–168)</span>
                </div>
              )}
            </div>
          </SelectRow>

          {/* Grace seat-save fee */}
          <SelectRow label="Grace Seat-Save Fee" hint="Extra fee member must pay during grace period to keep their seat (in addition to late fees)">
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">₹</span>
              <input type="number" min={0} max={2000} step={50} value={form.grace_seat_save_fee_inr ?? 500}
                onChange={e => update('grace_seat_save_fee_inr', Math.max(0, Math.min(2000, +e.target.value || 0)))}
                className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              <span className="text-xs text-slate-400">seat-save fee</span>
            </div>
          </SelectRow>

          {/* Auto-eliminate toggle */}
          <SelectRow label="Auto-Eliminate" hint="Automatically eliminate unpaid members when due date passes">
            <div className="flex items-center gap-3">
              <Toggle2 checked={!!form.auto_eliminate_enabled} onChange={v => update('auto_eliminate_enabled', v)} />
              <span className={`text-sm font-semibold ${form.auto_eliminate_enabled ? 'text-emerald-600' : 'text-slate-500'}`}>
                {form.auto_eliminate_enabled ? 'Enabled — system eliminates automatically' : 'Disabled — manual elimination only'}
              </span>
            </div>
          </SelectRow>

          {/* Grace period enabled toggle */}
          <SelectRow label="Grace Period" hint="Allow members to pay late fee + seat-save fee during grace window to keep their pool position">
            <div className="flex items-center gap-3">
              <Toggle2 checked={!!form.grace_period_enabled} onChange={v => update('grace_period_enabled', v)} />
              <span className={`text-sm font-semibold ${form.grace_period_enabled ? 'text-emerald-600' : 'text-slate-500'}`}>
                {form.grace_period_enabled ? 'Enabled — grace period window active' : 'Disabled — no grace window (immediate elimination)'}
              </span>
            </div>
          </SelectRow>

        </div>
      </div>

      {/* Preview card */}
      <div className="bg-blue-50 border border-blue-200 rounded-2xl p-5 text-sm">
        <p className="font-bold text-blue-800 mb-3 flex items-center gap-2">
          <Info className="w-4 h-4" /> Timeline Preview (based on Sunday T+0 draw)
        </p>
        <div className="space-y-1.5 text-blue-700">
          <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-emerald-400 mt-1.5 flex-shrink-0" /><p><strong>Draw opens:</strong> Sunday T+0</p></div>
          <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
            <p><strong>Due date:</strong> Day {form.payment_due_days ?? 4} at {DUE_HOUR_OPTIONS.find(o => o.value === (form.payment_due_hour ?? 23))?.label ?? '11:00 PM'}</p>
          </div>
          <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-violet-400 mt-1.5 flex-shrink-0" />
            <p><strong>Grace window:</strong> {form.grace_period_hours ?? 48}h after due date (pay ₹{form.grace_seat_save_fee_inr ?? 500} + late fees)</p>
          </div>
          <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-red-400 mt-1.5 flex-shrink-0" />
            <p><strong>Elimination:</strong> Grace window ends → unpaid members removed (non-refundable)</p>
          </div>
          <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-blue-400 mt-1.5 flex-shrink-0" />
            <p><strong>Late fee accrual:</strong> ₹{feeMode === 'custom' ? customFee : (form.late_fee_per_day_inr ?? 50)}/day (max ₹{form.late_fee_max_cap_inr ?? 500})</p>
          </div>
        </div>
      </div>

      {/* Save section */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 space-y-4">
        <p className="text-sm font-bold text-slate-700 flex items-center gap-2">
          <Lock className="w-4 h-4 text-slate-400" />
          Admin Authorization Required
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            className="border border-slate-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
            placeholder="Enter admin password to save changes" />
          <button onClick={handleSave} disabled={saving || !password.trim()}
            className="flex items-center justify-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-white font-bold rounded-xl text-sm transition shadow-sm">
            {saving ? <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" /> : <Save className="w-4 h-4" />}
            Save Settings
          </button>
        </div>
        <p className="text-[11px] text-slate-400">⚠️ Settings take effect from the next penalty cycle. Members currently in grace period are not affected until the window closes.</p>
      </div>
    </div>
  )
}
