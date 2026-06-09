/**
 * DevTools.jsx — Developer Mode control panel ("God Mode")
 *
 * Conditionally rendered:  only mounts when VITE_ENABLE_DEV_MODE=true.
 * The parent route guard (DevModeRoute in App.jsx) redirects away otherwise,
 * so this file never needs its own hard-stop — the guard already handles it.
 *
 * JWT:  All /dev/* API calls are authenticated automatically via the axios
 *       request interceptor in api/client.js (attaches Bearer from localStorage).
 *       No manual token handling needed here.
 */

import { useState, Fragment } from 'react'
import {
  Terminal, Zap, Clock, UserPlus, Skull,
  AlertTriangle, CheckCircle2, XCircle, Play,
  Info, Users, IndianRupee,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import {
  forceDrawDev,
  simulateCycleDev,
  simulateUsersDev,
  resetDataDev,
} from '../api/client'
import { useToast } from '../context/ToastContext'

const INR = n => `₹${Number(n).toLocaleString('en-IN')}`


// ─────────────────────────────────────────────────────────────────────────────
// Primitive UI helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Accessible toggle switch with red-on / slate-off colours */
function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 ${
        checked ? 'bg-red-600' : 'bg-slate-600'
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200 ${
          checked ? 'translate-x-[18px]' : 'translate-x-[3px]'
        }`}
      />
    </button>
  )
}

/** Dark card container with a coloured icon header row */
function DevCard({ icon: Icon, iconBg, iconColor, title, subtitle, children }) {
  return (
    <div className="bg-slate-900 border border-slate-700/60 rounded-2xl overflow-hidden shadow-xl shadow-black/30">
      <div className="flex items-center gap-3 px-6 py-4 border-b border-slate-700/60 bg-slate-900/80">
        <div className={`${iconBg} p-2.5 rounded-xl flex-shrink-0`}>
          <Icon className={`w-4 h-4 ${iconColor}`} />
        </div>
        <div className="min-w-0">
          <p className="font-bold text-slate-100 text-sm leading-none">{title}</p>
          {subtitle && (
            <p className="text-xs text-slate-500 mt-0.5 truncate">{subtitle}</p>
          )}
        </div>
      </div>
      <div className="p-6">{children}</div>
    </div>
  )
}

/** Compact stat tile — label on top, bold value below */
function StatPill({ label, value, accent = 'slate' }) {
  const cls = {
    slate:   'bg-slate-800 text-slate-100 border-slate-700',
    emerald: 'bg-emerald-950 text-emerald-300 border-emerald-800',
    amber:   'bg-amber-950 text-amber-300 border-amber-800',
    red:     'bg-red-950 text-red-300 border-red-800',
    purple:  'bg-purple-950 text-purple-300 border-purple-800',
    blue:    'bg-blue-950 text-blue-300 border-blue-800',
  }[accent] ?? 'bg-slate-800 text-slate-100 border-slate-700'

  return (
    <div className={`${cls} border rounded-xl p-3 text-center`}>
      <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-1 truncate">{label}</p>
      <p className="font-bold text-sm tabular-nums leading-none">{value}</p>
    </div>
  )
}

/** Wrapper that appears beneath a card after a successful API call */
function ResultBox({ children }) {
  return (
    <div className="mt-5 pt-5 border-t border-slate-700/60 space-y-4">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
        <CheckCircle2 className="w-3 h-3 text-emerald-500" />
        Response
      </p>
      {children}
    </div>
  )
}

/** Text input styled for the dark theme */
function DevInput({ label, hint, ...props }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 font-medium mb-1.5">
        {label}
        {hint && <span className="text-slate-600 ml-1">{hint}</span>}
      </label>
      <input
        {...props}
        className="w-full bg-slate-800 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-offset-0 focus:border-transparent transition-colors"
      />
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// Result renderers
// ─────────────────────────────────────────────────────────────────────────────

function WinnerCard({ slot, winner }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-600/50 p-4 space-y-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">{slot}</span>
        <span className="bg-purple-900/60 border border-purple-700/60 text-purple-300 text-[10px] font-bold px-2 py-0.5 rounded-full tracking-wider">
          LEVEL {winner.level}
        </span>
      </div>
      <p className="text-base font-bold text-white leading-none">{winner.username}</p>
      <p className="text-xl font-bold text-emerald-400 tabular-nums leading-none">{INR(winner.net_payout_inr)}</p>
      <div className="pt-1">
        <p className="text-[10px] text-slate-500 font-medium mb-1">WITHDRAW TOKEN</p>
        <code className="block text-xs font-mono bg-slate-900/80 rounded-lg px-3 py-2 text-amber-300 tracking-widest border border-slate-700/60">
          {winner.withdraw_token}
        </code>
      </div>
      {winner.replaced_by && (
        <p className="text-[10px] text-slate-500">
          Slot filled by&nbsp;<span className="text-slate-300 font-semibold">{winner.replaced_by}</span>
        </p>
      )}
    </div>
  )
}

function SingleDrawBadges({ r }) {
  return (
    <div className="flex flex-wrap gap-2 mb-4">
      <span className="bg-slate-800 text-slate-300 text-xs font-medium px-3 py-1.5 rounded-lg border border-slate-700">
        🏊&nbsp; {r.pool_name}&nbsp; <span className="text-slate-500">#{r.pool_id}</span>
      </span>
      {(r.auto_paid_count ?? 0) > 0 ? (
        <span className="bg-amber-950 border border-amber-800 text-amber-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
          <AlertTriangle className="w-3 h-3" />{r.auto_paid_count} unpaid auto-marked Paid
        </span>
      ) : (
        <span className="bg-slate-800 border border-slate-700 text-slate-400 text-xs px-3 py-1.5 rounded-lg">
          All members were already Paid
        </span>
      )}
      {(r.simulated_tokens_created ?? 0) > 0 && (
        <span className="bg-emerald-950 border border-emerald-800 text-emerald-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
          <IndianRupee className="w-3 h-3" />
          {r.simulated_tokens_created} cash inflow token{r.simulated_tokens_created !== 1 ? 's' : ''} created
        </span>
      )}
      {r.edge_case_used ? (
        <span className="bg-blue-950 border border-blue-800 text-blue-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
          <Info className="w-3 h-3" />Edge Case — No L4+ yet
        </span>
      ) : (
        <span className="bg-emerald-950 border border-emerald-800 text-emerald-300 text-xs font-semibold px-3 py-1.5 rounded-lg">
          ✓ Normal Draw (L1–3 vs L4–6)
        </span>
      )}
    </div>
  )
}

function RefillSummary({ refill }) {
  if (!refill) return null

  const hasP3 = (refill.phase3_transfers ?? 0) > 0
  const hasP3Dissolved = refill.phase3_dissolved?.length > 0

  return (
    <div className="mt-4 bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 space-y-3">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
        Triple-Phase FIFO Refill Summary
      </p>

      {/* ── Phase 1 ── */}
      <div>
        <p className="text-[9px] font-bold text-blue-400 uppercase tracking-widest mb-1.5">
          Phase 1 — Waitlist Fill
        </p>
        <div className="flex flex-wrap gap-2">
          <StatPill label="Assigned" value={refill.phase1_assigned} accent="blue" />
        </div>
        {refill.phase1_pool_changes?.length > 0 && (
          <div className="pt-2 space-y-1">
            {refill.phase1_pool_changes.map(c => (
              <p key={c.pool_id} className="text-[10px] font-mono text-slate-500">
                {c.pool_name}&nbsp;←&nbsp;
                <span className="text-sky-400">+{c.filled}</span>
                &nbsp;member{c.filled !== 1 ? 's' : ''}
                &nbsp;(now <span className="text-emerald-400">{c.total_after}/12</span>)
              </p>
            ))}
          </div>
        )}
        {refill.phase1_assigned === 0 && (
          <p className="text-[10px] text-slate-600 italic mt-1">Waitlist empty — no assignments.</p>
        )}
      </div>

      {/* ── Phase 2 ── */}
      <div>
        <p className="text-[9px] font-bold text-emerald-400 uppercase tracking-widest mb-1.5">
          Phase 2 — Auto-Scale
        </p>
        <div className="flex flex-wrap gap-2">
          <StatPill
            label="New Pool"
            value={refill.phase2_pool_created ?? 'none'}
            accent={refill.phase2_pool_created ? 'emerald' : 'slate'}
          />
          {(refill.phase2_assigned ?? 0) > 0 && (
            <StatPill label="Members" value={refill.phase2_assigned} accent="purple" />
          )}
        </div>
      </div>

      {/* ── Phase 3 ── */}
      <div>
        <p className="text-[9px] font-bold text-amber-400 uppercase tracking-widest mb-1.5">
          Phase 3 — Inter-Pool Condensation
        </p>
        {!hasP3 ? (
          <p className="text-[10px] text-slate-600 italic">
            No condensation needed — all pools at capacity after Phase 1.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2 mb-2">
              <StatPill label="Members Transferred" value={refill.phase3_transfers} accent="amber" />
              {hasP3Dissolved && (
                <StatPill
                  label="Pools Dissolved"
                  value={refill.phase3_dissolved.length}
                  accent="red"
                />
              )}
            </div>

            {/* Condensation event log */}
            {refill.phase3_events?.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-slate-700/50">
                <table className="w-full text-[10px] whitespace-nowrap">
                  <thead className="bg-slate-900/60">
                    <tr>
                      {['From (source)', 'To (target)', 'Moved', 'Outcome'].map(h => (
                        <th key={h} className="text-left py-2 px-3 text-slate-500 font-semibold uppercase tracking-wider">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {refill.phase3_events.map((ev, i) => (
                      <tr key={i} className="border-t border-slate-800/60">
                        <td className="py-2 px-3 font-mono text-slate-400">{ev.from_pool}</td>
                        <td className="py-2 px-3 font-mono text-slate-300 font-semibold">{ev.to_pool}</td>
                        <td className="py-2 px-3 text-amber-300 font-bold tabular-nums">+{ev.members_moved}</td>
                        <td className="py-2 px-3">
                          {ev.dissolved ? (
                            <span className="bg-red-950 border border-red-800 text-red-300 px-2 py-0.5 rounded-full font-semibold">
                              Dissolved
                            </span>
                          ) : (
                            <span className="bg-slate-800 border border-slate-700 text-slate-400 px-2 py-0.5 rounded-full">
                              Partial harvest
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {hasP3Dissolved && (
              <p className="text-[10px] text-red-400/80 flex items-center gap-1.5 pt-1">
                <span>⚠</span>
                Dissolved: {refill.phase3_dissolved.join(', ')}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function ForceDrawResult({ r }) {
  // ── Mass draw ──────────────────────────────────────────────────────────────
  if (r.mode === 'mass_draw') {
    return (
      <>
        {/* Summary badges */}
        <div className="flex flex-wrap gap-2 mb-4">
          <span className="bg-purple-950 border border-purple-800 text-purple-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
            <Zap className="w-3 h-3" />
            Global Mass Draw — {r.pools_drawn} pool{r.pools_drawn !== 1 ? 's' : ''} drawn
          </span>
          {r.total_auto_paid > 0 && (
            <span className="bg-amber-950 border border-amber-800 text-amber-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3" />{r.total_auto_paid} unpaid auto-marked Paid
            </span>
          )}
          {(r.simulated_tokens_created ?? 0) > 0 && (
            <span className="bg-emerald-950 border border-emerald-800 text-emerald-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
              <IndianRupee className="w-3 h-3" />{r.simulated_tokens_created} DEP tokens created
            </span>
          )}
          {r.skipped_pools?.length > 0 && (
            <span className="bg-red-950 border border-red-800 text-red-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3" />
              Errored: {r.skipped_pools.join(', ')}
            </span>
          )}
          {r.paused_pools?.length > 0 && (
            <span className="bg-orange-950 border border-orange-800 text-orange-300 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3" />
              Paused (partial): {r.paused_pools.join(', ')}
            </span>
          )}
        </div>

        {/* Per-pool draw results (collapsible table) */}
        {r.draws?.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-slate-700/60 mb-4">
            <table className="w-full text-xs whitespace-nowrap">
              <thead className="bg-slate-800/80">
                <tr>
                  {['Pool', 'Winner 1', 'Lvl', 'Payout', 'Winner 2', 'Lvl', 'Payout', 'Mode'].map(h => (
                    <th key={h} className="text-left py-2.5 px-3 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {r.draws.map(d => (
                  <tr key={d.pool_id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                    <td className="py-2.5 px-3 font-bold text-slate-300">{d.pool_name}</td>
                    <td className="py-2.5 px-3 font-mono text-slate-300 max-w-[120px]">
                      <span className="block truncate">{d.winner_1.username}</span>
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="bg-purple-900/60 border border-purple-700/50 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">L{d.winner_1.level}</span>
                    </td>
                    <td className="py-2.5 px-3 text-emerald-400 font-bold tabular-nums">{INR(d.winner_1.net_payout_inr)}</td>
                    <td className="py-2.5 px-3 font-mono text-slate-300 max-w-[120px]">
                      <span className="block truncate">{d.winner_2.username}</span>
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="bg-purple-900/60 border border-purple-700/50 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">L{d.winner_2.level}</span>
                    </td>
                    <td className="py-2.5 px-3 text-emerald-400 font-bold tabular-nums">{INR(d.winner_2.net_payout_inr)}</td>
                    <td className="py-2.5 px-3">
                      {d.edge_case_used
                        ? <span className="bg-amber-900/50 border border-amber-700/60 text-amber-300 px-2 py-0.5 rounded-full text-[10px] font-semibold">⚡ Early</span>
                        : <span className="bg-emerald-900/50 border border-emerald-700/60 text-emerald-300 px-2 py-0.5 rounded-full text-[10px] font-semibold">✓ Normal</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <RefillSummary refill={r.refill} />
      </>
    )
  }

  // ── Single draw (legacy + explicit pool_id) ────────────────────────────────
  return (
    <>
      <SingleDrawBadges r={r} />
      <div className="grid grid-cols-2 gap-3">
        <WinnerCard slot="Winner 1 — Low Tier (L1–3)" winner={r.winner_1} />
        <WinnerCard slot="Winner 2 — High Tier (L4–6)" winner={r.winner_2} />
      </div>
    </>
  )
}

function SimCycleResult({ r }) {
  return (
    <>
      {/* Summary stats */}
      <div className={`grid gap-3 mb-5 ${r.simulated_tokens_created > 0 ? 'grid-cols-5' : 'grid-cols-4'}`}>
        <StatPill label="Cycles Run"    value={`${r.n_executed} / ${r.n_requested}`} accent="blue" />
        <StatPill label="Users Created" value={r.users_created} />
        <StatPill label="Total Paid Out" value={INR(r.total_paid_out_inr)} accent="emerald" />
        <StatPill label="Pool"          value={r.pool_id ? `#${r.pool_id}` : 'Cleaned'} accent={r.pool_id ? 'purple' : 'amber'} />
        {r.simulated_tokens_created > 0 && (
          <StatPill
            label="DEP Tokens Simulated"
            value={r.simulated_tokens_created.toLocaleString('en-IN')}
            accent="amber"
          />
        )}
      </div>

      {/* Draw timeline table */}
      <div className="overflow-x-auto rounded-xl border border-slate-700/60">
        <table className="w-full text-xs whitespace-nowrap">
          <thead className="bg-slate-800/80">
            <tr>
              {['#', 'Winner 1', 'Lvl', 'Payout', 'Winner 2', 'Lvl', 'Payout', 'Pool State'].map(h => (
                <th
                  key={h}
                  className="text-left py-2.5 px-3 text-slate-400 font-semibold uppercase tracking-wider text-[10px]"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {r.draws.map((d, idx) => {
              const prev = r.draws[idx - 1]
              const maturityFlip = prev?.edge_case === true && d.edge_case === false
              return (
                <Fragment key={d.cycle}>
                  {maturityFlip && (
                    <tr>
                      <td
                        colSpan={8}
                        className="py-2.5 px-3 bg-emerald-950/70 border-y-2 border-emerald-700 text-center"
                      >
                        <span className="text-emerald-300 font-bold text-[10px] tracking-widest">
                          ★&nbsp;&nbsp;POOL MATURED — L4+ MEMBERS NOW AVAILABLE — NORMAL DRAW BEGINS&nbsp;&nbsp;★
                        </span>
                      </td>
                    </tr>
                  )}
                  <tr
                    className={`border-b border-slate-800/60 transition-colors ${
                      d.edge_case ? 'bg-amber-950/10 hover:bg-amber-950/20' : 'bg-emerald-950/10 hover:bg-emerald-950/20'
                    }`}
                  >
                    {/* Cycle # */}
                    <td className="py-2.5 px-3 font-bold text-slate-300 tabular-nums">
                      W{d.cycle}
                    </td>

                    {/* Winner 1 username */}
                    <td className="py-2.5 px-3 font-mono text-slate-300 max-w-[140px]">
                      <span className="block truncate" title={d.winner_1}>{d.winner_1}</span>
                    </td>

                    {/* Level 1 */}
                    <td className="py-2.5 px-3">
                      <span className="bg-purple-900/60 border border-purple-700/50 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">
                        L{d.level_1}
                      </span>
                    </td>

                    {/* Payout 1 */}
                    <td className="py-2.5 px-3 text-emerald-400 font-bold tabular-nums">
                      {INR(d.payout_1_inr)}
                    </td>

                    {/* Winner 2 username */}
                    <td className="py-2.5 px-3 font-mono text-slate-300 max-w-[140px]">
                      <span className="block truncate" title={d.winner_2}>{d.winner_2}</span>
                    </td>

                    {/* Level 2 */}
                    <td className="py-2.5 px-3">
                      <span className="bg-purple-900/60 border border-purple-700/50 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">
                        L{d.level_2}
                      </span>
                    </td>

                    {/* Payout 2 */}
                    <td className="py-2.5 px-3 text-emerald-400 font-bold tabular-nums">
                      {INR(d.payout_2_inr)}
                    </td>

                    {/* Edge case badge */}
                    <td className="py-2.5 px-3">
                      {d.edge_case ? (
                        <span className="bg-amber-900/50 border border-amber-700/60 text-amber-300 px-2 py-0.5 rounded-full font-semibold text-[10px]">
                          ⚡ Early Pool
                        </span>
                      ) : (
                        <span className="bg-emerald-900/50 border border-emerald-700/60 text-emerald-300 px-2 py-0.5 rounded-full font-semibold text-[10px]">
                          ✓ Mature
                        </span>
                      )}
                    </td>
                  </tr>
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {r.cleanup_done && (
        <p className="text-xs text-slate-500 flex items-center gap-1.5 pt-1">
          <CheckCircle2 className="w-3.5 h-3.5 text-slate-600" />
          All generated users, tokens, and pool have been deleted (cleanup=true).
        </p>
      )}
    </>
  )
}

function InjectResult({ r }) {
  return (
    <>
      <div className="grid grid-cols-4 gap-3 mb-4">
        <StatPill label="Users Created"  value={r.users_created.toLocaleString('en-IN')} accent="emerald" />
        <StatPill label="DEP Tokens"     value={r.dep_tokens_created.toLocaleString('en-IN')} accent="emerald" />
        <StatPill label="Pools Formed"   value={r.pools_formed} accent={r.pools_formed > 0 ? 'blue' : 'slate'} />
        <StatPill label="Elapsed"        value={`${r.elapsed_ms.toLocaleString()}ms`} accent="purple" />
      </div>
      <div className="bg-slate-800/70 border border-slate-700/50 rounded-xl px-4 py-3">
        <p className="text-xs text-slate-400 font-mono leading-relaxed">{r.note}</p>
      </div>
      {r.waitlist_remaining > 0 && (
        <p className="text-xs text-amber-400 flex items-center gap-1.5 pt-1">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          {r.waitlist_remaining.toLocaleString('en-IN')} users still on waitlist — use Force Draw or run another inject.
        </p>
      )}
    </>
  )
}

function NukeResult({ r }) {
  return (
    <>
      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatPill label="Users Deleted"  value={r.users_deleted.toLocaleString('en-IN')} accent="red" />
        <StatPill label="Tokens Deleted" value={r.tokens_deleted.toLocaleString('en-IN')} accent="red" />
        <StatPill label="Pools Deleted"  value={r.pools_deleted.toLocaleString('en-IN')} accent="red" />
      </div>
      {r.sequences_reset ? (
        <p className="text-emerald-400 text-xs flex items-center gap-1.5">
          <CheckCircle2 className="w-3.5 h-3.5" />
          All auto-increment IDs reset to 1. Next user gets id=1.
        </p>
      ) : (
        <p className="text-amber-400 text-xs flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5" />
          Rows deleted but sequence reset skipped (non-PostgreSQL backend).
        </p>
      )}
      <p className="text-xs text-slate-500 flex items-center gap-1.5 mt-1">
        <CheckCircle2 className="w-3.5 h-3.5 text-slate-600" />
        {r.note}
      </p>
    </>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// Main Page Component
// ─────────────────────────────────────────────────────────────────────────────

export default function DevTools() {
  const toast = useToast()

  // Global: 403 from server (ENABLE_DEV_MODE=false) blocks all tools
  const [serverDevError, setServerDevError] = useState(null)

  // ── Force Draw ────────────────────────────────────────────────────────────
  const [drawPoolId,              setDrawPoolId]              = useState('')
  const [drawLoading,             setDrawLoading]             = useState(false)
  const [drawResult,              setDrawResult]              = useState(null)
  const [drawAutoPayInstallments, setDrawAutoPayInstallments] = useState(false)

  // ── Simulate Cycle ────────────────────────────────────────────────────────
  const [simCycles,              setSimCycles]              = useState(3)
  const [simCleanup,             setSimCleanup]             = useState(true)
  const [simLoading,             setSimLoading]             = useState(false)
  const [simResult,              setSimResult]              = useState(null)
  const [simAutoPayInstallments, setSimAutoPayInstallments] = useState(false)

  // ── Mass User Injection ───────────────────────────────────────────────────
  const [injectCount,    setInjectCount]    = useState(1_000)
  const [injectAutoPool, setInjectAutoPool] = useState(true)
  const [injectLoading,  setInjectLoading]  = useState(false)
  const [injectResult,   setInjectResult]   = useState(null)

  // ── Database Nuke ─────────────────────────────────────────────────────────
  const [nukeConfirm, setNukeConfirm] = useState('')
  const [nukeLoading, setNukeLoading] = useState(false)
  const [nukeResult,  setNukeResult]  = useState(null)

  // ── Shared error handler ──────────────────────────────────────────────────
  const handleErr = (err, fallback) => {
    if (err.response?.status === 403) {
      setServerDevError(
        err.response?.data?.detail ??
        'ENABLE_DEV_MODE is not set to true on the server.'
      )
      return
    }
    const msg = err.response?.data?.detail ?? fallback
    toast(msg, 'error')
  }

  // ── Force Draw handler ────────────────────────────────────────────────────
  const handleForceDraw = async () => {
    setDrawLoading(true)
    setDrawResult(null)
    try {
      const pid = drawPoolId.trim() ? parseInt(drawPoolId.trim(), 10) : undefined
      const res = await forceDrawDev(pid, drawAutoPayInstallments)
      setDrawResult(res.data)
      const msg = res.data.mode === 'mass_draw'
        ? `Mass draw complete — ${res.data.pools_drawn} pool(s) drawn`
        : `Draw complete — ${res.data.pool_name}`
      toast(msg, 'success')
    } catch (err) {
      handleErr(err, 'Force draw failed')
    } finally {
      setDrawLoading(false)
    }
  }

  // ── Simulate Cycle handler ────────────────────────────────────────────────
  const handleSimCycle = async () => {
    setSimLoading(true)
    setSimResult(null)
    try {
      const res = await simulateCycleDev(simCycles, simCleanup, simAutoPayInstallments)
      setSimResult(res.data)
      toast(`Simulation complete — ${res.data.n_executed} of ${res.data.n_requested} cycles run`, 'success')
    } catch (err) {
      handleErr(err, 'Simulation failed')
    } finally {
      setSimLoading(false)
    }
  }

  // ── Mass User Injection handler ───────────────────────────────────────────
  const handleInject = async () => {
    setInjectLoading(true)
    setInjectResult(null)
    try {
      const res = await simulateUsersDev(injectCount, injectAutoPool)
      setInjectResult(res.data)
      toast(`${res.data.users_created.toLocaleString()} users injected`, 'success')
    } catch (err) {
      handleErr(err, 'User injection failed')
    } finally {
      setInjectLoading(false)
    }
  }

  // ── Database Nuke handler ─────────────────────────────────────────────────
  const handleNuke = async () => {
    setNukeLoading(true)
    setNukeResult(null)
    try {
      const res = await resetDataDev()
      setNukeResult(res.data)
      setNukeConfirm('')
      toast('Database nuked — all user data cleared', 'warning')
    } catch (err) {
      handleErr(err, 'Database reset failed')
    } finally {
      setNukeLoading(false)
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  // Informational hint: simulate_cycle creates max(threshold, 12) + 2×N users.
  // Threshold is fetched dynamically; default hint assumes 24.
  const fakesForSim = `≥${12 + 2 * simCycles} (threshold + 2×cycles)`

  return (
    <div className="min-h-full bg-slate-950">

      {/* ── Warning Header ──────────────────────────────────────────────────── */}
      <div className="bg-gradient-to-r from-red-950 via-slate-900 to-slate-950 border-b-2 border-red-800/50 px-8 py-5 sticky top-0 z-10">
        <div className="flex items-center gap-4 max-w-6xl mx-auto">
          <div className="bg-red-800/30 border border-red-700/50 p-3 rounded-xl flex-shrink-0">
            <Terminal className="w-5 h-5 text-red-400" />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-base font-bold text-red-100 leading-none tracking-wide">
              Developer Tools&nbsp;&nbsp;—&nbsp;&nbsp;God Mode
            </h1>
            <p className="text-xs text-red-400/70 mt-0.5">
              Direct database mutations · Actions are irreversible · Use on staging only
            </p>
          </div>
          <div className="hidden sm:flex items-center gap-2 bg-red-950/80 border border-red-800 rounded-lg px-3 py-1.5 flex-shrink-0">
            <span className="w-1.5 h-1.5 bg-red-400 rounded-full animate-pulse block" />
            <code className="text-xs font-mono font-bold text-red-300 tracking-wider">
              ENABLE_DEV_MODE=true
            </code>
          </div>
        </div>
      </div>

      {/* ── Page body ───────────────────────────────────────────────────────── */}
      <div className="p-8 max-w-6xl mx-auto space-y-6">

        {/* ── 403 Server Error Banner ────────────────────────────────────────── */}
        {serverDevError && (
          <div className="bg-red-950 border-2 border-red-600/80 rounded-2xl p-6 flex items-start gap-4 shadow-2xl shadow-red-950/50">
            <div className="bg-red-800/40 border border-red-700/50 rounded-xl p-2 flex-shrink-0 mt-0.5">
              <XCircle className="w-6 h-6 text-red-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-red-100 font-bold text-base leading-tight">
                ENABLE_DEV_MODE is false on the server
              </h2>
              <p className="text-red-300 text-sm mt-2 leading-relaxed">
                The backend is rejecting all <code className="bg-red-900/60 px-1.5 py-0.5 rounded text-red-200 font-mono">/dev/*</code> requests with HTTP&nbsp;403.
                You must set&nbsp;
                <code className="bg-red-900/60 px-1.5 py-0.5 rounded text-red-200 font-mono">ENABLE_DEV_MODE=true</code>&nbsp;
                in your Render environment variables and redeploy the backend before these tools will work.
              </p>
              <p className="text-red-500 text-xs font-mono mt-3 bg-red-950/60 rounded-lg px-3 py-2 border border-red-900">
                {serverDevError}
              </p>
              <button
                onClick={() => setServerDevError(null)}
                className="mt-3 text-xs text-red-400 hover:text-red-200 underline underline-offset-2 transition-colors"
              >
                Dismiss banner
              </button>
            </div>
          </div>
        )}

        {/* ── Row 1: Force Draw + Simulate Cycle (2-column grid) ─────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">

          {/* ── Tool A — Force Draw ─────────────────────────────────────────── */}
          <DevCard
            icon={Zap}
            iconBg="bg-amber-900/40 border border-amber-700/50"
            iconColor="text-amber-400"
            title="Force Draw"
            subtitle="Run the Sunday dual-draw instantly on any active pool"
          >
            <div className="space-y-4">
              <DevInput
                label="Target Pool ID"
                hint="(optional)"
                type="number"
                min={1}
                value={drawPoolId}
                onChange={e => setDrawPoolId(e.target.value)}
                placeholder="Leave blank → auto-select first active pool"
                className="focus:ring-amber-600"
              />

              <p className="text-xs text-slate-500">
                Unpaid members are automatically marked <span className="text-amber-400">Paid</span> before the draw, so it never fails due to payment status.
              </p>

              {/* ── Cash Inflow Simulation toggle ───────────────────────────────── */}
              <div
                role="checkbox"
                aria-checked={drawAutoPayInstallments}
                tabIndex={0}
                onClick={() => setDrawAutoPayInstallments(v => !v)}
                onKeyDown={e => e.key === ' ' && setDrawAutoPayInstallments(v => !v)}
                className={`flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer select-none transition-colors ${
                  drawAutoPayInstallments
                    ? 'bg-amber-950/30 border-amber-700/60'
                    : 'bg-slate-800/50 border-slate-700/50 hover:border-slate-600/70'
                }`}
              >
                <div className={`mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors ${
                  drawAutoPayInstallments
                    ? 'bg-amber-500 border-amber-500'
                    : 'border-slate-500 bg-transparent'
                }`}>
                  {drawAutoPayInstallments && (
                    <svg viewBox="0 0 12 12" className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth={2.5}>
                      <polyline points="1.5,6 4.5,9 10.5,3" />
                    </svg>
                  )}
                </div>
                <div>
                  <p className={`text-xs font-semibold leading-none ${drawAutoPayInstallments ? 'text-amber-300' : 'text-slate-300'}`}>
                    Simulate Token Cash Inflow (Mark Unpaid as Paid)
                  </p>
                  <p className="text-[10px] text-slate-500 mt-1.5 leading-relaxed">
                    Creates real <span className="text-slate-400 font-mono">Burned</span> DEP token records for each
                    unpaid member before drawing. Admin financial stats (Cash Inflow / Total Collection)
                    will reflect this simulation accurately. Without this, only payment status flips.
                  </p>
                </div>
              </div>

              <button
                onClick={handleForceDraw}
                disabled={drawLoading}
                className="w-full flex items-center justify-center gap-2 bg-amber-700 hover:bg-amber-600 active:bg-amber-800 disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed text-white font-bold py-3 px-4 rounded-xl transition-colors shadow-lg shadow-amber-900/20"
              >
                {drawLoading ? (
                  <><Spinner className="w-4 h-4 text-white" />Running Draw…</>
                ) : (
                  <><Zap className="w-4 h-4" />Execute Instant Draw</>
                )}
              </button>

              {drawResult && (
                <ResultBox>
                  <ForceDrawResult r={drawResult} />
                </ResultBox>
              )}
            </div>
          </DevCard>

          {/* ── Tool B — Simulate Cycle ─────────────────────────────────────── */}
          <DevCard
            icon={Clock}
            iconBg="bg-blue-900/40 border border-blue-700/50"
            iconColor="text-blue-400"
            title="Time-Travel Simulator"
            subtitle="Fast-forward N weekly draw cycles on a generated pool"
          >
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <DevInput
                  label="Cycles"
                  hint="(1–12)"
                  type="number"
                  min={1}
                  max={12}
                  value={simCycles}
                  onChange={e => setSimCycles(
                    Math.min(12, Math.max(1, parseInt(e.target.value, 10) || 1))
                  )}
                  className="focus:ring-blue-600"
                />

                <div>
                  <p className="text-xs text-slate-400 font-medium mb-1.5">Cleanup After Run</p>
                  <div className="flex items-center gap-3 h-10">
                    <Toggle
                      checked={simCleanup}
                      onChange={setSimCleanup}
                      label="Delete generated data after run"
                    />
                    <span className="text-xs text-slate-300">
                      {simCleanup ? 'Yes — purge after' : 'No — keep pool'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3 space-y-1 text-xs text-slate-500">
                <p>Creates <span className="text-slate-300 font-medium">{fakesForSim} fake users</span> → 1 pool of 12 → runs <span className="text-slate-300 font-medium">{simCycles} draw cycle{simCycles !== 1 ? 's' : ''}</span>.</p>
                <p>Watch <span className="text-amber-400 font-semibold">⚡ Early Pool</span> flip to <span className="text-emerald-400 font-semibold">✓ Mature</span> at cycle 4.</p>
              </div>

              {/* ── Cash Inflow Simulation toggle ───────────────────────────────── */}
              <div
                role="checkbox"
                aria-checked={simAutoPayInstallments}
                tabIndex={0}
                onClick={() => setSimAutoPayInstallments(v => !v)}
                onKeyDown={e => e.key === ' ' && setSimAutoPayInstallments(v => !v)}
                className={`flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer select-none transition-colors ${
                  simAutoPayInstallments
                    ? 'bg-blue-950/40 border-blue-700/60'
                    : 'bg-slate-800/50 border-slate-700/50 hover:border-slate-600/70'
                }`}
              >
                <div className={`mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors ${
                  simAutoPayInstallments
                    ? 'bg-blue-500 border-blue-500'
                    : 'border-slate-500 bg-transparent'
                }`}>
                  {simAutoPayInstallments && (
                    <svg viewBox="0 0 12 12" className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth={2.5}>
                      <polyline points="1.5,6 4.5,9 10.5,3" />
                    </svg>
                  )}
                </div>
                <div>
                  <p className={`text-xs font-semibold leading-none ${simAutoPayInstallments ? 'text-blue-300' : 'text-slate-300'}`}>
                    Simulate Token Cash Inflow (Mark Unpaid as Paid)
                  </p>
                  <p className="text-[10px] text-slate-500 mt-1.5 leading-relaxed">
                    Before each draw cycle, creates real <span className="text-slate-400 font-mono">Burned</span> DEP records
                    for unpaid members. Admin financial statistics (Total Collection / Cash Inflow) will
                    reflect the simulated instalments accurately. Without this, only payment status flips.
                  </p>
                </div>
              </div>

              <button
                onClick={handleSimCycle}
                disabled={simLoading}
                className="w-full flex items-center justify-center gap-2 bg-blue-700 hover:bg-blue-600 active:bg-blue-800 disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed text-white font-bold py-3 px-4 rounded-xl transition-colors shadow-lg shadow-blue-900/20"
              >
                {simLoading ? (
                  <><Spinner className="w-4 h-4 text-white" />Simulating {simCycles} cycle{simCycles !== 1 ? 's' : ''}…</>
                ) : (
                  <><Play className="w-4 h-4" />Run Simulation</>
                )}
              </button>

              {simResult && (
                <ResultBox>
                  <SimCycleResult r={simResult} />
                </ResultBox>
              )}
            </div>
          </DevCard>
        </div>

        {/* ── Row 2: Mass User Injection (full width) ─────────────────────────── */}
        <DevCard
          icon={UserPlus}
          iconBg="bg-emerald-900/40 border border-emerald-700/50"
          iconColor="text-emerald-400"
          title="Mass User Injection"
          subtitle="Bulk-create fake Waitlist users with Burned DEP tokens using SQLAlchemy Core batch inserts"
        >
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
              <div className="sm:col-span-2">
                <DevInput
                  label="Number of Users"
                  hint="(1 – 100,000)"
                  type="number"
                  min={1}
                  max={100_000}
                  value={injectCount}
                  onChange={e =>
                    setInjectCount(Math.min(100_000, Math.max(1, parseInt(e.target.value, 10) || 1)))
                  }
                  className="focus:ring-emerald-600"
                />
              </div>
              <div>
                <p className="text-xs text-slate-400 font-medium mb-1.5">Auto-Form Pools</p>
                <div className="flex items-center gap-3 h-10">
                  <Toggle
                    checked={injectAutoPool}
                    onChange={setInjectAutoPool}
                    label="Auto-trigger pool formation"
                  />
                  <span className="text-xs text-slate-300">{injectAutoPool ? 'Yes' : 'No'}</span>
                </div>
              </div>
            </div>

            {/* Dynamic performance hint based on count */}
            {injectCount >= 10_000 && (
              <div className="flex items-start gap-2.5 bg-amber-950/30 border border-amber-800/40 rounded-xl px-4 py-3">
                <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-amber-300/90 leading-relaxed">
                  <strong className="text-amber-200">{injectCount.toLocaleString('en-IN')} users</strong> is a large batch.
                  Backend uses batches of 5,000 rows — expect ~{Math.ceil(injectCount / 5_000) * 2} DB round-trips.
                  {injectCount >= 50_000
                    ? ' This may take 15–30 seconds on Render free tier. Please wait.'
                    : ' Usually completes in under 5 seconds.'}
                </p>
              </div>
            )}

            <div className="flex items-center gap-3 text-xs text-slate-500">
              <Users className="w-3.5 h-3.5 flex-shrink-0" />
              Each user gets a unique username, mobile number, and a Burned DEP token (₹1,000) — simulating a completed deposit.
            </div>

            <button
              onClick={handleInject}
              disabled={injectLoading}
              className="w-full flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 active:bg-emerald-800 disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed text-white font-bold py-3 px-4 rounded-xl transition-colors shadow-lg shadow-emerald-900/20"
            >
              {injectLoading ? (
                <><Spinner className="w-4 h-4 text-white" />Injecting {injectCount.toLocaleString('en-IN')} users…</>
              ) : (
                <><UserPlus className="w-4 h-4" />Inject {injectCount.toLocaleString('en-IN')} Users</>
              )}
            </button>

            {injectResult && (
              <ResultBox>
                <InjectResult r={injectResult} />
              </ResultBox>
            )}
          </div>
        </DevCard>

        {/* ── Row 3: Danger Zone ───────────────────────────────────────────────── */}
        <div className="bg-red-950/20 border-2 border-red-800/50 rounded-2xl overflow-hidden shadow-2xl shadow-red-950/20">
          {/* Danger Zone header */}
          <div className="flex items-center gap-3 px-6 py-4 bg-red-950/60 border-b-2 border-red-800/50">
            <div className="bg-red-800/50 border border-red-600/50 p-2.5 rounded-xl flex-shrink-0">
              <Skull className="w-4 h-4 text-red-300" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-bold text-red-100 text-sm tracking-wider">DANGER ZONE</p>
              <p className="text-xs text-red-400/70 mt-0.5">Irreversible operations · Admin accounts are never affected</p>
            </div>
            <span className="flex-shrink-0 text-[10px] font-mono font-bold bg-red-900/60 border border-red-700 text-red-300 px-2.5 py-1 rounded-lg tracking-widest">
              DESTRUCTIVE
            </span>
          </div>

          <div className="p-6 space-y-5">
            {/* What this does */}
            <div className="bg-red-900/15 border border-red-800/30 rounded-xl p-4 space-y-2">
              <p className="text-xs font-bold text-red-200 flex items-center gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                What "Nuke Database" does
              </p>
              <ul className="text-xs text-red-300/70 space-y-1 pl-5 list-disc leading-relaxed">
                <li>Deletes <strong className="text-red-200">all rows</strong> from <code className="bg-red-900/50 px-1 rounded font-mono">users</code>, <code className="bg-red-900/50 px-1 rounded font-mono">pools</code>, and <code className="bg-red-900/50 px-1 rounded font-mono">tokens</code> tables</li>
                <li>Resets PostgreSQL auto-increment sequences — next user gets <code className="bg-red-900/50 px-1 rounded font-mono">id = 1</code></li>
                <li><strong className="text-red-100">Admin accounts are NOT deleted</strong> — the <code className="bg-red-900/50 px-1 rounded font-mono">admins</code> table is untouched</li>
                <li className="text-red-400">This action <strong>cannot be undone</strong></li>
              </ul>
            </div>

            {/* Confirmation input + nuke button */}
            <div className="flex flex-col sm:flex-row items-start sm:items-end gap-4">
              <div className="flex-1 w-full">
                <label className="block text-xs font-medium mb-1.5">
                  <span className="text-slate-400">Type </span>
                  <code className="text-red-300 font-mono font-bold bg-red-950 px-1.5 py-0.5 rounded border border-red-800">
                    DELETE
                  </code>
                  <span className="text-slate-400"> to unlock the button</span>
                </label>
                <input
                  type="text"
                  value={nukeConfirm}
                  onChange={e => setNukeConfirm(e.target.value)}
                  placeholder="DELETE"
                  autoComplete="off"
                  spellCheck={false}
                  className={`w-full bg-slate-900 border rounded-xl px-4 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:border-transparent transition-all duration-200 ${
                    nukeConfirm === 'DELETE'
                      ? 'border-red-600 text-red-300 focus:ring-red-700 shadow-lg shadow-red-950/40'
                      : 'border-slate-700 text-slate-300 focus:ring-slate-600'
                  }`}
                />
              </div>

              <button
                onClick={handleNuke}
                disabled={nukeConfirm !== 'DELETE' || nukeLoading}
                className={`flex-shrink-0 flex items-center gap-2.5 font-bold py-3 px-7 rounded-xl transition-all duration-200 ${
                  nukeConfirm === 'DELETE' && !nukeLoading
                    ? 'bg-red-700 hover:bg-red-600 active:bg-red-800 text-white shadow-xl shadow-red-900/40 animate-pulse'
                    : 'bg-slate-800 text-slate-600 cursor-not-allowed border border-slate-700'
                }`}
              >
                {nukeLoading ? (
                  <><Spinner className="w-4 h-4 text-white" />Nuking…</>
                ) : (
                  <><Skull className="w-4 h-4" />NUKE DATABASE</>
                )}
              </button>
            </div>

            {nukeResult && (
              <ResultBox>
                <NukeResult r={nukeResult} />
              </ResultBox>
            )}
          </div>
        </div>

        {/* Bottom breathing room */}
        <div className="h-6" />
      </div>
    </div>
  )
}
