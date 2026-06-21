/**
 * DrawEngine.jsx — Draw Engine & SDE Control Center
 *
 * Sections:
 *  1. LPI Gauge + Pool Type Routing Decision
 *  2. Weekly Draw State Machine
 *  3. SDE Session Status + Brain 5 Pressure Map
 *  4. Admin Override Panel (Option A / B)
 *  5. Scheduler Status (APScheduler job next-run times)
 *  6. Manual Controls (Prepare · Execute · Cleanup)
 *
 * All data is fetched on mount and on manual refresh.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Cpu, RefreshCw, AlertTriangle, CheckCircle2,
  Clock, Zap, Shield, Activity, Calendar,
  ChevronRight, Play, RotateCcw, XCircle,
  TrendingUp, Layers, Database, AlertCircle,
  IndianRupee, Timer, Settings,
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  ShieldCheck, ShieldAlert, Lock, Scale, ListChecks,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import {
  getBrain5Lpi, getDrawState, getDrawCountdown,
  prepareWeeklyDraw, manualExecuteDraw, triggerPostDrawCleanup,
  getOverrideDashboard, submitOverrideDecision, getSchedulerStatus,
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  getReassessment, approveReassessment,
} from '../api/client'
import { useToast } from '../context/ToastContext'

// ─── Helpers ──────────────────────────────────────────────────────────────────
const INR = v => `₹${Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const fP  = v => parseFloat(v ?? 0)
const fmt = iso => iso ? new Date(iso).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' }) : '—'

function Chip({ label, value, accent = 'slate' }) {
  const c = {
    slate:   'bg-slate-50 text-slate-600 border-slate-200',
    green:   'bg-emerald-50 text-emerald-700 border-emerald-200',
    amber:   'bg-amber-50 text-amber-700 border-amber-200',
    red:     'bg-red-50 text-red-700 border-red-200',
    blue:    'bg-blue-50 text-blue-700 border-blue-200',
    violet:  'bg-violet-50 text-violet-700 border-violet-200',
  }[accent] ?? 'bg-slate-50 text-slate-600 border-slate-200'
  return (
    <div className={`${c} border rounded-xl px-3 py-2 text-center`}>
      <p className="text-[10px] font-semibold uppercase tracking-wider mb-0.5 opacity-60">{label}</p>
      <p className="text-sm font-bold tabular-nums leading-none">{value}</p>
    </div>
  )
}

function SectionCard({ title, icon: Icon, iconColor = 'text-slate-400', badge, children, action }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
        <Icon className={`w-4 h-4 flex-shrink-0 ${iconColor}`} />
        <h2 className="font-semibold text-slate-800 flex-1">{title}</h2>
        {badge && <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">{badge}</span>}
        {action}
      </div>
      {children}
    </div>
  )
}

// ─── LPI Semicircular Gauge ───────────────────────────────────────────────────
function LpiGauge({ lpi = 0 }) {
  const r       = 70
  const cx      = 90
  const cy      = 90
  const stroke  = 12
  const circ    = Math.PI * r            // half circumference (semicircle)
  const pct     = Math.min(100, Math.max(0, lpi)) / 100
  const filled  = pct * circ

  // Colour zones
  const color =
    lpi < 14  ? '#10b981' :   // green — regular
    lpi < 25  ? '#f59e0b' :   // amber — type A
    lpi < 50  ? '#f97316' :   // orange — SDE proactive
                '#ef4444'     // red — SDE hard + L3 exception

  const zones = [
    { pct: 0.14, color: '#10b981', label: 'Regular' },
    { pct: 0.11, color: '#f59e0b', label: 'Type A'  },
    { pct: 0.25, color: '#f97316', label: 'SDE'     },
    { pct: 0.50, color: '#ef4444', label: 'Critical' },
  ]

  return (
    <div className="flex flex-col items-center">
      <svg width={180} height={110} viewBox="0 0 180 110">
        {/* Track arc */}
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none" stroke="#f1f5f9" strokeWidth={stroke}
          strokeLinecap="round"
        />
        {/* Filled arc */}
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circ}`}
          style={{ transition: 'stroke-dasharray 0.8s ease, stroke 0.5s' }}
        />
        {/* Zone ticks */}
        {[14, 25, 50].map(z => {
          const angle = Math.PI * (z / 100) - Math.PI
          const tx = cx + r * Math.cos(angle)
          const ty = cy + r * Math.sin(angle)
          return (
            <circle key={z} cx={tx} cy={ty} r={3} fill="#94a3b8" />
          )
        })}
        {/* Centre value */}
        <text x={cx} y={cy - 8} textAnchor="middle" fontSize={28} fontWeight="900" fill={color}>
          {lpi.toFixed(1)}%
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" fontSize={10} fill="#94a3b8" fontWeight="600" letterSpacing={1}>
          LPI
        </text>
      </svg>

      {/* Zone legend */}
      <div className="flex gap-2 flex-wrap justify-center mt-1">
        {[
          { range: '0–14%',  label: 'Regular',  c: '#10b981' },
          { range: '14–25%', label: 'Type A',   c: '#f59e0b' },
          { range: '25–50%', label: 'SDE',      c: '#f97316' },
          { range: '50%+',   label: 'Critical', c: '#ef4444' },
        ].map(z => (
          <div key={z.label} className="flex items-center gap-1 text-[10px] text-slate-500">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: z.c }} />
            {z.label} <span className="text-slate-400">{z.range}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Pool Type Routing Decision card ─────────────────────────────────────────
function PoolTypeDecision({ decision }) {
  if (!decision) return <div className="p-6 text-sm text-slate-400">No decision data</div>

  const tiers = [
    { label: 'P1 — SDE',     active: decision.p1_sde_active,    reason: decision.p1_sde_reason,   c: 'red',    desc: 'L4 forced eviction' },
    { label: 'P2 — Type A',  active: decision.p2_type_a_active,  reason: 'LPI 14–24%',             c: 'amber',  desc: 'L1–2 lower / L3–4 upper' },
    { label: 'P3 — Regular', active: decision.p3_regular_active, reason: 'LPI < 14%',              c: 'green',  desc: 'L1–3 lower / L4–6 upper' },
    { label: 'P4 — Type B',  active: decision.p4_type_b_active,  reason: 'L1/L2 exhausted',        c: 'violet', desc: 'L3 lower / L4 upper (fallback)' },
  ]

  const colors = {
    red:    { bg: 'bg-red-50',    text: 'text-red-700',    border: 'border-red-200',    dot: 'bg-red-500' },
    amber:  { bg: 'bg-amber-50',  text: 'text-amber-700',  border: 'border-amber-200',  dot: 'bg-amber-500' },
    green:  { bg: 'bg-emerald-50',text: 'text-emerald-700',border: 'border-emerald-200',dot: 'bg-emerald-500' },
    violet: { bg: 'bg-violet-50', text: 'text-violet-700', border: 'border-violet-200', dot: 'bg-violet-500' },
    off:    { bg: 'bg-slate-50',  text: 'text-slate-400',  border: 'border-slate-200',  dot: 'bg-slate-300' },
  }

  return (
    <div className="p-4 grid grid-cols-2 gap-3">
      {tiers.map(t => {
        const tc = t.active ? colors[t.c] : colors.off
        return (
          <div key={t.label} className={`${tc.bg} ${tc.border} border rounded-xl p-3 transition-all`}>
            <div className="flex items-center gap-2 mb-1.5">
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${tc.dot} ${t.active ? 'animate-pulse' : ''}`} />
              <span className={`text-xs font-bold ${tc.text}`}>{t.label}</span>
              {t.active && (
                <span className={`ml-auto text-[9px] font-black px-1.5 py-0.5 rounded-full ${tc.text} ${tc.bg} border ${tc.border}`}>
                  ACTIVE
                </span>
              )}
            </div>
            <p className="text-[10px] text-slate-500 leading-tight">{t.desc}</p>
            {t.active && t.reason && (
              <p className={`text-[10px] font-semibold mt-1 ${tc.text}`}>{t.reason}</p>
            )}
          </div>
        )
      })}

      {decision.l4_flagged_count > 0 && (
        <div className="col-span-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
          <span className="text-xs text-red-600 font-semibold">
            {decision.l4_flagged_count} L4 member(s) flagged for SDE eviction this cycle
          </span>
        </div>
      )}
    </div>
  )
}

// ─── Draw State Machine ───────────────────────────────────────────────────────
function DrawStateMachine({ state, countdown }) {
  if (!state) {
    return (
      <div className="p-6 text-center text-sm text-slate-400">
        No draw state for current week. Run preparation to begin.
      </div>
    )
  }

  const steps = [
    { key: 'prep',      label: 'Preparation',   done: state.preparation_valid,  time: state.preparation_completed_at },
    { key: 'countdown', label: 'Countdown Live', done: state.countdown_active,   time: null },
    { key: 'draw',      label: 'Draw Executed',  done: state.draw_executed,      time: null },
  ]

  return (
    <div className="p-6 space-y-4">
      {/* State steps */}
      <div className="flex items-center gap-0">
        {steps.map((s, i) => (
          <div key={s.key} className="flex items-center flex-1">
            <div className="flex flex-col items-center flex-1">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 ${
                s.done
                  ? 'bg-emerald-500 border-emerald-500'
                  : 'bg-white border-slate-300'
              }`}>
                {s.done
                  ? <CheckCircle2 className="w-4 h-4 text-white" />
                  : <span className="text-xs font-bold text-slate-400">{i + 1}</span>
                }
              </div>
              <p className={`text-[10px] font-semibold mt-1 text-center ${s.done ? 'text-emerald-600' : 'text-slate-400'}`}>
                {s.label}
              </p>
            </div>
            {i < steps.length - 1 && (
              <div className={`flex-1 h-0.5 mx-1 ${
                steps[i + 1].done || s.done ? 'bg-emerald-300' : 'bg-slate-200'
              }`} />
            )}
          </div>
        ))}
      </div>

      {/* Key facts row */}
      <div className="grid grid-cols-3 gap-3">
        <Chip label="Week ID"         value={state.week_id || '—'}                     accent="slate" />
        <Chip label="LPI Snapshot"    value={`${fP(state.lpi_snapshot).toFixed(1)}%`}  accent={fP(state.lpi_snapshot) >= 25 ? 'amber' : 'green'} />
        <Chip label="SDE Sessions"    value={`${state.sde_sessions_planned || 0} planned`} accent="blue" />
        <Chip label="Float Projection" value={INR(state.float_projection_inr)}          accent="slate" />
        <Chip label="Override Needed" value={state.admin_override_required ? 'YES' : 'No'} accent={state.admin_override_required ? 'red' : 'green'} />
        <Chip label="Type-B Streak"   value={`${state.consecutive_type_b_weeks || 0} week(s)`} accent={state.consecutive_type_b_weeks >= 2 ? 'amber' : 'slate'} />
      </div>

      {/* Countdown */}
      {countdown?.countdown_active && countdown.remaining_seconds != null && (
        <div className="flex items-center gap-3 bg-violet-50 border border-violet-200 rounded-xl px-4 py-3">
          <Timer className="w-4 h-4 text-violet-600 flex-shrink-0" />
          <div className="flex-1">
            <p className="text-xs font-bold text-violet-700">Countdown Active</p>
            <p className="text-[10px] text-violet-500 mt-0.5">
              Draw in {Math.floor(countdown.remaining_seconds / 3600)}h {Math.floor((countdown.remaining_seconds % 3600) / 60)}m ·
              {' '}{fmt(countdown.draw_time_utc)} UTC
            </p>
          </div>
        </div>
      )}

      {state.draw_time_utc && (
        <p className="text-[10px] text-slate-400">
          Scheduled draw: <span className="text-slate-600 font-semibold">{fmt(state.draw_time_utc)}</span>
        </p>
      )}
    </div>
  )
}

// ─── Admin Override Panel ─────────────────────────────────────────────────────
function OverridePanel({ dashboard, weekId, onDecision }) {
  const [submitting, setSubmitting] = useState(null)
  const toast = useToast()

  if (!dashboard || !dashboard.admin_override_required) {
    return (
      <div className="p-6 text-center">
        <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
        <p className="text-sm text-slate-400">No admin override required this week</p>
      </div>
    )
  }

  const { option_a, option_b, recommendation, time_remaining_seconds, overflow_l4_count, current_choice } = dashboard

  const handleChoice = async (choice) => {
    setSubmitting(choice)
    try {
      await submitOverrideDecision(choice, weekId)
      toast(`Override applied: ${choice === 'option_a' ? 'Option A (probabilistic)' : 'Option B (certain)'}`, 'success')
      onDecision()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Override failed', 'error')
    } finally {
      setSubmitting(null)
    }
  }

  const hours = Math.floor((time_remaining_seconds || 0) / 3600)
  const mins  = Math.floor(((time_remaining_seconds || 0) % 3600) / 60)
  const isOverdue = (time_remaining_seconds || 0) <= 0

  return (
    <div className="p-6 space-y-4">
      {/* Urgency banner */}
      <div className={`flex items-start gap-3 rounded-xl px-4 py-3 border ${
        isOverdue ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'
      }`}>
        <AlertTriangle className={`w-4 h-4 flex-shrink-0 mt-0.5 ${isOverdue ? 'text-red-500' : 'text-amber-500'}`} />
        <div>
          <p className={`text-sm font-bold ${isOverdue ? 'text-red-700' : 'text-amber-700'}`}>
            {isOverdue ? 'Override deadline PASSED — auto-select imminent' : 'Admin Decision Required'}
          </p>
          <p className={`text-xs mt-0.5 ${isOverdue ? 'text-red-500' : 'text-amber-600'}`}>
            {overflow_l4_count} L4 member(s) cannot be cleared by SDE. Choose how to handle them.
            {!isOverdue && ` Time remaining: ${hours}h ${mins}m`}
          </p>
        </div>
      </div>

      {/* Auto-resolve deadline ring — visible when override not yet applied */}
      {!current_choice && !isOverdue && (
        <OverrideDeadlineRing timeRemainingSeconds={time_remaining_seconds || 0} />
      )}

      {current_choice && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-2 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          <p className="text-sm font-semibold text-emerald-700">
            Applied: {current_choice === 'option_a' ? 'Option A (probabilistic)' : 'Option B (certain)'}
          </p>
        </div>
      )}

      {/* Option cards */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { key: 'option_a', label: 'Option A', sub: 'Probabilistic', data: option_a,
            desc: 'Let overflow L4 members draw normally this week. Risk: ~16.7% each advances to L5.',
            costLabel: 'Expected Extra Cost', cost: INR(option_a?.expected_extra_cost_inr ?? 0),
            accent: recommendation === 'A' ? 'green' : 'slate' },
          { key: 'option_b', label: 'Option B', sub: 'Certain cost',  data: option_b,
            desc: 'Promote overflow L4 → L5 now. Cleared via SDE next week.',
            costLabel: 'Certain Extra Cost',  cost: INR(option_b?.certain_extra_cost_inr  ?? 0),
            accent: recommendation === 'B' ? 'red' : 'slate' },
        ].map(opt => {
          const isRec = (opt.key === 'option_a' && recommendation === 'A') || (opt.key === 'option_b' && recommendation === 'B')
          return (
            <div key={opt.key} className={`rounded-2xl border-2 p-4 space-y-3 transition-all ${
              current_choice === opt.key
                ? 'border-emerald-400 bg-emerald-50'
                : isRec
                  ? 'border-blue-300 bg-blue-50'
                  : 'border-slate-200 bg-white'
            }`}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-bold text-slate-800 text-sm">{opt.label}</p>
                  <p className="text-[10px] text-slate-500">{opt.sub}</p>
                </div>
                {isRec && (
                  <span className="text-[9px] font-black bg-blue-100 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded-full">
                    RECOMMENDED
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">{opt.desc}</p>
              <div>
                <p className="text-[10px] text-slate-400">{opt.costLabel}</p>
                <p className="text-lg font-black text-slate-800">{opt.cost}</p>
              </div>
              <button
                onClick={() => handleChoice(opt.key)}
                disabled={!!submitting || !!current_choice}
                className={`w-full py-2 rounded-xl text-xs font-bold transition ${
                  current_choice === opt.key
                    ? 'bg-emerald-500 text-white cursor-default'
                    : submitting === opt.key
                      ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                      : 'bg-slate-800 hover:bg-slate-700 text-white'
                } disabled:opacity-50`}
              >
                {submitting === opt.key ? <Spinner className="w-3.5 h-3.5 inline mr-1" /> : null}
                {current_choice === opt.key ? 'Applied' : `Apply ${opt.label}`}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Scheduler Status ─────────────────────────────────────────────────────────
function SchedulerStatus({ status }) {
  if (!status) return <div className="p-4 text-sm text-slate-400">Fetching scheduler...</div>

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${status.running ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
        <p className={`text-sm font-bold ${status.running ? 'text-emerald-700' : 'text-red-600'}`}>
          {status.running ? 'Scheduler Running' : 'Scheduler Stopped'}
        </p>
        <span className="text-[10px] text-slate-400 ml-auto">{status.enabled ? 'SCHEDULER_ENABLED=true' : 'SCHEDULER_ENABLED=false'}</span>
      </div>

      {!status.running && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 text-xs text-amber-700">
          Set <code className="font-mono bg-amber-100 px-1 rounded">SCHEDULER_ENABLED=true</code> in Render env vars to activate autonomous draw scheduling.
        </div>
      )}

      {/* Schedule config */}
      {status.schedule && (
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: 'Preparation', value: status.schedule.prep_utc },
            { label: 'Draw', value: status.schedule.draw_utc },
            { label: 'Cleanup', value: status.schedule.cleanup_utc },
          ].map(s => (
            <div key={s.label} className="bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-center">
              <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">{s.label}</p>
              <p className="text-xs font-bold text-slate-700 font-mono">{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Job list */}
      {status.jobs?.length > 0 && (
        <div className="rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="text-left px-3 py-2 font-semibold text-slate-400 uppercase tracking-wider text-[10px]">Job</th>
                <th className="text-right px-3 py-2 font-semibold text-slate-400 uppercase tracking-wider text-[10px]">Next Run (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {status.jobs.map((j, i) => (
                <tr key={j.id} className={`border-b last:border-0 border-slate-100 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50/30'}`}>
                  <td className="px-3 py-2 text-slate-600 font-medium">{j.name}</td>
                  <td className="px-3 py-2 text-right font-mono text-slate-500">{j.next_run ? fmt(j.next_run) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Manual Controls ──────────────────────────────────────────────────────────
function ManualControls({ onRefresh }) {
  const toast       = useToast()
  const [preparing, setPreparing]   = useState(false)
  const [executing,  setExecuting]  = useState(false)
  const [cleaning,   setCleaning]   = useState(false)
  const [prepDt,     setPrepDt]     = useState('')

  const handlePrepare = async () => {
    if (!prepDt) { toast('Enter a draw date/time first', 'warning'); return }
    setPreparing(true)
    try {
      const res = await prepareWeeklyDraw(new Date(prepDt).toISOString())
      toast(`Preparation complete — week ${res.data.week_id}`, 'success')
      onRefresh()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Preparation failed', 'error')
    } finally {
      setPreparing(false) }
  }

  const handleExecute = async () => {
    setExecuting(true)
    try {
      const res = await manualExecuteDraw()
      toast(`Draw complete — ${res.data.pools_drawn} pool(s) drawn`, 'success')
      onRefresh()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Draw execution failed', 'error')
    } finally {
      setExecuting(false) }
  }

  const handleCleanup = async () => {
    setCleaning(true)
    try {
      await triggerPostDrawCleanup()
      toast('Post-draw cleanup complete', 'success')
      onRefresh()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Cleanup failed', 'error')
    } finally {
      setCleaning(false) }
  }

  // Default draw time: next Sunday 13:30 UTC
  const nextSundayDraw = () => {
    const now = new Date()
    const dayOfWeek = now.getUTCDay()
    const daysUntilSunday = dayOfWeek === 0 ? 7 : 7 - dayOfWeek
    const next = new Date(now)
    next.setUTCDate(now.getUTCDate() + daysUntilSunday)
    next.setUTCHours(13, 30, 0, 0)
    return next.toISOString().slice(0, 16)
  }

  return (
    <div className="p-6 space-y-4">
      {/* Prepare */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-slate-600">1. T-2H Draw Preparation</p>
        <div className="flex gap-2">
          <input
            type="datetime-local"
            value={prepDt}
            onChange={e => setPrepDt(e.target.value)}
            className="flex-1 bg-white border border-slate-200 rounded-xl px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-violet-400"
          />
          <button
            onClick={() => setPrepDt(nextSundayDraw())}
            className="text-xs text-violet-600 hover:text-violet-800 border border-violet-200 rounded-xl px-3 py-2 transition bg-violet-50"
          >
            Auto
          </button>
        </div>
        <button
          onClick={handlePrepare}
          disabled={preparing || !prepDt}
          className="w-full flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-700 disabled:bg-slate-200 disabled:text-slate-400 text-white font-bold py-2.5 rounded-xl transition text-sm"
        >
          {preparing ? <Spinner className="w-4 h-4" /> : <Settings className="w-4 h-4" />}
          {preparing ? 'Preparing…' : 'Run Preparation (T-2H)'}
        </button>
      </div>

      <div className="border-t border-slate-100" />

      {/* Execute */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-slate-600">2. Execute Weekly Draw</p>
        <p className="text-[10px] text-slate-400">Runs all eligible full pools. Auto-selects override if deadline passed.</p>
        <button
          onClick={handleExecute}
          disabled={executing}
          className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-200 disabled:text-slate-400 text-white font-bold py-2.5 rounded-xl transition text-sm"
        >
          {executing ? <Spinner className="w-4 h-4" /> : <Play className="w-4 h-4" />}
          {executing ? 'Executing Draw…' : 'Execute Weekly Draw'}
        </button>
      </div>

      <div className="border-t border-slate-100" />

      {/* Cleanup */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-slate-600">3. Post-Draw Cleanup (T+5 min)</p>
        <p className="text-[10px] text-slate-400">Resets weekly flags, releases draw lock, clears SDE state.</p>
        <button
          onClick={handleCleanup}
          disabled={cleaning}
          className="w-full flex items-center justify-center gap-2 bg-slate-700 hover:bg-slate-600 disabled:bg-slate-200 disabled:text-slate-400 text-white font-bold py-2.5 rounded-xl transition text-sm"
        >
          {cleaning ? <Spinner className="w-4 h-4" /> : <RotateCcw className="w-4 h-4" />}
          {cleaning ? 'Cleaning…' : 'Run Post-Draw Cleanup'}
        </button>
      </div>
    </div>
  )
}


// ─── Module 3: T-2H War Room Banner ──────────────────────────────────────────
// Auto-activates when BOTH preparation_valid=true AND countdown_active=true.
// Shows a live countdown timer that ticks locally between 30-s server polls.
function WarRoomBanner({ countdown, drawState }) {
  const [remSec, setRemSec] = useState(countdown?.remaining_seconds ?? 0)

  // Sync when server sends updated value
  useEffect(() => {
    if (countdown?.remaining_seconds != null) setRemSec(countdown.remaining_seconds)
  }, [countdown?.remaining_seconds])

  // Local 1-s tick while active
  useEffect(() => {
    if (!countdown?.countdown_active || !countdown?.preparation_valid) return
    const id = setInterval(() => setRemSec(s => Math.max(0, s - 1)), 1000)
    return () => clearInterval(id)
  }, [countdown?.countdown_active, countdown?.preparation_valid])

  if (!countdown?.countdown_active || !countdown?.preparation_valid) return null

  const h = Math.floor(remSec / 3600)
  const m = Math.floor((remSec % 3600) / 60)
  const s = remSec % 60

  return (
    <div className="relative rounded-2xl overflow-hidden border-2 border-red-700/60 bg-slate-950">
      {/* Animated sweep background */}
      <div className="absolute inset-0 bg-gradient-to-r from-red-950/0 via-red-900/15 to-red-950/0"
           style={{ animation: 'pulse 2s ease-in-out infinite' }}/>
      <div className="relative z-10 px-6 py-5">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          {/* Left: status badge */}
          <div className="flex items-center gap-3">
            <span className="w-3.5 h-3.5 rounded-full bg-red-500"
                  style={{ boxShadow: '0 0 10px #ef4444', animation: 'ping 1s ease-in-out infinite' }}/>
            <div>
              <p className="text-[10px] font-black text-red-400 uppercase tracking-[0.3em]">
                ⚔ WAR ROOM ACTIVE ⚔
              </p>
              <p className="text-[10px] text-slate-500 mt-0.5">
                Draw at {countdown.draw_time_utc
                  ? new Date(countdown.draw_time_utc).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
                  : '—'}
              </p>
            </div>
          </div>

          {/* Center: big countdown */}
          <div className="text-center">
            <div className="text-5xl font-black text-white font-mono tabular-nums tracking-widest"
                 style={{ textShadow: '0 0 20px rgba(239,68,68,0.5)' }}>
              {String(h).padStart(2,'0')}:{String(m).padStart(2,'0')}:{String(s).padStart(2,'0')}
            </div>
            <p className="text-[10px] text-slate-500 mt-1 font-mono uppercase tracking-widest">
              until draw execution
            </p>
          </div>

          {/* Right: override alert */}
          <div>
            {drawState?.admin_override_required ? (
              <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-950/60 border border-amber-700/60 rounded-xl text-amber-300 text-xs font-black animate-pulse">
                <AlertTriangle className="w-4 h-4 flex-shrink-0"/>
                OVERRIDE DECISION REQUIRED
              </div>
            ) : (
              <div className="flex items-center gap-2 px-4 py-2.5 bg-emerald-950/40 border border-emerald-700/40 rounded-xl text-emerald-400 text-xs font-semibold">
                <Shield className="w-4 h-4 flex-shrink-0"/>
                System nominal
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Override Deadline Ring (Auto-resolve ring countdown) ─────────────────────
function OverrideDeadlineRing({ timeRemainingSeconds = 7200 }) {
  const total  = 7200   // 2 hours
  const pct    = Math.max(0, Math.min(1, timeRemainingSeconds / total))
  const r = 40, cx = 50, cy = 50
  const circ = 2 * Math.PI * r
  const dash  = circ * pct

  const color  = pct > 0.5 ? '#10b981' : pct > 0.25 ? '#f59e0b' : '#ef4444'
  const h = Math.floor(timeRemainingSeconds / 3600)
  const m = Math.floor((timeRemainingSeconds % 3600) / 60)

  return (
    <div className="flex items-center gap-4 bg-slate-50 border border-slate-200 rounded-xl px-4 py-3">
      {/* Ring */}
      <div className="flex-shrink-0">
        <svg width="70" height="70" viewBox="0 0 100 100">
          <circle cx={cx} cy={cy} r={r} fill="none" stroke="#e2e8f0" strokeWidth="8"/>
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="8"
                  strokeLinecap="round" strokeDasharray={`${dash} ${circ}`}
                  transform={`rotate(-90 ${cx} ${cy})`}
                  style={{ transition: 'stroke-dasharray 1s linear, stroke 0.4s' }}
                  className={pct <= 0.1 ? 'animate-pulse' : ''}/>
          <text x={cx} y={cy - 3} textAnchor="middle" fontSize="12" fontWeight="800"
                fill={color} fontFamily="ui-monospace,monospace">
            {String(h).padStart(2,'0')}:{String(m).padStart(2,'0')}
          </text>
          <text x={cx} y={cy + 11} textAnchor="middle" fontSize="7" fill="#94a3b8">left</text>
        </svg>
      </div>

      {/* Text */}
      <div>
        <p className="text-xs font-bold text-slate-700">Auto-Resolve Ring</p>
        <p className={`text-[10px] mt-0.5 ${
          pct <= 0.1 ? 'text-red-600 font-bold animate-pulse' :
          pct <= 0.25 ? 'text-amber-600 font-semibold' : 'text-slate-400'
        }`}>
          {pct <= 0.1
            ? '🚨 Imminent auto-resolve — decide now'
            : pct <= 0.25
              ? '⚠ Time running critically low'
              : `${h}h ${m}m until system auto-resolves`}
        </p>
        {pct <= 0.1 && (
          <p className="text-[9px] text-red-500 mt-1 font-mono">
            [SYSTEM AUTO-RESOLVED DUE TO ADMIN TIMEOUT]
          </p>
        )}
      </div>
    </div>
  )
}

// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
// ─── Module 4: Master Pool Re-assessment — virtual pre-deployment integrity gate ─
// Renders the verdict produced at T-2H (STEP 8b) by app/services/pool_reassessor.py:
// it virtually dissolves EVERY pool, projects the whole week's winner set, and
// cross-verifies the "purity of the draw" against five financial-grade checks.
// THREE checks are HARD gates (float-solvency, pyramid-sustainability,
// reconciliation) — any one failing → HOLD → the real draw is refused at T-0H
// until an admin clears it here.  TWO are diagnostics (purity, level-advancement)
// that drive the corrected plan but never freeze a mature week alone.
//
// Backend is already deployed (additive endpoints) so this panel is fully
// defensive: empty-state when no report exists, never throws on missing fields.

const _RA_LEVELS = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']

// One gate tile: hard gates carry money/integrity weight, diagnostics are advisory.
function RaGateTile({ label, ok, hard, Icon }) {
  const isHardFail = hard && !ok
  const tone = ok
    ? 'border-emerald-200 bg-emerald-50'
    : hard
      ? 'border-red-300 bg-red-50'
      : 'border-amber-200 bg-amber-50'
  const txt = ok ? 'text-emerald-700' : hard ? 'text-red-700' : 'text-amber-700'
  return (
    <div className={`border rounded-xl px-3 py-2.5 ${tone} ${isHardFail ? 'ring-2 ring-red-400/40' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <div className={`flex items-center gap-1.5 ${txt}`}>
          <Icon className="w-3.5 h-3.5 flex-shrink-0" />
          <span className="text-[11px] font-bold leading-tight">{label}</span>
        </div>
        {ok
          ? <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
          : <XCircle className={`w-4 h-4 flex-shrink-0 ${hard ? 'text-red-600' : 'text-amber-600'}`} />}
      </div>
      <p className="text-[9px] font-semibold uppercase tracking-wider mt-1 opacity-60">
        {hard ? 'Hard gate' : 'Diagnostic'} · {ok ? 'PASS' : 'FAIL'}
      </p>
    </div>
  )
}

// Member-vs-winner pyramid: side-by-side bars per level. The "315 L4 winners but
// only 80 members" signature shows up here as a winner bar overshooting members.
function RaPyramid({ member = {}, winner = {} }) {
  const peak = Math.max(
    1,
    ..._RA_LEVELS.map(l => Math.max(Number(member[l] ?? 0), Number(winner[l] ?? 0))),
  )
  return (
    <div className="space-y-2">
      {_RA_LEVELS.map(l => {
        const mv = Number(member[l] ?? 0)
        const wv = Number(winner[l] ?? 0)
        const high = l === 'L4' || l === 'L5' || l === 'L6'
        const impossible = wv > mv   // projecting more winners than members exist
        return (
          <div key={l} className="flex items-center gap-2">
            <span className={`text-[11px] font-bold w-6 ${high ? 'text-red-600' : 'text-slate-500'}`}>{l}</span>
            <div className="flex-1 space-y-1">
              {/* members */}
              <div className="flex items-center gap-1.5">
                <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full bg-slate-400 rounded-full transition-all"
                       style={{ width: `${(mv / peak) * 100}%` }} />
                </div>
                <span className="text-[10px] font-mono text-slate-500 w-9 text-right tabular-nums">{mv}</span>
              </div>
              {/* winners */}
              <div className="flex items-center gap-1.5">
                <div className="flex-1 h-2.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full transition-all ${impossible ? 'bg-red-500' : high ? 'bg-violet-500' : 'bg-violet-400'}`}
                       style={{ width: `${Math.min(100, (wv / peak) * 100)}%` }} />
                </div>
                <span className={`text-[10px] font-mono w-9 text-right tabular-nums ${impossible ? 'text-red-600 font-bold' : 'text-violet-600'}`}>{wv}</span>
              </div>
            </div>
            {impossible && (
              <span title="More projected winners than members exist at this level — impossible-data signature"
                    className="text-[9px] font-black text-red-600">⚠</span>
            )}
          </div>
        )
      })}
      <div className="flex items-center gap-4 pt-1">
        <span className="flex items-center gap-1 text-[9px] text-slate-400">
          <span className="w-3 h-2 rounded-full bg-slate-400 inline-block" /> Members
        </span>
        <span className="flex items-center gap-1 text-[9px] text-slate-400">
          <span className="w-3 h-2 rounded-full bg-violet-500 inline-block" /> Projected winners
        </span>
      </div>
    </div>
  )
}

function ReassessmentPanel({ weekId, onChanged }) {
  const toast = useToast()
  const [report,     setReport]     = useState(null)
  const [exists,     setExists]     = useState(false)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(null)

  // approve modal
  const [modalMode,  setModalMode]  = useState(null)   // 'reassess' | 'override' | null
  const [password,   setPassword]   = useState('')
  const [note,       setNote]       = useState('')
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(async () => {
    if (!weekId) { setLoading(false); return }
    setLoading(true)
    try {
      const res = await getReassessment(weekId)
      setExists(Boolean(res.data?.exists))
      setReport(res.data?.report ?? null)
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail ?? 'Failed to load re-assessment')
      setReport(null)
      setExists(false)
    } finally {
      setLoading(false)
    }
  }, [weekId])

  useEffect(() => { load() }, [load])

  const closeModal = () => { setModalMode(null); setPassword(''); setNote('') }

  const submitApprove = async () => {
    if (!password) { toast('Admin password required', 'error'); return }
    if (modalMode === 'override' && !note.trim()) {
      toast('Override requires a justification note', 'error'); return
    }
    setSubmitting(true)
    try {
      const res = await approveReassessment(weekId, password, {
        override:  modalMode === 'override',
        adminNote: note.trim() || undefined,
      })
      const d = res.data ?? {}
      if (d.cleared) toast(d.message || 'HOLD cleared — draw may deploy.', 'success')
      else           toast(d.message || 'Re-assessment still holds.', 'error')
      closeModal()
      await load()
      onChanged?.()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Approval failed', 'error')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Empty / loading / error states (fully defensive) ──────────────────────
  if (loading) {
    return (
      <SectionCard title="Master Pool Re-assessment" icon={ShieldCheck} iconColor="text-violet-500" badge="VIRTUAL GATE">
        <div className="flex items-center justify-center h-24">
          <Spinner className="w-6 h-6 text-violet-400" />
        </div>
      </SectionCard>
    )
  }
  if (error) {
    return (
      <SectionCard title="Master Pool Re-assessment" icon={ShieldAlert} iconColor="text-red-500" badge="VIRTUAL GATE">
        <div className="p-6 text-sm text-red-600 flex items-center gap-2">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      </SectionCard>
    )
  }
  if (!exists || !report) {
    return (
      <SectionCard title="Master Pool Re-assessment" icon={ShieldCheck} iconColor="text-violet-500" badge="VIRTUAL GATE">
        <div className="p-6 text-center">
          <Shield className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm font-semibold text-slate-500">
            No re-assessment yet for {weekId || 'this week'}.
          </p>
          <p className="text-xs text-slate-400 mt-1">
            The virtual integrity gate runs automatically at T-2H draw preparation
            (STEP 8b). It dissolves every pool, projects the full week, and cross-verifies
            draw purity before any real draw is allowed to deploy.
          </p>
        </div>
      </SectionCard>
    )
  }

  // ── Loaded ────────────────────────────────────────────────────────────────
  const isHold     = report.verdict === 'HOLD'
  const activeHold = report.is_active_hold
  const g          = report.gates ?? {}
  const fin        = report.financials ?? {}
  const headroom   = Number(fin.headroom_inr ?? 0)
  const audit      = report.audit ?? {}
  const plan       = Array.isArray(report.corrected_plan) ? report.corrected_plan : []
  const approval   = report.approval ?? {}
  const fAudit     = audit.float    ?? {}
  const pAudit     = audit.pyramid  ?? {}
  const purAudit   = audit.purity   ?? {}

  return (
    <>
      <SectionCard
        title="Master Pool Re-assessment"
        icon={activeHold ? ShieldAlert : ShieldCheck}
        iconColor={activeHold ? 'text-red-500' : 'text-emerald-500'}
        badge="VIRTUAL GATE"
        action={
          <button onClick={load}
                  className="text-[11px] font-medium text-slate-400 hover:text-slate-600 flex items-center gap-1">
            <RefreshCw className="w-3 h-3" /> {weekId}
          </button>
        }
      >
        <div className="p-5 space-y-5">

          {/* ── Verdict banner ── */}
          <div className={`rounded-xl px-5 py-4 flex items-center justify-between gap-4 flex-wrap border-2 ${
            activeHold ? 'border-red-300 bg-red-50'
            : isHold    ? 'border-amber-300 bg-amber-50'
            : 'border-emerald-300 bg-emerald-50'
          }`}>
            <div className="flex items-center gap-3">
              {activeHold
                ? <ShieldAlert className="w-8 h-8 text-red-600 flex-shrink-0" />
                : <ShieldCheck className="w-8 h-8 text-emerald-600 flex-shrink-0" />}
              <div>
                <p className={`text-lg font-black leading-none ${
                  activeHold ? 'text-red-700' : isHold ? 'text-amber-700' : 'text-emerald-700'
                }`}>
                  {activeHold ? '🛑 DRAW HELD' : isHold ? 'HOLD (cleared)' : '✓ DRAW CLEARED TO DEPLOY'}
                </p>
                <p className="text-[11px] text-slate-500 mt-1">
                  Verdict <b>{report.verdict}</b> · report #{report.id} · assessed {fmt(report.run_at)}
                  {report.failed_hard_gates?.length > 0 && (
                    <> · failed: <b className="text-red-600">{report.failed_hard_gates.join(', ')}</b></>
                  )}
                </p>
              </div>
            </div>
            {activeHold && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setModalMode('reassess')}
                  className="flex items-center gap-1.5 px-3.5 py-2 bg-violet-600 hover:bg-violet-700 text-white text-xs font-bold rounded-lg transition">
                  <RefreshCw className="w-3.5 h-3.5" /> Re-assess on current data
                </button>
                <button
                  onClick={() => setModalMode('override')}
                  className="flex items-center gap-1.5 px-3.5 py-2 bg-white border border-red-300 hover:bg-red-50 text-red-700 text-xs font-bold rounded-lg transition">
                  <Lock className="w-3.5 h-3.5" /> Override &amp; deploy
                </button>
              </div>
            )}
          </div>

          {/* ── Five gates ── */}
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">Integrity checks</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
              <RaGateTile label="Float Solvency"        ok={g.float_pass}         hard Icon={IndianRupee} />
              <RaGateTile label="Pyramid Sustainability" ok={g.pyramid_pass}      hard Icon={Layers} />
              <RaGateTile label="Reconciliation"         ok={g.reconcile_pass}    hard Icon={Database} />
              <RaGateTile label="Draw Purity"            ok={g.purity_pass}             Icon={Scale} />
              <RaGateTile label="Level Advancement"      ok={g.level_advance_pass}      Icon={TrendingUp} />
            </div>
          </div>

          {/* ── Financials + Pyramid ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

            {/* Financials */}
            <div className="space-y-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Float gate (solvency)</p>
              <div className="grid grid-cols-2 gap-2">
                <Chip label="Projected payout" value={INR(fin.projected_payout_inr)} accent="amber" />
                <Chip label="Available float"  value={INR(fin.available_float_inr)} accent="blue" />
                <Chip label="Net float"        value={INR(fin.net_float_inr)} accent="slate" />
                <Chip label="Headroom"         value={INR(headroom)} accent={headroom >= 0 ? 'green' : 'red'} />
              </div>
              <div className="text-[10px] text-slate-400 space-y-0.5 pt-1 font-mono">
                {fAudit.reserve_inr != null && <p>reserve held: {INR(fAudit.reserve_inr)}</p>}
                {fAudit.worstcase_payout_inr != null && fAudit.composition_payout_inr != null && (
                  <p>payout = max(composition {INR(fAudit.composition_payout_inr)}, worst-case {INR(fAudit.worstcase_payout_inr)})</p>
                )}
              </div>

              {/* pyramid audit numbers */}
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400 pt-2">Pyramid gate (held-L4 backlog)</p>
              <div className="grid grid-cols-2 gap-2">
                <Chip label="Flagged L4 now" value={pAudit.flagged_l4_now ?? '—'} accent={(pAudit.flagged_l4_now ?? 0) > 0 ? 'red' : 'slate'} />
                <Chip label="L4 cleared"     value={pAudit.l4_cleared ?? '—'} accent="violet" />
                <Chip label="Backlog after"  value={pAudit.l4_backlog_after ?? '—'} accent={(pAudit.l4_backlog_after ?? 0) > 0 ? 'amber' : 'green'} />
                <Chip label="Clear capacity" value={pAudit.clear_capacity ?? '—'} accent="slate" />
              </div>
            </div>

            {/* Pyramid bars */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Member vs projected-winner pyramid</p>
                {purAudit.over_representation != null && (
                  <span className={`text-[10px] font-bold ${g.purity_pass ? 'text-slate-400' : 'text-amber-600'}`}>
                    high-tier over-rep {purAudit.over_representation}×
                  </span>
                )}
              </div>
              <RaPyramid member={report.member_pyramid} winner={report.winner_pyramid} />
            </div>
          </div>

          {/* ── Corrected plan ── */}
          {plan.length > 0 && (
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
                <ListChecks className="w-3.5 h-3.5" /> Proposed corrected plan
              </p>
              <div className="space-y-2">
                {plan.map((step, i) => {
                  const crit = step.severity === 'critical'
                  return (
                    <div key={i} className={`rounded-lg border px-3.5 py-2.5 ${
                      crit ? 'border-red-200 bg-red-50/60' : 'border-amber-200 bg-amber-50/60'
                    }`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-[9px] font-black uppercase px-1.5 py-0.5 rounded ${
                          crit ? 'bg-red-200 text-red-800' : 'bg-amber-200 text-amber-800'
                        }`}>{step.gate}</span>
                        <span className={`text-[9px] font-bold uppercase ${crit ? 'text-red-500' : 'text-amber-600'}`}>
                          {step.severity}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-700 font-medium">{step.finding}</p>
                      <p className="text-[11px] text-slate-600 mt-1">→ {step.action}</p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ── Approval audit footer ── */}
          {approval.approved && (
            <div className="text-[10px] text-slate-400 border-t border-slate-100 pt-3 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
              Cleared by <b className="text-slate-600">{approval.approved_by || '—'}</b> at {fmt(approval.approved_at)}
              {approval.admin_note && <> · note: “{approval.admin_note}”</>}
            </div>
          )}
        </div>
      </SectionCard>

      {/* ── Password-confirm modal (re-assess vs override) ── */}
      {modalMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
             onClick={() => !submitting && closeModal()}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6"
               onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-1">
              {modalMode === 'override'
                ? <Lock className="w-5 h-5 text-red-600" />
                : <RefreshCw className="w-5 h-5 text-violet-600" />}
              <h3 className="text-lg font-bold text-slate-900">
                {modalMode === 'override' ? 'Override & Deploy' : 'Re-assess on Current Data'}
              </h3>
            </div>
            <p className="text-xs text-slate-500 mb-4">
              {modalMode === 'override'
                ? 'You are explicitly ACCEPTING the risk and clearing the HOLD as-prepared. The prepared draw will deploy at the next execution. A justification note is required for the audit trail.'
                : 'Re-runs the full virtual gate against the CURRENT data. The HOLD clears only if the fresh verdict is PASS — approval is re-verification, not a rubber stamp.'}
            </p>

            <label className="block text-[11px] font-semibold text-slate-600 mb-1">Admin password</label>
            <input
              type="password"
              autoFocus
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') submitApprove() }}
              disabled={submitting}
              placeholder="••••••••"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-400 focus:border-violet-400 outline-none disabled:opacity-50"
            />

            <label className="block text-[11px] font-semibold text-slate-600 mt-3 mb-1">
              Reviewer note {modalMode === 'override'
                ? <span className="text-red-500">(required)</span>
                : <span className="text-slate-400">(optional)</span>}
            </label>
            <textarea
              value={note}
              onChange={e => setNote(e.target.value)}
              disabled={submitting}
              rows={2}
              maxLength={2000}
              placeholder={modalMode === 'override' ? 'Why is it safe to override this HOLD?' : 'Optional context for the audit trail'}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-violet-400 focus:border-violet-400 outline-none resize-none disabled:opacity-50"
            />

            <div className="flex items-center gap-2 mt-5">
              <button onClick={closeModal} disabled={submitting}
                      className="flex-1 px-4 py-2 border border-slate-200 rounded-lg text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 transition">
                Cancel
              </button>
              <button onClick={submitApprove} disabled={submitting}
                      className={`flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-bold text-white transition disabled:opacity-50 ${
                        modalMode === 'override' ? 'bg-red-600 hover:bg-red-700' : 'bg-violet-600 hover:bg-violet-700'
                      }`}>
                {submitting ? <Spinner className="w-4 h-4" /> : modalMode === 'override' ? <Lock className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
                {submitting ? 'Working…' : modalMode === 'override' ? 'Override & Deploy' : 'Re-assess'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function DrawEngine() {
  const toast = useToast()
  const [loading,    setLoading]    = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastUp,     setLastUp]     = useState(null)

  // Data state
  const [lpiData,     setLpiData]     = useState(null)
  const [drawState,   setDrawState]   = useState(null)
  const [countdown,   setCountdown]   = useState(null)
  const [override,    setOverride]    = useState(null)
  const [scheduler,   setScheduler]   = useState(null)

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)

    try {
      const [lpiR, stateR, cntR, schedR] = await Promise.allSettled([
        getBrain5Lpi(),
        getDrawState(),
        getDrawCountdown(),
        getSchedulerStatus(),
      ])

      if (lpiR.status   === 'fulfilled') setLpiData(lpiR.value.data)
      if (stateR.status === 'fulfilled') setDrawState(stateR.value.data)
      if (cntR.status   === 'fulfilled') setCountdown(cntR.value.data)
      if (schedR.status === 'fulfilled') setScheduler(schedR.value.data)

      // Fetch override for current week if needed
      try {
        const now  = new Date()
        const iso  = now.toISOString()
        const yr   = now.getFullYear()
        const wk   = getISOWeek(now)
        const wid  = `${yr}-W${String(wk).padStart(2,'0')}`
        const oR   = await getOverrideDashboard(wid)
        setOverride(oR.data)
      } catch { setOverride(null) }

    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to load draw engine data', 'error')
    } finally {
      setLoading(false)
      setRefreshing(false)
      setLastUp(new Date())
    }
  }, [toast])

  useEffect(() => { fetchAll() }, [fetchAll])

  // Auto-refresh every 30s if countdown is active
  useEffect(() => {
    if (!countdown?.countdown_active) return
    const iv = setInterval(() => fetchAll(true), 30_000)
    return () => clearInterval(iv)
  }, [countdown?.countdown_active, fetchAll])

  // ISO week helper
  function getISOWeek(d) {
    const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
    const dayNum = date.getUTCDay() || 7
    date.setUTCDate(date.getUTCDate() + 4 - dayNum)
    const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1))
    return Math.ceil((((date - yearStart) / 86400000) + 1) / 7)
  }

  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Week id for the re-assessment panel: prefer the backend's own week_id (the
  // exact key STEP 8b wrote the report under); fall back to the current ISO week.
  const currentWeekId = (() => {
    if (drawState?.week_id) return drawState.week_id
    const now = new Date()
    return `${now.getFullYear()}-W${String(getISOWeek(now)).padStart(2, '0')}`
  })()

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="p-8 space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Cpu className="w-6 h-6 text-violet-600" />
            Draw Engine
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            SDE · Brain 5 LPI · Draw Lifecycle · Scheduler
            {lastUp && <> · Last updated {lastUp.toLocaleTimeString()}</>}
          </p>
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

      {/* ── T-2H War Room auto-activation ──────────────────────────────── */}
      {countdown && (
        <WarRoomBanner countdown={countdown} drawState={drawState} />
      )}

      {/* SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
      {/* ── Master Pool Re-assessment — virtual pre-deployment integrity gate ── */}
      <ReassessmentPanel weekId={currentWeekId} onChanged={() => fetchAll(true)} />

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Spinner className="w-8 h-8 text-violet-400" />
        </div>
      ) : (
        <>
          {/* ── Row 1: LPI Gauge + Pool Type Decision ── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">

            <SectionCard title="Level Pressure Index (LPI)" icon={Activity} iconColor="text-violet-500">
              <div className="p-4">
                <LpiGauge lpi={fP(lpiData?.lpi)} />

                {lpiData && (
                  <div className="mt-4 grid grid-cols-3 gap-2">
                    {Object.entries(lpiData.level_distribution || {}).slice(0, 6).map(([k, v]) => (
                      <Chip key={k} label={k} value={v} accent={
                        k === 'l4' || k === 'l5' || k === 'l6' ? (v > 0 ? 'red' : 'slate') : 'slate'
                      } />
                    ))}
                  </div>
                )}

                {lpiData?.elevated_risk && (
                  <div className="mt-3 flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
                    <p className="text-xs text-red-600 font-semibold">Elevated Risk: L5/L6 members exist</p>
                  </div>
                )}
              </div>
            </SectionCard>

            <SectionCard title="Pool Type Routing Decision" icon={Layers} iconColor="text-blue-500">
              <PoolTypeDecision decision={lpiData?.pool_type_decision} />
              {lpiData?.sde_demand && (
                <div className="px-4 pb-4">
                  <div className="grid grid-cols-3 gap-2 bg-slate-50 rounded-xl p-3 border border-slate-100">
                    <Chip label="L4 Count"     value={lpiData.sde_demand.l4_count}         accent="amber" />
                    <Chip label="Sessions Needed" value={lpiData.sde_demand.sessions_needed} accent="blue" />
                    <Chip label="Overflow"     value={lpiData.sde_demand.overflow_count}    accent={lpiData.sde_demand.overflow_count > 0 ? 'red' : 'green'} />
                    <Chip label="L1/L2 Have"   value={lpiData.sde_demand.l1l2_available}   accent="slate" />
                    <Chip label="L1/L2 Need"   value={lpiData.sde_demand.l1l2_threshold}   accent="slate" />
                    <Chip label="Clearable"    value={lpiData.sde_demand.clearable_count}   accent="green" />
                  </div>
                </div>
              )}
            </SectionCard>
          </div>

          {/* ── Row 2: Draw State + Admin Override ── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">

            <SectionCard
              title="Weekly Draw State Machine"
              icon={Calendar}
              iconColor="text-emerald-500"
              badge={drawState?.week_id}
            >
              <DrawStateMachine state={drawState} countdown={countdown} />
            </SectionCard>

            <SectionCard
              title="Admin Override Panel"
              icon={Shield}
              iconColor="text-amber-500"
              badge={override?.admin_override_required ? 'ACTION NEEDED' : undefined}
            >
              <OverridePanel
                dashboard={override}
                weekId={drawState?.week_id}
                onDecision={() => fetchAll(true)}
              />
            </SectionCard>
          </div>

          {/* ── Row 3: Scheduler + Manual Controls ── */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">

            <SectionCard title="APScheduler Status" icon={Clock} iconColor="text-cyan-500">
              <SchedulerStatus status={scheduler} />
            </SectionCard>

            <SectionCard title="Manual Draw Controls" icon={Zap} iconColor="text-amber-500">
              <ManualControls onRefresh={() => fetchAll(true)} />
            </SectionCard>
          </div>

          {/* ── Brain 5 forward signal footer ── */}
          {lpiData?.forward_signal_l3 != null && (
            <div className="bg-blue-50 border border-blue-100 rounded-2xl px-6 py-4 flex items-center gap-4">
              <TrendingUp className="w-5 h-5 text-blue-500 flex-shrink-0" />
              <div>
                <p className="text-sm font-bold text-blue-800">Brain 5 Forward Signal</p>
                <p className="text-xs text-blue-600 mt-0.5">
                  Projected new L3 members next cycle: <strong>{fP(lpiData.forward_signal_l3).toFixed(1)}</strong>
                  {' '} · Total active: <strong>{lpiData.total_active}</strong>
                </p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
