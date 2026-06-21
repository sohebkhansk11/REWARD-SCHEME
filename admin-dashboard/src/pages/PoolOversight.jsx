import { useState, useEffect, useCallback } from 'react'
import { ChevronDown, ChevronRight, Zap, RefreshCw, AlertCircle, Shield, AlertTriangle, UserX, Settings, PlusCircle, ToggleLeft, ToggleRight, Layers, BarChart2, GitMerge, X } from 'lucide-react'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import {
  getPools, getUsers, triggerDraw, applyDailyPenalty, eliminateUnpaid, BASE_URL,
  getPoolSettings, setAutoPoolCreation, manualCreatePool,
  fillPoolVacancies, syncPoolMemberCounts,
  getThreshold, updateThreshold,
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  getReconciliation, dissolvePool,
} from '../api/client'
import { useToast } from '../context/ToastContext'

// ── Inline toggle switch (fits the white-card admin theme) ──────────────────
function AutoSwitch({ checked, loading, onChange }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => !loading && onChange(!checked)}
      disabled={loading}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-not-allowed ${
        checked ? 'bg-indigo-600' : 'bg-slate-300'
      }`}
    >
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-md transition-transform duration-200 ${
        checked ? 'translate-x-6' : 'translate-x-1'
      }`} />
    </button>
  )
}

const LEVEL_COLOR = {
  1: 'bg-blue-100 text-blue-700',
  2: 'bg-blue-100 text-blue-700',
  3: 'bg-cyan-100 text-cyan-700',
  4: 'bg-amber-100 text-amber-700',
  5: 'bg-orange-100 text-orange-700',
  6: 'bg-rose-100 text-rose-700',
}

// ─── Module 4: 12-Seat Hex Grid ──────────────────────────────────────────────
const _hexPts = (cx, cy, r) =>
  Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i - Math.PI / 2
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`
  }).join(' ')

const _LEVEL_COLOR = {
  1: '#94a3b8', 2: '#06b6d4', 3: '#f97316',
  4: '#f43f5e', 5: '#f59e0b', 6: '#ef4444',
}

// Seat positions: 4-col × 3-row grid with alternating row offsets
const _HEX_SEATS = [
  {x:40, y:36}, {x:90, y:36}, {x:140, y:36}, {x:190, y:36},
  {x:65, y:79}, {x:115,y:79}, {x:165,y:79},  {x:215,y:79},
  {x:40, y:122},{x:90, y:122},{x:140,y:122},  {x:190,y:122},
]

function PoolHexGrid({ members }) {
  const [tip, setTip] = useState(null)
  const r = 21, ringR = 27

  return (
    <div>
      <svg viewBox="0 0 255 150" className="w-full" style={{ maxWidth: 340 }}>
        {_HEX_SEATS.map((pos, i) => {
          const m = members[i]
          if (!m) {
            return (
              <polygon key={i} points={_hexPts(pos.x, pos.y, r)}
                       fill="#f8fafc" stroke="#e2e8f0" strokeWidth="1.5"/>
            )
          }
          const lvl        = m.current_level ?? 1
          const hexColor   = _LEVEL_COLOR[lvl] ?? '#94a3b8'
          const isPaid     = m.weekly_payment_status === 'Paid'
          const isLate     = m.weekly_payment_status === 'Late'
          const ringColor  = isPaid ? '#10b981' : isLate ? '#f59e0b' : '#ef4444'
          const ringDash   = isLate ? '4 2' : undefined

          return (
            <g key={i} onMouseEnter={() => setTip({ m, pos })} onMouseLeave={() => setTip(null)}
               className="cursor-pointer">
              <circle cx={pos.x} cy={pos.y} r={ringR} fill="none"
                      stroke={ringColor} strokeWidth="2.5" strokeDasharray={ringDash}
                      opacity={isPaid ? 1 : 0.6}/>
              <polygon points={_hexPts(pos.x, pos.y, r)}
                       fill={hexColor} fillOpacity="0.15"
                       stroke={hexColor} strokeWidth="1.5"
                       className={lvl === 4 ? 'animate-pulse' : ''}/>
              <text x={pos.x} y={pos.y + 4} textAnchor="middle"
                    fontSize="9" fontWeight="800" fill={hexColor} fontFamily="ui-monospace,monospace">
                L{lvl}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Inline tooltip */}
      {tip && (
        <div className="text-xs bg-slate-800 text-white rounded-lg px-2.5 py-1.5 inline-block mt-1 ml-2">
          @{tip.m.username} · L{tip.m.current_level} ·{' '}
          <span className={tip.m.weekly_payment_status==='Paid' ? 'text-emerald-400' : 'text-amber-400'}>
            {tip.m.weekly_payment_status}
          </span>
          {Number(tip.m.late_fees_inr) > 0 &&
            <span className="text-amber-400 ml-1">₹{Number(tip.m.late_fees_inr).toLocaleString()} fee</span>}
        </div>
      )}

      <div className="flex items-center gap-3 mt-2 flex-wrap text-[9px] text-slate-400">
        <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-0.5 bg-emerald-400 rounded"/>Paid</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-0.5 bg-amber-400 rounded" style={{borderTop:'1px dashed #f59e0b'}}/>Late fee</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-0.5 bg-red-400 rounded opacity-60"/>Unpaid</span>
        {[1,2,3,4,5,6].map(l=>(
          <span key={l} className="flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full" style={{background:_LEVEL_COLOR[l]}}/>L{l}
          </span>
        ))}
      </div>
    </div>
  )
}

function DrawResult({ result }) {
  const INR = v => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)
  return (
    <div className="mt-4 border border-emerald-200 bg-emerald-50 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wider flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5" /> Draw Result — {result.pool_name}
        </p>
        {result.edge_case_used && (
          <span className="text-[10px] font-semibold bg-amber-100 text-amber-700 border border-amber-200 rounded-full px-2 py-0.5 uppercase tracking-wide">
            Early-pool mode (no L4+ members)
          </span>
        )}
      </div>
      {[result.winner_1, result.winner_2].map((w, i) => (
        <div key={i} className="bg-white rounded-lg p-3 flex flex-wrap items-center gap-x-6 gap-y-1.5 text-sm">
          <div>
            <span className="text-xs text-slate-400">
              Winner {i + 1} {result.edge_case_used ? `(L${w.winner_level} — fallback)` : i === 0 ? `(L${w.winner_level} low-tier)` : `(L${w.winner_level} high-tier)`}
            </span>
            <p className="font-semibold text-slate-800">@{w.winner_username}</p>
          </div>
          <div>
            <span className="text-xs text-slate-400">Net Payout</span>
            <p className="font-bold text-emerald-700">{INR(w.net_payout_inr)}</p>
          </div>
          <div>
            <span className="text-xs text-slate-400">Gross → Fee</span>
            <p className="text-slate-500 text-xs">{INR(w.gross_payout_inr)} − {INR(w.fee_inr)}</p>
          </div>
          <div>
            <span className="text-xs text-slate-400">Withdraw Code</span>
            <p className="font-mono font-semibold text-slate-800 tracking-widest">{w.withdraw_token_code}</p>
          </div>
          {w.replaced_by_username && (
            <div>
              <span className="text-xs text-slate-400">Replaced By</span>
              <p className="font-semibold text-slate-600">@{w.replaced_by_username}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function PoolRow({ pool, members, onDraw, onRequestDissolve }) {
  const [expanded,    setExpanded]   = useState(false)
  const [hexView,     setHexView]    = useState(false)
  const [drawLoading, setDrawLoading] = useState(false)
  const [drawResult,  setDrawResult]  = useState(null)
  const toast = useToast()

  const canDraw = pool.status === 'Active' && members.length === 12
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Manual dissolver only applies to LIVE pools (a dead pool cannot be dissolved).
  const canDissolve = pool.status !== 'Merged_Dissolved'

  const handleDraw = async e => {
    e.stopPropagation()
    if (!window.confirm(`Run Dual-Draw for ${pool.name}? This will randomly select 2 winners.`)) return
    setDrawLoading(true)
    setDrawResult(null)
    try {
      const res = await triggerDraw(pool.id)
      setDrawResult(res.data)
      toast(`Draw complete for ${pool.name}`, 'success')
      onDraw()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Draw failed', 'error')
    } finally {
      setDrawLoading(false)
    }
  }

  return (
    <>
      <tr
        className="border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-colors"
        onClick={() => setExpanded(e => !e)}
      >
        <td className="px-5 py-4">
          <div className="flex items-center gap-2">
            {expanded ? (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-slate-400" />
            )}
            <span className="font-bold text-slate-800">{pool.name}</span>
          </div>
        </td>
        <td className="px-5 py-4"><StatusBadge status={pool.status} /></td>
        <td className="px-5 py-4 text-center">
          <span className={`font-mono font-semibold tabular-nums ${
            members.length >= 12 ? 'text-emerald-600' :
            members.length >= 8  ? 'text-amber-600'  :
            'text-red-500'
          }`}>
            {members.length}/12
          </span>
        </td>
        <td className="px-5 py-4 text-right">
          <div className="flex items-center justify-end gap-2">
            <button
              onClick={handleDraw}
              disabled={!canDraw || drawLoading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed shadow-sm transition"
            >
              {drawLoading ? <Spinner className="w-3.5 h-3.5" /> : <Zap className="w-3.5 h-3.5" />}
              Trigger Draw
            </button>
            {/* SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                Manual donor↔receiver dissolver — relocates every member into other
                live pools (level/journey preserved), opens a password-confirm modal. */}
            <button
              onClick={e => { e.stopPropagation(); onRequestDissolve(pool, members.length) }}
              disabled={!canDissolve}
              title="Dissolve this pool — relocate every member into other live pools (no draw, no payout)"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 border border-rose-200 text-rose-700 hover:bg-rose-100 rounded-lg text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed shadow-sm transition"
            >
              <GitMerge className="w-3.5 h-3.5" />
              Dissolve
            </button>
          </div>
        </td>

        {/* ── SDE / Brain5 metadata ───────────────────────── */}
        <td className="px-5 py-4 text-center">
          {pool.pool_draw_type ? (
            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-violet-50 text-violet-700 border border-violet-200">
              {pool.pool_draw_type}
            </span>
          ) : <span className="text-slate-300 text-xs">—</span>}
        </td>
        <td className="px-5 py-4 text-center">
          {pool.contains_flagged_l4
            ? <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-700 border border-red-200"><AlertTriangle className="w-3 h-3" />L4</span>
            : <span className="text-slate-300 text-xs">—</span>
          }
        </td>
        <td className="px-5 py-4 text-center">
          {pool.draw_completed_this_week
            ? <Shield className="w-4 h-4 text-emerald-500 mx-auto" />
            : <span className="text-slate-300 text-xs">—</span>
          }
        </td>
      </tr>

      {expanded && (
        <tr className="bg-slate-50/60 border-b border-slate-200">
          <td colSpan={7} className="px-5 pb-5 pt-2">
            {drawResult && <DrawResult result={drawResult} />}

            {/* View toggle */}
            {members.length > 0 && (
              <div className="flex items-center gap-2 mt-3 mb-2">
                <button
                  onClick={() => setHexView(false)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${!hexView ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}
                >
                  ☰ Table
                </button>
                <button
                  onClick={() => setHexView(true)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${hexView ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}
                >
                  ⬡ Hex Grid
                </button>
                <span className="text-[10px] text-slate-400 ml-1">
                  {members.filter(m=>m.weekly_payment_status==='Paid').length}/{members.length} paid
                </span>
              </div>
            )}

            {hexView && members.length > 0 ? (
              <PoolHexGrid members={members} />
            ) : members.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">No members in this pool</p>
            ) : (
              <table className="w-full text-sm mt-3 bg-white rounded-xl overflow-hidden shadow-sm border border-slate-100">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-100">
                    {['#', 'Name', 'Username', 'Level', 'Weekly Payment', 'Late Fees', 'Status'].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {members.map((m, idx) => (
                    <tr key={m.id} className="border-b border-slate-50 last:border-0">
                      <td className="px-4 py-2.5 text-slate-400 font-mono text-xs">{idx + 1}</td>
                      <td className="px-4 py-2.5 font-medium text-slate-800">{m.name}</td>
                      <td className="px-4 py-2.5 text-slate-500 font-mono text-xs">@{m.username}</td>
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${LEVEL_COLOR[m.current_level] ?? 'bg-slate-100 text-slate-600'}`}>
                          {m.current_level}
                        </span>
                      </td>
                      <td className="px-4 py-2.5"><StatusBadge status={m.weekly_payment_status} /></td>
                      <td className="px-4 py-2.5">
                        {Number(m.late_fees_inr) > 0
                          ? <span className="text-xs font-semibold text-red-600">−₹{Number(m.late_fees_inr).toLocaleString('en-IN')}</span>
                          : <span className="text-xs text-slate-300">—</span>}
                      </td>
                      <td className="px-4 py-2.5"><StatusBadge status={m.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export default function PoolOversight() {
  const toast = useToast()
  const [pools, setPools] = useState([])
  const [users, setUsers] = useState([])
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // SSOT reconciliation payload (single source of truth for every headline).
  const [recon, setRecon] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [penaltyLoading, setPenaltyLoading] = useState(false)
  const [eliminateLoading, setEliminateLoading] = useState(false)

  // ── Pool creation settings ────────────────────────────────────────────────
  const [autoPoolEnabled,       setAutoPoolEnabled]       = useState(null)   // null = loading
  const [poolSettingsLoading,   setPoolSettingsLoading]   = useState(false)
  const [manualCreateLoading,   setManualCreateLoading]   = useState(false)
  const [manualCreateResult,    setManualCreateResult]    = useState(null)

  // ── Maintenance actions ───────────────────────────────────────────────────
  const [fillVacanciesLoading,  setFillVacanciesLoading]  = useState(false)
  const [fillVacanciesResult,   setFillVacanciesResult]   = useState(null)
  const [syncCountsLoading,     setSyncCountsLoading]     = useState(false)
  const [syncCountsResult,      setSyncCountsResult]      = useState(null)

  // ── Configurable threshold ────────────────────────────────────────────────
  const [threshold,         setThreshold]         = useState(null)   // current value from API
  const [thresholdInput,    setThresholdInput]    = useState('')      // controlled input
  const [thresholdPassword, setThresholdPassword] = useState('')
  const [thresholdLoading,  setThresholdLoading]  = useState(false)

  // ── Manual pool dissolver (Point 5 — donor↔receiver merger) ───────────────
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  const [dissolveTarget,   setDissolveTarget]   = useState(null)   // {pool, memberCount} | null
  const [dissolvePassword, setDissolvePassword] = useState('')
  const [dissolveLoading,  setDissolveLoading]  = useState(false)

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    setError(null)
    try {
      // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
      // SSOT WIRING (A3).  Headline counts now come from the authoritative
      // server-computed /admin/stats/reconciliation payload — never derived
      // client-side from a truncated /users/ page.  The member fetch is widened
      // to 5000 so per-pool expansions show EVERY Active member (the old 500-row
      // unordered page dropped Active members past row 500 → "where gone 577?").
      // getReconciliation is DEFENSIVE: if the endpoint is missing/old (404) the
      // UI silently falls back to the legacy client-derived counts.
      const [poolsRes, usersRes, reconRes] = await Promise.all([
        getPools(),
        getUsers({ limit: 5000 }),
        getReconciliation().catch(() => null),
      ])
      setPools(poolsRes.data)
      setUsers(usersRes.data)
      setRecon(reconRes?.data ?? null)
    } catch (err) {
      const msg = err.code === 'ERR_NETWORK'
        ? `Cannot reach API at ${BASE_URL}`
        : err.response?.data?.detail ?? 'Failed to load pool data'
      setError(msg)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  // ── Pool settings fetch ───────────────────────────────────────────────────
  const fetchPoolSettings = useCallback(async () => {
    try {
      const [toggleRes, threshRes] = await Promise.all([getPoolSettings(), getThreshold()])
      setAutoPoolEnabled(toggleRes.data.auto_pool_creation_enabled)
      setThreshold(threshRes.data.pool_creation_threshold)
      setThresholdInput(String(threshRes.data.pool_creation_threshold))
    } catch { /* non-fatal — defaults apply */ }
  }, [])

  useEffect(() => { fetchAll(); fetchPoolSettings() }, [fetchAll, fetchPoolSettings])

  // Auto-refresh every 30 s (silent)
  useEffect(() => {
    const id = setInterval(() => fetchAll(true), 30_000)
    return () => clearInterval(id)
  }, [fetchAll])

  // ── Toggle auto pool creation ─────────────────────────────────────────────
  const handleToggleAutoPool = async (newValue) => {
    setPoolSettingsLoading(true)
    try {
      const res = await setAutoPoolCreation(newValue)
      setAutoPoolEnabled(res.data.auto_pool_creation_enabled)
      toast(res.data.message, 'success')
      if (newValue) fetchAll(true)   // refresh pool list if re-enabled (may have created a pool)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to update pool settings', 'error')
    } finally {
      setPoolSettingsLoading(false)
    }
  }

  // ── Manual pool creation ──────────────────────────────────────────────────
  const handleManualCreatePool = async () => {
    if (!window.confirm('Force-create a new Active pool from the oldest paid Waitlist members? This bypasses the 24-member threshold.')) return
    setManualCreateLoading(true)
    setManualCreateResult(null)
    try {
      const res = await manualCreatePool()
      setManualCreateResult(res.data)
      toast(`Pool '${res.data.pool_name}' created with ${res.data.members_assigned} members`, 'success')
      fetchAll(true)
    } catch (err) {
      if (err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')) {
        toast('Server is processing heavy load. Please wait or refresh.', 'error')
      } else {
        toast(err.response?.data?.detail ?? 'Manual pool creation failed', 'error')
      }
    } finally {
      setManualCreateLoading(false)
    }
  }

  // ── Fill pool vacancies (FIFO from waitlist) ─────────────────────────────
  const handleFillVacancies = async () => {
    setFillVacanciesLoading(true)
    setFillVacanciesResult(null)
    try {
      const res = await fillPoolVacancies()
      setFillVacanciesResult(res.data)
      const msg = res.data.message ?? 'Vacancy fill complete'
      toast(msg, 'success')
      fetchAll(true)
    } catch (err) {
      if (err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')) {
        toast('Server is processing heavy load. Please wait or refresh.', 'error')
      } else {
        toast(err.response?.data?.detail ?? 'Vacancy fill failed', 'error')
      }
    } finally {
      setFillVacanciesLoading(false)
    }
  }

  // ── Sync stale pool.total_members ─────────────────────────────────────────
  const handleSyncCounts = async () => {
    setSyncCountsLoading(true)
    setSyncCountsResult(null)
    try {
      const res = await syncPoolMemberCounts()
      setSyncCountsResult(res.data)
      toast(res.data.message, res.data.synced_count > 0 ? 'success' : 'info')
      fetchAll(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Sync failed', 'error')
    } finally {
      setSyncCountsLoading(false)
    }
  }

  // ── Update pool-creation threshold ───────────────────────────────────────
  const handleUpdateThreshold = async () => {
    const val = parseInt(thresholdInput, 10)
    if (isNaN(val) || val < 1 || val > 1000) {
      toast('Threshold must be a whole number between 1 and 1000', 'error')
      return
    }
    if (!thresholdPassword.trim()) {
      toast('Admin password is required', 'error')
      return
    }
    setThresholdLoading(true)
    try {
      const res = await updateThreshold(val, thresholdPassword)
      setThreshold(res.data.pool_creation_threshold)
      setThresholdPassword('')
      toast(res.data.message, 'success')
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to update threshold', 'error')
    } finally {
      setThresholdLoading(false)
    }
  }

  const handleApplyPenalty = async () => {
    if (!window.confirm('Apply ₹50 late fee to all unpaid active members?')) return
    setPenaltyLoading(true)
    try {
      const res = await applyDailyPenalty()
      toast(res.data.message, 'success')
      fetchAll(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to apply penalty', 'error')
    } finally {
      setPenaltyLoading(false)
    }
  }

  const handleEliminateUnpaid = async () => {
    if (!window.confirm('ELIMINATE all currently unpaid active members? This is irreversible.')) return
    setEliminateLoading(true)
    try {
      const res = await eliminateUnpaid()
      toast(res.data.message, res.data.eliminated_count > 0 ? 'success' : 'info')
      fetchAll(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Elimination failed', 'error')
    } finally {
      setEliminateLoading(false)
    }
  }

  // ── Manual pool dissolver (Point 5) ───────────────────────────────────────
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  const openDissolve = (pool, memberCount) => {
    setDissolvePassword('')
    setDissolveTarget({ pool, memberCount })
  }
  const closeDissolve = () => {
    if (dissolveLoading) return
    setDissolveTarget(null)
    setDissolvePassword('')
  }
  const handleConfirmDissolve = async () => {
    if (!dissolveTarget) return
    if (!dissolvePassword.trim()) {
      toast('Admin password is required to dissolve a pool', 'error')
      return
    }
    setDissolveLoading(true)
    try {
      const res = await dissolvePool(dissolveTarget.pool.id, dissolvePassword)
      toast(res.data.note ?? `Pool '${dissolveTarget.pool.name}' dissolved`, 'success')
      // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
      // Task 2: the dissolve is now routed through the virtual integrity gate.
      // Surface the resulting verdict defensively (field is optional on older API):
      // on a HOLD the admin is told to review the Pool Re-assessment panel.
      const ra = res.data.reassessment
      if (ra && ra.is_active_hold) {
        toast(
          `Re-assessment HOLD after dissolve (report #${ra.report_id}) — review the `
          + `Pool Re-assessment panel before the next draw.`,
          'error',
        )
      } else if (ra && ra.verdict === 'PASS') {
        toast('Re-assessment PASS — new pool structure verified.', 'info')
      }
      setDissolveTarget(null)
      setDissolvePassword('')
      fetchAll(true)
    } catch (err) {
      if (err.code === 'ECONNABORTED' || err.message?.toLowerCase().includes('timeout')) {
        toast('Server is processing heavy load. Please wait or refresh.', 'error')
      } else {
        toast(err.response?.data?.detail ?? 'Pool dissolve failed', 'error')
      }
    } finally {
      setDissolveLoading(false)
    }
  }

  const membersOf = poolId => users.filter(u => u.current_pool_id === poolId)

  const activePools = pools.filter(p => p.status === 'Active')

  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // SSOT-PREFERRED headline values with defensive client fallback.  When the
  // reconciliation endpoint is live every card reads ONE authoritative number;
  // if it is missing the legacy client-derived value is used so the page never
  // breaks.  "Live Pools" excludes Merged_Dissolved (dead pools are not pools).
  const clientActiveMembers = users.filter(u => u.status === 'Active').length
  const clientLivePools     = pools.filter(p => p.status !== 'Merged_Dissolved').length
  const totalMembers   = recon?.users?.active   ?? clientActiveMembers
  const livePoolsVal   = recon?.pools?.live     ?? clientLivePools
  const activePoolsVal = recon?.pools?.active   ?? activePools.length
  const dissolvedVal   = recon?.pools?.dissolved
  const integrity      = recon?.integrity ?? null

  if (loading) {
    return <div className="flex items-center justify-center h-full"><Spinner className="w-8 h-8" /></div>
  }

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Pool Oversight</h1>
          <p className="text-sm text-slate-400 mt-0.5">Monitor pool members and trigger draws</p>
        </div>
        <button
          onClick={() => fetchAll(true)}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Stats strip — SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 /
          Sohebkhan.sk11]: values now sourced from the SSOT reconciliation
          endpoint (server-authoritative, no client truncation). */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Live Pools', value: livePoolsVal,
            sub: dissolvedVal != null ? `${dissolvedVal} dissolved (excluded)` : null },
          { label: 'Active Pools', value: activePoolsVal },
          { label: 'Active Members', value: totalMembers,
            sub: recon ? 'server-verified' : 'client estimate' },
        ].map(s => (
          <div key={s.label} className="bg-white rounded-xl px-5 py-4 shadow-sm border border-slate-100 flex items-center justify-between">
            <div className="flex flex-col">
              <span className="text-sm text-slate-500">{s.label}</span>
              {s.sub && <span className="text-[10px] text-slate-400 mt-0.5">{s.sub}</span>}
            </div>
            <span className="text-xl font-bold text-slate-800 tabular-nums">{s.value}</span>
          </div>
        ))}
      </div>

      {/* SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
          SSOT integrity health strip — makes data-trustworthiness visible.  Green
          when every reconciliation identity holds; amber with a breakdown when a
          leak/staleness is detected (the 6-hourly integrity job auto-heals it). */}
      {integrity && (
        integrity.ok ? (
          <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-2.5 text-sm text-emerald-700">
            <Shield className="w-4 h-4 flex-shrink-0" />
            <span className="font-medium">Data reconciled</span>
            <span className="text-emerald-600/80 text-xs">
              every Active member sits in a live pool · pool counters match live counts · no orphans
            </span>
          </div>
        ) : (
          <div className="flex items-start gap-3 bg-amber-50 border-2 border-amber-300 rounded-xl p-4 text-sm">
            <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-amber-800">⚠ Reconciliation drift detected</p>
              <p className="text-xs text-amber-700 mt-0.5 leading-relaxed">
                {integrity.orphans_total > 0 && <span className="mr-3">Orphaned Active members: <b>{integrity.orphans_total}</b></span>}
                {integrity.stale_pool_counters > 0 && <span className="mr-3">Stale pool counters: <b>{integrity.stale_pool_counters}</b></span>}
                {integrity.dissolved_with_members > 0 && <span className="mr-3">Dissolved pools holding members: <b>{integrity.dissolved_with_members}</b></span>}
                <br />The 6-hourly integrity job re-homes orphans and resyncs counters automatically; run “Sync Member Counts” below to repair now.
              </p>
            </div>
          </div>
        )
      )}

      {/* ── Type B Danger Banner ─────────────────────────────────────────────── */}
      {pools.filter(p => p.pool_draw_type === 'type_b' && (p.status ?? p.pool_status) === 'Active').length >= 1 && (
        <div className="flex items-start gap-3 bg-amber-50 border-2 border-amber-300 rounded-xl p-4">
          <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-bold text-amber-800 text-sm">
              ⚠ Type B Fallback Draw Active
              <span className="ml-2 font-normal text-xs text-amber-700">
                ({pools.filter(p => p.pool_draw_type === 'type_b' && (p.status ?? p.pool_status) === 'Active').length} pool{pools.filter(p => p.pool_draw_type === 'type_b' && (p.status ?? p.pool_status) === 'Active').length !== 1 ? 's' : ''})
              </span>
            </p>
            <p className="text-xs text-amber-700 mt-0.5 leading-relaxed">
              Type B indicates L1/L2 member shortage — L3/L4 filling both winner slots.
              Anti-Maturity Protocol risk if this persists across consecutive weeks.
              Increase waitlist injection or run Fill Vacancies below.
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />{error}
        </div>
      )}

      {/* ── Pool Creation Settings ────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Settings className="w-4 h-4 text-indigo-500" />
            <h2 className="font-semibold text-slate-800">Pool Creation Settings</h2>
          </div>
          {poolSettingsLoading && <Spinner className="w-4 h-4 text-indigo-400" />}
        </div>

        {/* Auto-creation toggle row */}
        <div className="flex items-center justify-between gap-4 p-4 rounded-xl bg-slate-50 border border-slate-100">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              {autoPoolEnabled
                ? <ToggleRight className="w-4 h-4 text-indigo-500 flex-shrink-0" />
                : <ToggleLeft  className="w-4 h-4 text-slate-400 flex-shrink-0" />
              }
              <p className="font-semibold text-sm text-slate-800">
                Auto AI Pool Creation&nbsp;
                {autoPoolEnabled === null
                  ? <span className="text-xs font-normal text-slate-400">(loading…)</span>
                  : autoPoolEnabled
                    ? <span className="text-xs font-normal text-emerald-600">— ON</span>
                    : <span className="text-xs font-normal text-slate-500">— OFF</span>
                }
              </p>
            </div>
            <p className="text-xs text-slate-400 mt-0.5 pl-6">
              When <strong>ON</strong>, a new pool of 12 forms automatically whenever 24+ paid Waitlist members
              accumulate. When <strong>OFF</strong>, only manual pool creation works.
            </p>
          </div>
          <AutoSwitch
            checked={autoPoolEnabled ?? true}
            loading={poolSettingsLoading || autoPoolEnabled === null}
            onChange={handleToggleAutoPool}
          />
        </div>

        {/* Manual create row */}
        <div className="flex items-start gap-4 pt-1">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-700">Manually Create New Pool</p>
            <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
              Force-creates a pool immediately from the oldest paid Waitlist members, bypassing the
              24-member threshold and the toggle above. Requires at least 12 paid Waitlist members.
              Also runs FIFO vacancy fill across all existing pools.
            </p>
          </div>
          <button
            onClick={handleManualCreatePool}
            disabled={manualCreateLoading}
            className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-colors"
          >
            {manualCreateLoading
              ? <><Spinner className="w-4 h-4" />Creating…</>
              : <><PlusCircle className="w-4 h-4" />Manually Create Pool</>
            }
          </button>
        </div>

        {/* Manual create success result */}
        {manualCreateResult && (
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-sm space-y-1">
            <p className="font-semibold text-emerald-700 flex items-center gap-1.5">
              <PlusCircle className="w-4 h-4" />
              Pool <span className="font-mono">{manualCreateResult.pool_name}</span> created
              with {manualCreateResult.members_assigned} member{manualCreateResult.members_assigned !== 1 ? 's' : ''}
            </p>
            {manualCreateResult.fifo_filled_other_pools > 0 && (
              <p className="text-xs text-emerald-600">
                Also FIFO-filled {manualCreateResult.fifo_filled_other_pools} vacancy slot{manualCreateResult.fifo_filled_other_pools !== 1 ? 's' : ''} in other existing pools.
              </p>
            )}
          </div>
        )}

        {/* Configurable threshold */}
        <div className="border-t border-slate-100 pt-5 space-y-3">
          <div>
            <p className="text-sm font-semibold text-slate-700">
              Auto-Pool Trigger Threshold
              {threshold !== null && (
                <span className="ml-2 text-xs font-normal text-indigo-600 bg-indigo-50 border border-indigo-100 rounded-full px-2 py-0.5">
                  current: {threshold} members
                </span>
              )}
            </p>
            <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
              When Auto AI Pool Creation is <strong>ON</strong>, a new pool forms once this many
              paid Waitlist members accumulate. Default is 24. Requires admin password.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[80px] max-w-[140px]">
              <label className="block text-xs font-medium text-slate-500 mb-1">New threshold</label>
              <input
                type="number"
                min="1"
                max="1000"
                value={thresholdInput}
                onChange={e => setThresholdInput(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-300"
                placeholder="24"
              />
            </div>
            <div className="flex-1 min-w-[160px]">
              <label className="block text-xs font-medium text-slate-500 mb-1">Admin password</label>
              <input
                type="password"
                value={thresholdPassword}
                onChange={e => setThresholdPassword(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
                placeholder="Your admin password"
                autoComplete="current-password"
              />
            </div>
            <button
              onClick={handleUpdateThreshold}
              disabled={thresholdLoading}
              className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-colors"
            >
              {thresholdLoading
                ? <><Spinner className="w-4 h-4" />Saving…</>
                : 'Save Threshold'
              }
            </button>
          </div>
        </div>
      </div>

      {/* ── Maintenance Actions ─────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 space-y-5">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-sky-500" />
          <h2 className="font-semibold text-slate-800">Pool Maintenance</h2>
        </div>

        {/* Fill vacancies row */}
        <div className="flex items-start gap-4 p-4 rounded-xl bg-slate-50 border border-slate-100">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-700">Fill Pool Vacancies (FIFO)</p>
            <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
              Assigns the oldest paid Waitlist members into any active pools that have fewer than
              12 members. Fixes under-capacity pools caused by eliminations or manual changes.
              Run this whenever Pool Oversight shows member counts below 12.
            </p>
            {fillVacanciesResult && (
              <p className="mt-2 text-xs font-medium text-sky-700">
                {fillVacanciesResult.message}
                {fillVacanciesResult.pool_created && (
                  <span className="ml-1 text-emerald-600">
                    — also created pool <span className="font-mono">{fillVacanciesResult.pool_created.name}</span>
                  </span>
                )}
              </p>
            )}
          </div>
          <button
            onClick={handleFillVacancies}
            disabled={fillVacanciesLoading}
            className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2.5 bg-sky-600 hover:bg-sky-700 text-white rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-colors"
          >
            {fillVacanciesLoading
              ? <><Spinner className="w-4 h-4" />Filling…</>
              : <><Layers className="w-4 h-4" />Fill Vacancies</>
            }
          </button>
        </div>

        {/* Sync member counts row */}
        <div className="flex items-start gap-4 p-4 rounded-xl bg-slate-50 border border-slate-100">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-700">Sync Member Count Cache</p>
            <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
              Recalculates and corrects <span className="font-mono">pool.total_members</span> for
              every pool based on the actual active user count. Fixes the Dashboard showing
              stale values like "12/12" when a pool actually has fewer members.
            </p>
            {syncCountsResult && (
              <p className="mt-2 text-xs font-medium text-slate-600">
                {syncCountsResult.message}
              </p>
            )}
            {syncCountsResult?.changes?.length > 0 && (
              <ul className="mt-1.5 space-y-0.5">
                {syncCountsResult.changes.map(c => (
                  <li key={c.pool_id} className="text-xs text-slate-500 font-mono">
                    {c.pool_name}: {c.was} → <span className="text-emerald-600 font-semibold">{c.now}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            onClick={handleSyncCounts}
            disabled={syncCountsLoading}
            className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2.5 bg-slate-700 hover:bg-slate-800 text-white rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-colors"
          >
            {syncCountsLoading
              ? <><Spinner className="w-4 h-4" />Syncing…</>
              : <><BarChart2 className="w-4 h-4" />Sync Counts</>
            }
          </button>
        </div>
      </div>

      {/* Penalty Actions */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 space-y-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-500" />
          <h2 className="font-semibold text-slate-800">Penalty Controls</h2>
        </div>
        <p className="text-xs text-slate-400">
          Run <strong>Apply Daily Penalty</strong> Monday–Saturday to accrue ₹50/day on unpaid members.
          Run <strong>Eliminate Unpaid</strong> on Sunday before the draw to forfeit delinquent slots.
        </p>
        <div className="flex gap-3 flex-wrap">
          <button
            onClick={handleApplyPenalty}
            disabled={penaltyLoading}
            className="inline-flex items-center gap-2 px-4 py-2 bg-amber-50 border border-amber-200 text-amber-700 hover:bg-amber-100 rounded-xl text-sm font-semibold disabled:opacity-50 transition"
          >
            {penaltyLoading ? <Spinner className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
            Apply ₹50 Daily Penalty
          </button>
          <button
            onClick={handleEliminateUnpaid}
            disabled={eliminateLoading}
            className="inline-flex items-center gap-2 px-4 py-2 bg-red-50 border border-red-200 text-red-700 hover:bg-red-100 rounded-xl text-sm font-semibold disabled:opacity-50 transition"
          >
            {eliminateLoading ? <Spinner className="w-4 h-4" /> : <UserX className="w-4 h-4" />}
            Eliminate Unpaid Members
          </button>
        </div>
      </div>

      {/* Pools table */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
          <Shield className="w-4 h-4 text-slate-400" />
          <h2 className="font-semibold text-slate-800">All Pools</h2>
          <span className="ml-auto text-xs text-slate-400">Click a row to see members</span>
        </div>

        {pools.length === 0 ? (
          <div className="py-16 text-center text-slate-400 text-sm">
            No pools exist yet — trigger a waitlist check from the Dashboard to create the first pool.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Pool</th>
                <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                <th className="text-center px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Members</th>
                <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Action</th>
                <th className="text-center px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Draw Type</th>
                <th className="text-center px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">L4 Flag</th>
                <th className="text-center px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Week Done</th>
              </tr>
            </thead>
            <tbody>
              {pools.map(pool => (
                <PoolRow
                  key={pool.id}
                  pool={pool}
                  members={membersOf(pool.id)}
                  onDraw={() => fetchAll(true)}
                  onRequestDissolve={openDissolve}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Manual Pool Dissolver modal (Point 5 — donor↔receiver merger) ─────
          SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
          Password-gated confirm.  Spells out exactly what happens (relocate, no
          draw, no payout, full level preservation) before the irreversible move. */}
      {dissolveTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4"
          onClick={closeDissolve}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-md p-6 space-y-4"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                <div className="w-9 h-9 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center">
                  <GitMerge className="w-5 h-5 text-rose-600" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-900">Dissolve {dissolveTarget.pool.name}</h3>
                  <p className="text-xs text-slate-400">Donor → receiver merger</p>
                </div>
              </div>
              <button
                onClick={closeDissolve}
                disabled={dissolveLoading}
                className="text-slate-400 hover:text-slate-600 disabled:opacity-40"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="bg-slate-50 border border-slate-100 rounded-xl p-3.5 text-xs text-slate-600 leading-relaxed space-y-1.5">
              <p>
                All <b className="text-slate-800">{dissolveTarget.memberCount}</b> active member
                {dissolveTarget.memberCount !== 1 ? 's' : ''} will be <b>relocated</b> into other live pools,
                filling oldest under-capacity pools first (new pools are created only if needed).
              </p>
              <p className="flex items-start gap-1.5 text-emerald-700">
                <Shield className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                <span>Every member <b>keeps their level, weekly-payment status and journey</b>.
                  This runs <b>no draw</b>, pays <b>nobody</b>, and sends <b>nobody</b> back to the waitlist.</span>
              </p>
              <p className="text-slate-400">
                The pool is then marked <span className="font-mono">Merged_Dissolved</span>. This cannot be undone.
              </p>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Admin password</label>
              <input
                type="password"
                value={dissolvePassword}
                onChange={e => setDissolvePassword(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !dissolveLoading) handleConfirmDissolve() }}
                disabled={dissolveLoading}
                autoFocus
                autoComplete="current-password"
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-300 disabled:opacity-50"
                placeholder="Required to authorise dissolution"
              />
            </div>

            <div className="flex gap-3 pt-1">
              <button
                onClick={closeDissolve}
                disabled={dissolveLoading}
                className="flex-1 px-4 py-2.5 bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 rounded-xl text-sm font-semibold disabled:opacity-50 transition"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDissolve}
                disabled={dissolveLoading || !dissolvePassword.trim()}
                className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-rose-600 hover:bg-rose-700 text-white rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition"
              >
                {dissolveLoading
                  ? <><Spinner className="w-4 h-4" />Dissolving…</>
                  : <><GitMerge className="w-4 h-4" />Dissolve Pool</>
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
