import { useState, useEffect, useCallback } from 'react'
import { Trophy, ChevronLeft, ChevronRight, RefreshCw, Filter } from 'lucide-react'
import { getWinnersHistory } from '../api/client'
import { useToast } from '../context/ToastContext'

// ── Level badge colours ────────────────────────────────────────────────────────
const LEVEL_COLORS = {
  1: 'bg-slate-700 text-slate-300',
  2: 'bg-blue-900/60 text-blue-300',
  3: 'bg-violet-900/60 text-violet-300',
  4: 'bg-amber-900/60 text-amber-300',
  5: 'bg-orange-900/60 text-orange-300',
  6: 'bg-emerald-900/60 text-emerald-300',
}

// ── Journey badge ──────────────────────────────────────────────────────────────
function JourneyBadge({ type }) {
  if (type === 'merged') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-violet-900/60 text-violet-300 border border-violet-700/40">
        Dynamic Merge
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-emerald-900/60 text-emerald-300 border border-emerald-700/40">
      Direct
    </span>
  )
}

// ── Draw type badge ────────────────────────────────────────────────────────────
function DrawTypeBadge({ drawType }) {
  const isSde = drawType && String(drawType).toLowerCase().includes('sde')
  return isSde ? (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-rose-900/60 text-rose-300 border border-rose-700/40">
      SDE Exit
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-blue-900/60 text-blue-300 border border-blue-700/40">
      Regular
    </span>
  )
}

// ── SDE targeted-exit badge ───────────────────────────────────────────────────
function SdeTargetBadge({ targeted }) {
  if (!targeted) return <span className="text-slate-600 text-xs">—</span>
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-amber-900/60 text-amber-300 border border-amber-700/40">
      Targeted
    </span>
  )
}

// ── Referral badge ─────────────────────────────────────────────────────────────
function ReferralBadge({ isReferred }) {
  if (isReferred) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-amber-900/60 text-amber-300 border border-amber-700/40">
        Referral
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-slate-700/60 text-slate-400 border border-slate-600/40">
      Organic
    </span>
  )
}

// ─── Module 5: Winner's Autopsy Modal ────────────────────────────────────────
// Slide-over modal showing a reconstructed lifecycle timeline for a winner.
function WinnerAutopsyModal({ winner, onClose }) {
  if (!winner) return null

  const lvl      = winner.level_won ?? 1
  const isSde    = (winner.draw_type ?? '').toLowerCase().includes('sde') || winner.targeted_early_exit
  const isMerged = winner.journey_type === 'merged'
  const isRef    = winner.is_referred ?? false
  const exitDate = winner.draw_timestamp
    ? new Date(winner.draw_timestamp).toLocaleDateString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
    : '—'

  const netProfit = (winner.net_payout_inr ?? 0) - (winner.total_deposited_inr ?? 0)

  // Reconstruct journey events from available fields
  const events = [
    {
      icon: '👤', color: 'blue',
      title: 'Joined the System',
      detail: isRef ? 'Via referral — organic member recruitment' : 'Direct registration',
    },
    {
      icon: '⏳', color: 'slate',
      title: 'Entered Layer 3 (Waitlist)',
      detail: 'Awaiting DEP token burn & pool capacity check',
    },
    {
      icon: isMerged ? '🔀' : '🏊', color: isMerged ? 'violet' : 'blue',
      title: isMerged
        ? `Dynamic Merge → ${winner.pool_name ?? `Pool #${winner.pool_id}`}`
        : `Injected into ${winner.pool_name ?? `Pool #${winner.pool_id}`}`,
      detail: isMerged
        ? 'Brain 4 condensation — old pool dissolved, members redistributed'
        : 'FIFO assignment from Layer 2 reserve buffer',
    },
    // Level milestones (synthetic, estimated)
    ...Array.from({ length: lvl - 1 }, (_, i) => ({
      icon: '⬆️', color: 'violet',
      title: `Advanced to Level ${i + 2}`,
      detail: `Survived weekly draw at L${i + 1} — moved up the member ladder`,
    })),
    // SDE targeting (if applicable)
    ...(isSde ? [{
      icon: '🎯', color: 'rose',
      title: 'Flagged by Brain 5 — SDE Protocol',
      detail: 'L4 threshold breached — member queued for guaranteed elimination at next draw',
    }] : []),
    // Final win
    {
      icon: '🏆', color: 'amber',
      title: `Won Draw at Level ${lvl} — ELIMINATED`,
      detail: `Gross ₹${Number(winner.gross_payout_inr ?? 0).toLocaleString('en-IN')} → Fee ₹${Number((winner.gross_payout_inr ?? 0) - (winner.net_payout_inr ?? 0)).toLocaleString('en-IN')} → Net ₹${Number(winner.net_payout_inr ?? 0).toLocaleString('en-IN')}`,
      date: exitDate,
    },
  ]

  const COLORS = {
    blue:   { dot: 'bg-blue-500',    card: 'bg-blue-950/30 border-blue-700/40 text-blue-300' },
    slate:  { dot: 'bg-slate-600',   card: 'bg-slate-800 border-slate-600/40 text-slate-400' },
    violet: { dot: 'bg-violet-500',  card: 'bg-violet-950/30 border-violet-700/40 text-violet-300' },
    rose:   { dot: 'bg-rose-500',    card: 'bg-rose-950/30 border-rose-700/40 text-rose-300' },
    amber:  { dot: 'bg-amber-500',   card: 'bg-amber-950/30 border-amber-700/40 text-amber-300' },
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm"/>

      <div
        className="relative w-full max-w-lg h-full bg-slate-950 border-l border-slate-700/60 shadow-2xl flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex-shrink-0 border-b border-slate-700/60 px-5 py-4 flex items-start justify-between bg-slate-900">
          <div>
            <p className="font-black text-white text-base flex items-center gap-2">
              <Trophy className="w-4 h-4 text-amber-400"/>Winner Autopsy
            </p>
            <p className="text-xs text-slate-400 mt-0.5 font-mono">
              @{winner.user_name ?? winner.username ?? '—'}
            </p>
          </div>
          <button onClick={onClose}
                  className="text-slate-500 hover:text-white transition text-lg leading-none mt-0.5">✕</button>
        </div>

        {/* Key metrics */}
        <div className="flex-shrink-0 px-5 py-4 grid grid-cols-3 gap-2 border-b border-slate-800">
          {[
            { l: 'Level Won',  v: `L${lvl}`,                                         c: 'text-amber-400' },
            { l: 'Net Payout', v: `₹${Number(winner.net_payout_inr ?? 0).toLocaleString('en-IN')}`,  c: 'text-emerald-400' },
            { l: 'Net Profit', v: (netProfit >= 0 ? '+' : '') + `₹${netProfit.toLocaleString('en-IN')}`, c: netProfit >= 0 ? 'text-emerald-400' : 'text-red-400' },
            { l: 'Pool',       v: winner.pool_name ?? `#${winner.pool_id ?? '?'}`,   c: 'text-slate-300' },
            { l: 'Draw Type',  v: isSde ? 'SDE Exit' : 'Regular',                    c: isSde ? 'text-rose-400' : 'text-blue-400' },
            { l: 'Entry',      v: isMerged ? 'Merge' : 'Direct',                     c: isMerged ? 'text-violet-400' : 'text-slate-400' },
          ].map(({ l, v, c }) => (
            <div key={l} className="bg-slate-800/80 rounded-xl p-2.5 text-center">
              <p className="text-[9px] text-slate-500 uppercase tracking-widest">{l}</p>
              <p className={`text-xs font-bold mt-0.5 ${c}`}>{v}</p>
            </div>
          ))}
        </div>

        {/* Timeline */}
        <div className="flex-1 overflow-y-auto px-5 py-5">
          <p className="text-[9px] text-slate-500 uppercase tracking-[0.2em] mb-4 font-semibold">
            Member Lifecycle Timeline
          </p>

          <div className="relative">
            <div className="absolute left-3 top-3 bottom-0 w-0.5 bg-slate-800"/>
            <div className="space-y-3.5">
              {events.map((ev, i) => {
                const c = COLORS[ev.color] ?? COLORS.slate
                return (
                  <div key={i} className="flex gap-3.5">
                    <div className={`w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center text-[9px] z-10 ${c.dot}`}>
                      {i === events.length - 1 ? '★' : i + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={`rounded-xl border px-3 py-2.5 ${c.card}`}>
                        <p className="text-xs font-bold">{ev.title}</p>
                        <p className="text-[10px] opacity-75 mt-0.5 leading-relaxed">{ev.detail}</p>
                        {ev.date && (
                          <p className="text-[9px] font-mono mt-1 opacity-50">{ev.date}</p>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <p className="text-[9px] text-slate-700 text-center mt-5">
            * Level advancement events are estimated from final level. Exact timestamps require full audit log.
          </p>
        </div>
      </div>
    </div>
  )
}

// ── KPI card ───────────────────────────────────────────────────────────────────
function KpiCard({ label, value, sub, colorClass = 'text-white' }) {
  return (
    <div className="bg-slate-800 border border-slate-700/60 rounded-xl p-4">
      <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-widest mb-2">{label}</p>
      <p className={`text-2xl font-bold tabular-nums leading-none ${colorClass}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

// ── Pagination bar ─────────────────────────────────────────────────────────────
function Pagination({ page, total, pageSize, onChange }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-slate-700/60">
      <span className="text-xs text-slate-500">
        Showing {Math.min((page - 1) * pageSize + 1, total)}–{Math.min(page * pageSize, total)} of {total} winners
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <span className="text-xs text-slate-400 px-2">
          {page} / {totalPages}
        </span>
        <button
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          className="p-1.5 rounded text-slate-400 hover:text-white hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function WinningLedger() {
  const { addToast } = useToast()

  const [items,    setItems]    = useState([])
  const [total,    setTotal]    = useState(0)
  const [page,     setPage]     = useState(1)
  const [loading,  setLoading]  = useState(false)

  // Filter state
  const [filterLevel,    setFilterLevel]    = useState('')   // '' = all, '1'–'6'
  const [filterJourney,  setFilterJourney]  = useState('')   // '' | 'direct' | 'merged'
  const [filterDrawType, setFilterDrawType] = useState('')   // '' | 'regular' | 'sde'

  // Module 5 — Forensic autopsy modal
  const [autopsyWinner, setAutopsyWinner] = useState(null)

  const PAGE_SIZE = 25

  const load = useCallback(async (pg = page) => {
    setLoading(true)
    try {
      // API uses limit/offset pagination
      const params = { limit: PAGE_SIZE, offset: (pg - 1) * PAGE_SIZE }
      if (filterLevel)    params.level        = Number(filterLevel)
      if (filterJourney)  params.journey_type = filterJourney
      if (filterDrawType) params.draw_type    = filterDrawType
      const { data } = await getWinnersHistory(params)
      setItems(data.items  ?? [])
      setTotal(data.total  ?? 0)
      setPage(pg)
    } catch {
      addToast('Failed to load winner history.', 'error')
    } finally {
      setLoading(false)
    }
  }, [page, filterLevel, filterJourney, filterDrawType, addToast])

  // Re-fetch when filters change
  useEffect(() => { load(1) }, [filterLevel, filterJourney, filterDrawType]) // eslint-disable-line react-hooks/exhaustive-deps

  // Initial load
  useEffect(() => { load(1) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Derived KPIs from visible page data ────────────────────────────────────
  const totalPaid    = items.reduce((s, w) => s + (w.net_winning_inr ?? 0), 0)
  const totalDep     = items.reduce((s, w) => s + (w.total_deposited_inr ?? 0), 0)
  const avgNet       = items.length ? (totalPaid / items.length) : 0
  const mergedCount  = items.filter(w => w.journey_type === 'merged').length
  const directCount  = items.filter(w => w.journey_type === 'direct').length
  const sdeCount     = items.filter(w =>
    (w.draw_type && String(w.draw_type).toLowerCase().includes('sde')) ||
    w.targeted_early_exit
  ).length

  return (
    <div className="p-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="bg-amber-600/20 p-2 rounded-lg border border-amber-600/30">
            <Trophy className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Winning Ledger</h1>
            <p className="text-sm text-slate-400 mt-0.5">Complete winner history with journey tracking</p>
          </div>
        </div>
        <button
          onClick={() => load(page)}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-300 hover:text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Total Winners"    value={total.toLocaleString()}                    colorClass="text-amber-400" />
        <KpiCard label="Winnings Paid"    value={`₹${(totalPaid/1000).toFixed(1)}K`}        colorClass="text-emerald-400"
                 sub={`page of ${PAGE_SIZE}`} />
        <KpiCard label="Avg Net Win"      value={`₹${Math.round(avgNet).toLocaleString()}`} colorClass="text-blue-400" />
        <KpiCard label="Direct Wins"      value={directCount.toLocaleString()}               colorClass="text-emerald-400" />
        <KpiCard label="Merged Wins"      value={mergedCount.toLocaleString()}               colorClass="text-violet-400" />
        <KpiCard label="SDE Exits"        value={sdeCount.toLocaleString()}                  colorClass="text-rose-400"
                 sub="this page" />
      </div>

      {/* Filters + table */}
      <div className="bg-slate-800 border border-slate-700/60 rounded-xl overflow-hidden">

        {/* Filter bar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-700/60 flex-wrap">
          <Filter className="w-4 h-4 text-slate-500 flex-shrink-0" />
          <span className="text-xs text-slate-500 font-semibold uppercase tracking-widest mr-1">Filter</span>

          {/* Level filter */}
          <select
            value={filterLevel}
            onChange={e => setFilterLevel(e.target.value)}
            className="bg-slate-700 border border-slate-600 text-slate-300 text-xs rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">All Levels</option>
            {[1,2,3,4,5,6].map(l => (
              <option key={l} value={l}>Level {l}</option>
            ))}
          </select>

          {/* Journey filter */}
          <select
            value={filterJourney}
            onChange={e => setFilterJourney(e.target.value)}
            className="bg-slate-700 border border-slate-600 text-slate-300 text-xs rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">All Entry Methods</option>
            <option value="direct">Direct (Waitlist)</option>
            <option value="merged">Dynamic Merge</option>
          </select>

          {/* Draw type filter */}
          <select
            value={filterDrawType}
            onChange={e => setFilterDrawType(e.target.value)}
            className="bg-slate-700 border border-slate-600 text-slate-300 text-xs rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">All Draw Types</option>
            <option value="regular">Regular Draw</option>
            <option value="sde">SDE Exit</option>
          </select>

          <span className="ml-auto text-xs text-slate-500">
            {total.toLocaleString()} total records
          </span>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] font-semibold text-slate-500 uppercase tracking-widest border-b border-slate-700/60">
                <th className="text-left px-4 py-3">Member</th>
                <th className="text-left px-4 py-3">Pool</th>
                <th className="text-center px-4 py-3">Level</th>
                <th className="text-left px-4 py-3">Entry Method</th>
                <th className="text-right px-4 py-3">Total Deposited</th>
                <th className="text-right px-4 py-3">Gross Won</th>
                <th className="text-right px-4 py-3">Net Won</th>
                <th className="text-right px-4 py-3">Net Profit</th>
                <th className="text-center px-4 py-3">Pauses</th>
                <th className="text-center px-4 py-3">Draw Type</th>
                <th className="text-center px-4 py-3">SDE</th>
                <th className="text-left px-4 py-3">Source</th>
                <th className="text-left px-4 py-3">Exit Date</th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 && (
                <tr>
                  <td colSpan={13} className="text-center py-12 text-slate-500 text-sm">
                    Loading...
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={13} className="text-center py-12 text-slate-500 text-sm">
                    <Trophy className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    No winner records found.
                    {(filterLevel || filterJourney) && (
                      <span className="block text-xs mt-1">Try clearing the filters above.</span>
                    )}
                  </td>
                </tr>
              )}
              {items.map((w, idx) => {
                // API field names: user_name, username, gross_payout_inr,
                // net_payout_inr, pauses_experienced, draw_timestamp
                const deposited = w.total_deposited_inr ?? 1000
                const gross     = w.gross_payout_inr    ?? 0
                const net       = w.net_payout_inr      ?? 0
                const profit    = net - deposited
                const lvl       = w.level_won           ?? 1
                const pauses    = w.pauses_experienced  ?? 0
                const exitDate  = w.draw_timestamp
                  ? new Date(w.draw_timestamp).toLocaleDateString('en-IN', {
                      day: '2-digit', month: 'short', year: '2-digit',
                    })
                  : '—'

                return (
                  <tr
                    key={`${w.draw_id ?? idx}-${w.user_id ?? idx}`}
                    onClick={() => setAutopsyWinner(w)}
                    className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors cursor-pointer"
                    title="Click to view member journey autopsy"
                  >
                    {/* Member */}
                    <td className="px-4 py-3">
                      <div className="font-medium text-white text-xs">{w.user_name ?? '—'}</div>
                      <div className="text-[10px] text-slate-500 font-mono">@{w.username ?? '—'}</div>
                    </td>

                    {/* Pool */}
                    <td className="px-4 py-3 text-xs text-slate-400 font-mono">
                      {w.pool_name ?? `Pool #${w.pool_id ?? '?'}`}
                    </td>

                    {/* Level badge */}
                    <td className="px-4 py-3 text-center">
                      <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold ${LEVEL_COLORS[lvl] ?? LEVEL_COLORS[1]}`}>
                        L{lvl}
                      </span>
                    </td>

                    {/* Entry method */}
                    <td className="px-4 py-3">
                      <JourneyBadge type={w.journey_type} />
                    </td>

                    {/* Total deposited */}
                    <td className="px-4 py-3 text-right text-xs text-slate-300 tabular-nums">
                      ₹{deposited.toLocaleString()}
                    </td>

                    {/* Gross won */}
                    <td className="px-4 py-3 text-right text-xs text-amber-400 tabular-nums font-medium">
                      ₹{Number(gross).toLocaleString()}
                    </td>

                    {/* Net won */}
                    <td className="px-4 py-3 text-right text-xs text-emerald-400 tabular-nums font-medium">
                      ₹{Number(net).toLocaleString()}
                    </td>

                    {/* Net profit (net won − total deposited) */}
                    <td className={`px-4 py-3 text-right text-xs tabular-nums font-bold ${profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {profit >= 0 ? '+' : ''}₹{profit.toLocaleString()}
                    </td>

                    {/* Pauses */}
                    <td className="px-4 py-3 text-center">
                      {pauses > 0 ? (
                        <span className="inline-block px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-400 text-[10px] font-bold border border-amber-700/30">
                          {pauses}×
                        </span>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
                    </td>

                    {/* Draw Type — Regular vs SDE Exit */}
                    <td className="px-4 py-3 text-center">
                      <DrawTypeBadge drawType={w.draw_type} />
                    </td>

                    {/* SDE targeted early exit */}
                    <td className="px-4 py-3 text-center">
                      <SdeTargetBadge targeted={w.targeted_early_exit} />
                    </td>

                    {/* Source — Referral / Organic */}
                    <td className="px-4 py-3">
                      <ReferralBadge isReferred={w.is_referred ?? false} />
                    </td>

                    {/* Exit date */}
                    <td className="px-4 py-3 text-xs text-slate-500">{exitDate}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > PAGE_SIZE && (
          <Pagination
            page={page}
            total={total}
            pageSize={PAGE_SIZE}
            onChange={pg => load(pg)}
          />
        )}
      </div>

      {/* Click-hint hint bar */}
      {items.length > 0 && !autopsyWinner && (
        <p className="text-center text-[10px] text-slate-600 font-mono">
          Click any row to open the Winner's Autopsy timeline
        </p>
      )}

      {/* Module 5: Forensic Autopsy Modal */}
      <WinnerAutopsyModal winner={autopsyWinner} onClose={() => setAutopsyWinner(null)} />
    </div>
  )
}
