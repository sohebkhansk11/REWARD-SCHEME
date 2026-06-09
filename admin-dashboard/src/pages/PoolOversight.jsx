import { useState, useEffect, useCallback } from 'react'
import { ChevronDown, ChevronRight, Zap, RefreshCw, AlertCircle, Shield, AlertTriangle, UserX, Settings, PlusCircle, ToggleLeft, ToggleRight } from 'lucide-react'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import {
  getPools, getUsers, triggerDraw, applyDailyPenalty, eliminateUnpaid, BASE_URL,
  getPoolSettings, setAutoPoolCreation, manualCreatePool,
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

function PoolRow({ pool, members, onDraw }) {
  const [expanded, setExpanded] = useState(false)
  const [drawLoading, setDrawLoading] = useState(false)
  const [drawResult, setDrawResult] = useState(null)
  const toast = useToast()

  const canDraw = pool.status === 'Active' && members.length === 12

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
          <span className={`font-mono font-semibold ${members.length === 12 ? 'text-emerald-600' : 'text-amber-600'}`}>
            {members.length}/12
          </span>
        </td>
        <td className="px-5 py-4 text-right">
          <button
            onClick={handleDraw}
            disabled={!canDraw || drawLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed shadow-sm transition"
          >
            {drawLoading ? <Spinner className="w-3.5 h-3.5" /> : <Zap className="w-3.5 h-3.5" />}
            Trigger Draw
          </button>
        </td>
      </tr>

      {expanded && (
        <tr className="bg-slate-50/60 border-b border-slate-200">
          <td colSpan={4} className="px-5 pb-5 pt-2">
            {drawResult && <DrawResult result={drawResult} />}

            {members.length === 0 ? (
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

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    setError(null)
    try {
      const [poolsRes, usersRes] = await Promise.all([getPools(), getUsers()])
      setPools(poolsRes.data)
      setUsers(usersRes.data)
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
      const res = await getPoolSettings()
      setAutoPoolEnabled(res.data.auto_pool_creation_enabled)
    } catch { /* non-fatal — default to true (backend default) */ }
  }, [])

  useEffect(() => { fetchAll(); fetchPoolSettings() }, [fetchAll, fetchPoolSettings])

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
      toast(err.response?.data?.detail ?? 'Manual pool creation failed', 'error')
    } finally {
      setManualCreateLoading(false)
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

  const membersOf = poolId => users.filter(u => u.current_pool_id === poolId)

  const activePools = pools.filter(p => p.status === 'Active')
  const totalMembers = users.filter(u => u.status === 'Active').length

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

      {/* Stats strip */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total Pools', value: pools.length },
          { label: 'Active Pools', value: activePools.length },
          { label: 'Active Members', value: totalMembers },
        ].map(s => (
          <div key={s.label} className="bg-white rounded-xl px-5 py-4 shadow-sm border border-slate-100 flex items-center justify-between">
            <span className="text-sm text-slate-500">{s.label}</span>
            <span className="text-xl font-bold text-slate-800 tabular-nums">{s.value}</span>
          </div>
        ))}
      </div>

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
              </tr>
            </thead>
            <tbody>
              {pools.map(pool => (
                <PoolRow
                  key={pool.id}
                  pool={pool}
                  members={membersOf(pool.id)}
                  onDraw={() => fetchAll(true)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
