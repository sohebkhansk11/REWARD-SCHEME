/**
 * DevTools.jsx — Developer Mode · God Mode Control Panel
 *
 * 4 tabs:
 *  0. STRESS TEST   — AI Platform Stress-Tester (1–1,000 cycles) + Pre-Test Setup
 *  1. DRAW CONTROL  — Force Draw + Time-Travel + Date controls
 *  2. INJECTION     — User injection with date/time/cadence customization
 *  3. DANGER ZONE   — Database nuclear reset
 *
 * All /dev/* calls authenticated via JWT request interceptor.
 */

import { useState, useEffect, useCallback, Fragment } from 'react'
import {
  Terminal, Zap, Clock, UserPlus, Skull, FlaskConical,
  AlertTriangle, CheckCircle2, XCircle, Play, Info, Users,
  IndianRupee, TrendingUp, GitMerge, ShieldAlert, BarChart3,
  DollarSign, Database, RefreshCw, Layers, Trophy, Target,
  Cpu, Settings, CalendarDays, Activity, ToggleLeft, ToggleRight,
  Shuffle, ChevronRight, Download, TableProperties,
} from 'lucide-react'
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid,
  Tooltip as RechartTooltip,
  Legend, ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'
import Spinner from '../components/Spinner'
import {
  forceDrawDev, simulateCycleDev, simulateUsersDev,
  resetDataDev, advancedSimulationDev,
  startRealSimulation, getRealSimStatus, getRealSimResult,
  devInjectTimed, devMarkAllPaid,
  devSetPaymentScenario, getInjectionStatus,
  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  getDebuggerStatus, toggleDebugger, getDebuggerLogs, clearDebuggerLogs,
} from '../api/client'
import { useToast } from '../context/ToastContext'

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const INR  = n => `₹${Number(n ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const NUM  = n => Number(n ?? 0).toLocaleString('en-IN')
const fP   = v => parseFloat(v ?? 0)

// ─────────────────────────────────────────────────────────────────────────────
// Shared primitive UI components (dark theme)
// ─────────────────────────────────────────────────────────────────────────────

function Toggle({ checked, onChange, label, disabled = false }) {
  return (
    <button
      type="button" role="switch" aria-checked={checked} aria-label={label}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500 ${
        checked ? 'bg-violet-600' : 'bg-slate-600'
      } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200 ${
        checked ? 'translate-x-[18px]' : 'translate-x-[3px]'
      }`} />
    </button>
  )
}

function DevCard({ icon: Icon, iconBg, iconColor, title, subtitle, children }) {
  return (
    <div className="bg-slate-900 border border-slate-700/60 rounded-2xl overflow-hidden shadow-xl shadow-black/30">
      <div className="flex items-center gap-3 px-6 py-4 border-b border-slate-700/60 bg-slate-900/80">
        <div className={`${iconBg} p-2.5 rounded-xl flex-shrink-0`}><Icon className={`w-4 h-4 ${iconColor}`} /></div>
        <div className="min-w-0">
          <p className="font-bold text-slate-100 text-sm leading-none">{title}</p>
          {subtitle && <p className="text-xs text-slate-500 mt-0.5 truncate">{subtitle}</p>}
        </div>
      </div>
      <div className="p-6">{children}</div>
    </div>
  )
}

function StatPill({ label, value, accent = 'slate' }) {
  const cls = {
    slate:'bg-slate-800 text-slate-100 border-slate-700', emerald:'bg-emerald-950 text-emerald-300 border-emerald-800',
    amber:'bg-amber-950 text-amber-300 border-amber-800',   red:'bg-red-950 text-red-300 border-red-800',
    purple:'bg-purple-950 text-purple-300 border-purple-800',blue:'bg-blue-950 text-blue-300 border-blue-800',
    cyan:'bg-cyan-950 text-cyan-300 border-cyan-800',       rose:'bg-rose-950 text-rose-300 border-rose-800',
  }[accent] ?? 'bg-slate-800 text-slate-100 border-slate-700'
  return (
    <div className={`${cls} border rounded-xl p-3 text-center`}>
      <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-1 truncate">{label}</p>
      <p className="font-bold text-sm tabular-nums leading-none">{value}</p>
    </div>
  )
}

function ResultBox({ children }) {
  return (
    <div className="mt-5 pt-5 border-t border-slate-700/60 space-y-4">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest flex items-center gap-1.5">
        <CheckCircle2 className="w-3 h-3 text-emerald-500" /> Response
      </p>
      {children}
    </div>
  )
}

function DevInput({ label, hint, ...props }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 font-medium mb-1.5">
        {label}{hint && <span className="text-slate-600 ml-1">{hint}</span>}
      </label>
      <input {...props}
        className="w-full bg-slate-800 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-offset-0 focus:border-transparent transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      />
    </div>
  )
}

function DevSelect({ label, hint, children, ...props }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 font-medium mb-1.5">
        {label}{hint && <span className="text-slate-600 ml-1">{hint}</span>}
      </label>
      <select {...props}
        className="w-full bg-slate-800 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent transition-colors disabled:opacity-40"
      >
        {children}
      </select>
    </div>
  )
}

function InfoBanner({ text, accent = 'amber' }) {
  const c = {
    amber: 'bg-amber-950/40 border-amber-800/40 text-amber-300',
    blue:  'bg-blue-950/40 border-blue-800/40 text-blue-300',
    red:   'bg-red-950/40 border-red-800/40 text-red-300',
    green: 'bg-emerald-950/40 border-emerald-800/40 text-emerald-300',
  }[accent] ?? 'bg-amber-950/40 border-amber-800/40 text-amber-300'
  return (
    <div className={`flex items-start gap-2.5 ${c} border rounded-xl px-4 py-3`}>
      <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5 opacity-70" />
      <p className="text-xs leading-relaxed">{text}</p>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// TAB 0 — STRESS TEST (existing advanced simulation)
// ─────────────────────────────────────────────────────────────────────────────

function _SimTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-slate-900/95 border border-slate-700 rounded-xl p-3.5 shadow-2xl backdrop-blur-sm">
      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2.5">Week {label}</p>
      {payload.map(p => (
        <div key={p.dataKey} className="flex items-center gap-2.5 mb-1.5 last:mb-0">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: p.color }} />
          <span className="text-xs text-slate-400">{p.name}:</span>
          <span className="text-xs font-bold tabular-nums" style={{ color: p.color }}>{Number(p.value).toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  )
}

function SimLockout({ progress = null, isRealEngine = false }) {
  // progress: { week: number, total: number, percent: number } | null
  const showProgress = isRealEngine && progress && progress.total > 0
  return (
    <div className="absolute inset-0 z-30 flex flex-col items-center justify-center backdrop-blur-md bg-black/60 rounded-2xl">
      <div className="relative w-20 h-20 mb-6">
        <svg className="w-20 h-20 animate-spin" style={{ animationDuration: '1.4s' }} viewBox="0 0 80 80" fill="none">
          <circle cx="40" cy="40" r="34" stroke={isRealEngine ? '#059669' : '#7c3aed'} strokeWidth="5" strokeOpacity="0.15" />
          <circle cx="40" cy="40" r="34" stroke={isRealEngine ? '#059669' : '#7c3aed'} strokeWidth="5" strokeDasharray="53 160" strokeLinecap="round" />
        </svg>
        <svg className="absolute inset-0 w-20 h-20 animate-spin" style={{ animationDuration: '0.9s', animationDirection: 'reverse' }} viewBox="0 0 80 80" fill="none">
          <circle cx="40" cy="40" r="26" stroke={isRealEngine ? '#34d399' : '#06b6d4'} strokeWidth="3" strokeDasharray="32 132" strokeLinecap="round" />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center"><FlaskConical className={`w-7 h-7 ${isRealEngine ? 'text-emerald-300' : 'text-violet-300'}`} /></div>
      </div>

      <p className="text-white font-extrabold text-lg text-center mb-1 tracking-tight">
        {isRealEngine ? '🔬 Real Engine running…' : 'AI Stress-Testing Engine running…'}
      </p>

      {showProgress ? (
        /* ── Real Engine live progress bar ─────────────────────────────── */
        <div className="w-72 mt-4 px-4">
          <div className="flex justify-between items-center mb-2">
            <span className="text-xs text-slate-400">
              Week <span className="font-bold text-emerald-300">{progress.week}</span>
              {' '}/ {progress.total}
            </span>
            <span className="text-sm font-black tabular-nums text-emerald-400">
              {progress.percent.toFixed(1)}%
            </span>
          </div>
          <div className="h-2.5 bg-slate-700/80 rounded-full overflow-hidden border border-slate-600/50">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out"
              style={{
                width: `${Math.max(2, progress.percent)}%`,
                background: 'linear-gradient(90deg, #059669 0%, #34d399 100%)',
                boxShadow: '0 0 8px rgba(52,211,153,0.5)',
              }}
            />
          </div>
          <p className="text-emerald-400 text-[11px] text-center mt-2 font-semibold">
            {progress.percent < 100
              ? 'Real strategy engine processing weekly cycles…'
              : 'Finalising results…'}
          </p>
          <p className="text-slate-500 text-[10px] text-center mt-1">
            Inject → Payment → A/B/C → Draw → SDE — each week runs real production services
          </p>
        </div>
      ) : isRealEngine ? (
        /* Real Engine — no progress yet (still queued) */
        <div className="text-slate-400 text-sm text-center max-w-xs leading-relaxed px-4 space-y-1 mt-3">
          <p className="text-emerald-400 font-semibold">Starting simulation engine…</p>
          <p>Connecting to Real PostgreSQL DB + ChronosEngine time-travel.</p>
        </div>
      ) : (
        /* Fast Preview */
        <div className="text-slate-400 text-sm text-center max-w-xs leading-relaxed px-4 space-y-1 mt-2">
          <p>Executing deep algorithmic evaluation up to 1,000 rounds.</p>
          <p>Calibrating system liquidity limits.</p>
        </div>
      )}

      <p className={`text-xs font-bold mt-5 flex items-center gap-2 ${isRealEngine ? 'text-emerald-400' : 'text-violet-400'}`}>
        <span className={`w-2 h-2 rounded-full animate-pulse block ${isRealEngine ? 'bg-emerald-400' : 'bg-violet-400'}`} />
        Please do not refresh — simulation running in background.
      </p>
    </div>
  )
}

// ── Simulation Error Debugger Panel ─────────────────────────────────────────
// Renders when result._error is true.  If result._debugger is populated
// (Real Engine background job), it shows the exact file, line, function and
// source line alongside a collapsible full traceback.
function SimErrorDebugger({ result }) {
  const [showTrace, setShowTrace] = useState(false)
  const d = result._debugger ?? null

  return (
    <div className="mb-5 rounded-xl border border-red-800/60 bg-red-950/30 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 bg-red-950/50 border-b border-red-800/40">
        <XCircle className="w-4 h-4 text-red-500 flex-shrink-0"/>
        <p className="font-bold text-red-400 uppercase tracking-wide text-xs flex-1">
          Simulation Error {result._status ? `(HTTP ${result._status})` : '(Network)'}
        </p>
        {d && (
          <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-red-900/60 border border-red-700/60 text-red-300 uppercase">
            🔍 Debugger
          </span>
        )}
      </div>

      <div className="p-4 space-y-3">
        {/* Error message */}
        <p className="text-xs text-red-300 font-mono leading-relaxed break-all">{result._msg}</p>

        {/* Exact location — only when Real Engine provides debugger info */}
        {d && (
          <div className="space-y-2">
            {/* Exception type + location grid */}
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-2.5">
                <p className="text-slate-500 text-[9px] font-bold uppercase tracking-wider mb-1">Exception Type</p>
                <p className="text-amber-400 font-mono font-bold">{d.error_type ?? '—'}</p>
              </div>
              <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-2.5">
                <p className="text-slate-500 text-[9px] font-bold uppercase tracking-wider mb-1">Function</p>
                <p className="text-cyan-400 font-mono font-bold">{d.error_func ?? '—'}</p>
              </div>
              <div className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-2.5 col-span-2">
                <p className="text-slate-500 text-[9px] font-bold uppercase tracking-wider mb-1">File : Line</p>
                <p className="text-emerald-400 font-mono text-[11px] break-all">
                  {d.error_file
                    ? <>{d.error_file.replace(/.*[/\\]app[/\\]/, 'app/')} <span className="text-slate-400">:</span> <span className="text-white font-black">{d.error_line}</span></>
                    : '—'
                  }
                </p>
              </div>
              {d.error_source && (
                <div className="bg-slate-900/80 border border-amber-800/50 rounded-lg p-2.5 col-span-2">
                  <p className="text-slate-500 text-[9px] font-bold uppercase tracking-wider mb-1">Source Line</p>
                  <p className="text-amber-300 font-mono text-xs break-all">{d.error_source}</p>
                </div>
              )}
            </div>

            {/* Full traceback — collapsible */}
            {d.error_traceback && (
              <div>
                <button
                  onClick={() => setShowTrace(v => !v)}
                  className="flex items-center gap-1.5 text-[10px] font-bold text-slate-400 hover:text-slate-200 transition-colors uppercase tracking-wider"
                >
                  <ChevronRight className={`w-3 h-3 transition-transform duration-200 ${showTrace ? 'rotate-90' : ''}`}/>
                  {showTrace ? 'Hide Full Traceback' : 'Show Full Traceback'}
                </button>
                {showTrace && (
                  <pre className="mt-2 p-3 bg-black/50 border border-slate-700/50 rounded-lg text-[10px] text-slate-400 font-mono overflow-x-auto whitespace-pre-wrap break-all leading-relaxed">
                    {d.error_traceback}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}

        {/* Common causes hint */}
        <p className="text-[10px] text-slate-600 border-t border-slate-800 pt-2">
          Common causes: 500 = server bug (check traceback above) ·
          403 = ENABLE_DEV_MODE not set on server ·
          Network = Render restarted (rare in background mode)
        </p>
      </div>
    </div>
  )
}


function SimStatsGrid({ s }) {
  const cond   = s.total_condensation_events
  const pauses = s.total_draw_pauses_triggered
  const liq    = s.final_virtual_liquidity_float
  const sh     = s.system_health ?? {}
  const sdeEx  = sh.total_sde_exits    ?? 0
  const typeA  = sh.total_type_a_draws ?? 0
  const typeB  = sh.total_type_b_draws ?? 0
  const sdeFlg = sh.total_l4_sde_flaggings ?? 0
  return (
    <div className="mt-6 space-y-4">
      <p className="text-[10px] font-bold text-violet-400 uppercase tracking-widest flex items-center gap-2"><Database className="w-3.5 h-3.5" />Simulation Audit Ledger</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {[
          { icon: Users,      label:'Users Created',     value:s.total_simulated_users_created.toLocaleString('en-IN'), badge:'👥', dyn:false },
          { icon: BarChart3,  label:'Pools Auto-Scaled', value:s.total_pools_auto_scaled, badge:'📊', dyn:false },
          { icon: GitMerge,   label:'Inter-Pool Merges', value:cond,  badge:'🔄', dyn:cond>0,  bc:'border-orange-500 bg-orange-950/20' },
          { icon: ShieldAlert,label:'Draws Paused',      value:pauses,badge:'⚠️', dyn:pauses>0,bc:'border-red-500 bg-red-950/20', vc:pauses>0?'text-red-400':'text-white' },
          { icon: IndianRupee,label:'Late Fees Collected',value:INR(s.total_late_fees_collected_inr),badge:'💸', dyn:false },
          { icon: DollarSign, label:'Final Liquidity Float',value:INR(liq),badge:'💰',dyn:true,bc:liq>=0?'border-emerald-500 bg-emerald-950/20':'border-red-500 bg-red-950/20',vc:liq>=0?'text-emerald-400':'text-red-400' },
        ].map((c, i) => (
          <div key={i} className={`border-2 rounded-2xl p-5 transition-all duration-300 ${c.dyn?c.bc:'border-slate-700/60 bg-slate-800/40'}`}>
            <div className="flex items-start justify-between mb-3">
              <div className="bg-slate-800/80 p-2 rounded-xl"><c.icon className="w-4 h-4 text-slate-300" /></div>
              {c.badge && <span className="text-base leading-none">{c.badge}</span>}
            </div>
            <p className={`text-2xl font-black tabular-nums leading-none mb-1.5 ${c.vc||'text-white'}`}>{c.value}</p>
            <p className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider">{c.label}</p>
          </div>
        ))}
      </div>

      {/* SDE / Draw Type metrics row */}
      <div>
        <p className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-3"><Cpu className="w-3.5 h-3.5" />Brain 5 SDE &amp; Draw Type Analytics</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label:'L4 SDE Flaggings', value:sdeFlg,                                    accent:'amber',  desc:'Members reaching L4 — flagged for forced exit' },
            { label:'SDE Exits',        value:sdeEx,                                     accent:'rose',   desc:'Total guaranteed SDE exits (L4+L5+L6)' },
            { label:'L5 Ext-II Exits',  value:sh.total_l5_ext2_forced_exits??0,          accent:'orange', desc:'L5 members forced out before becoming L6' },
            { label:'L6 Ext-III Exits', value:sh.total_l6_ext3_forced_exits??0,          accent:'purple', desc:'L6 members emergency forced exit' },
            { label:'Type A Draws',     value:typeA,                                     accent:'cyan',   desc:'LPI 14-25% routing' },
            { label:'Type B Draws',     value:typeB,                                     accent:'orange', desc:'L1/L2 shortage fallback' },
            { label:'Accel Diss',       value:sh.total_accel_dissolution_events??0,      accent:'red',    desc:'≥60% L4+ → both winners from L4+' },
            { label:'Draw Pauses',      value:(sh.total_draw_pauses_triggered??0),       accent:'amber',  desc:'Pools paused (safestop, under-capacity)' },
          ].map((c, i) => (
            <div key={i} className="border border-slate-700/60 bg-slate-800/40 rounded-xl p-3">
              <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">{c.label}</p>
              <p className={`text-xl font-black tabular-nums mt-1 ${
                c.accent==='amber'?'text-amber-400':c.accent==='rose'?'text-rose-400':c.accent==='cyan'?'text-cyan-400':c.accent==='orange'?'text-orange-400':c.accent==='purple'?'text-purple-400':'text-red-400'
              }`}>{c.value}</p>
              <p className="text-[9px] text-slate-600 mt-0.5">{c.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* A-1: L5/L6 Escalation Explanation */}
      {sh.l5_l6_escalation_explanation && (
        <div className={`p-3 rounded-xl border text-xs ${
          (sh.max_l5_count>0||sh.max_l6_count>0)
            ? 'bg-red-950/30 border-red-800/50 text-red-300'
            : 'bg-emerald-950/30 border-emerald-800/50 text-emerald-300'
        }`}>
          <p className="font-bold uppercase tracking-wider text-[10px] mb-1 opacity-70">
            {(sh.max_l5_count>0||sh.max_l6_count>0) ? '⚠ Anti-Maturity Pressure Analysis (A-1)' : '✓ Anti-Maturity Health (A-1)'}
          </p>
          <p>{sh.l5_l6_escalation_explanation}</p>
        </div>
      )}
    </div>
  )
}

function SystemHealth({ fm, sh }) {
  if (!fm || !sh) return null
  const liability = fm.projected_ultimate_liability ?? 0
  const profit    = fm.net_organizer_profit_inr ?? 0
  return (
    <div className="mt-6">
      <p className="text-[10px] font-bold text-rose-400 uppercase tracking-widest flex items-center gap-2 mb-3"><ShieldAlert className="w-3.5 h-3.5" />System Health &amp; Liability</p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label:'Total Collected',     val:INR(fm.total_collected_inr??0),      c:'text-cyan-400',    bc:'border-emerald-700/30' },
          { label:'Total Distributed',   val:INR(fm.total_distributed_inr??0),    c:'text-amber-400',   bc:'border-amber-700/30'   },
          { label:'Net Profit',          val:INR(profit),                          c:profit>=0?'text-emerald-400':'text-red-400', bc:profit>=0?'border-emerald-700/30':'border-red-700/30' },
          { label:'Projected Liability', val:INR(liability),                       c:'text-red-400',     bc:'border-red-700/50',    bg:'bg-red-950/30' },
          { label:'Direct Assignments',  val:(sh.total_direct_pool_assignments??0).toLocaleString(), c:'text-blue-400', bc:'border-slate-700/50' },
          { label:'Dynamic Merges',      val:(sh.total_dynamic_merges??0).toLocaleString(),          c:'text-violet-400',bc:'border-violet-700/30' },
          { label:'Draw Pauses',         val:(sh.total_draw_pauses_triggered??0).toLocaleString(),   c:'text-amber-400', bc:'border-amber-700/30' },
          { label:'Late Fees Collected', val:INR(fm.total_late_fees_inr??0),       c:'text-emerald-400',bc:'border-slate-700/50'   },
        ].map((r,i) => (
          <div key={i} className={`${r.bg||'bg-slate-800/40'} border ${r.bc} rounded-2xl p-4`}>
            <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-widest mb-2">{r.label}</p>
            <p className={`text-xl font-black tabular-nums ${r.c}`}>{r.val}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

const LEVEL_ACCENT = {
  L1:'text-slate-300 bg-slate-700', L2:'text-blue-300 bg-blue-900/60',
  L3:'text-violet-300 bg-violet-900/60', L4:'text-amber-300 bg-amber-900/60',
  L5:'text-orange-300 bg-orange-900/60', L6:'text-emerald-300 bg-emerald-900/60',
}

function LevelMatrix({ levelWise }) {
  if (!levelWise) return null
  return (
    <div className="mt-6">
      <p className="text-[10px] font-bold text-amber-400 uppercase tracking-widest flex items-center gap-2 mb-3"><BarChart3 className="w-3.5 h-3.5" />Level-Wise Financial Matrix</p>
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-2xl overflow-hidden">
        <table className="w-full text-xs">
          <thead><tr className="border-b border-slate-700/60">{['Level','Winners','Collected','Distributed','Avg Payout','Level ROI'].map(h=>(
            <th key={h} className="text-left px-4 py-3 text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{h}</th>
          ))}</tr></thead>
          <tbody>
            {['L1','L2','L3','L4','L5','L6'].map(lk => {
              const d=levelWise[lk]??{}, acc=LEVEL_ACCENT[lk]??LEVEL_ACCENT.L1
              const roi=d.level_roi_pct??0
              return (
                <tr key={lk} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                  <td className="px-4 py-3"><span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold ${acc}`}>{lk}</span></td>
                  <td className="px-4 py-3 tabular-nums text-slate-300">{(d.winners_count??0).toLocaleString()}</td>
                  <td className="px-4 py-3 tabular-nums text-cyan-400">{INR(d.total_collected_from_them??0)}</td>
                  <td className="px-4 py-3 tabular-nums text-amber-400">{INR(d.total_distributed_to_them??0)}</td>
                  <td className="px-4 py-3 tabular-nums text-slate-400">{INR(d.avg_payout??0)}</td>
                  <td className={`px-4 py-3 tabular-nums font-bold ${roi>=0?'text-emerald-400':'text-red-400'}`}>{roi>=0?'+':''}{roi.toFixed(1)}%</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const SCENARIO_COLORS = { SUSTAINABLE_WAVE:'#3fb950', BOOM_GOLDEN_CROSS:'#58a6ff', FLASH_FLOOD:'#d29922', DRY_PHASE:'#f85149', REFERRAL_LIFELINE:'#a371f7', NEUTRAL:'#8b949e', VELOCITY_CLIFF:'#e3b341' }

function AiBrainCharts({ logs }) {
  if (!logs?.length) return null
  const hasAiData = logs.some(l => l.momentum_value !== undefined)
  if (!hasAiData) return null
  const scenarioCounts = {}
  logs.forEach(l => { if (l.scenario) scenarioCounts[l.scenario] = (scenarioCounts[l.scenario]??0)+1 })
  const dominant = Object.entries(scenarioCounts).sort((a,b)=>b[1]-a[1])[0]?.[0]??'NEUTRAL'
  return (
    <div className="mt-6">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2"><TrendingUp className="w-3.5 h-3.5" />AI Brain — Momentum &amp; RDR</p>
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[10px] font-bold uppercase tracking-wide" style={{ background:`${SCENARIO_COLORS[dominant]}15`, borderColor:`${SCENARIO_COLORS[dominant]}50`, color:SCENARIO_COLORS[dominant] }}>
          {dominant.replace(/_/g,' ')}
        </div>
      </div>
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-2xl p-5 space-y-6">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={logs} margin={{ top:5,right:10,left:-15,bottom:5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.5} vertical={false}/>
            <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={{stroke:'#334155'}}/>
            <YAxis tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false}/>
            <ReferenceLine y={0} stroke="#64748b" strokeDasharray="4 2" strokeOpacity={0.6}/>
            <RechartTooltip contentStyle={{background:'#1e293b',border:'1px solid #334155',borderRadius:8,fontSize:11}} labelStyle={{color:'#94a3b8',fontSize:10}}/>
            <Legend wrapperStyle={{paddingTop:12,fontSize:11,color:'#94a3b8'}}/>
            <Line type="monotone" dataKey="momentum_value" name="Momentum" stroke="#e3b341" strokeWidth={2} dot={false} activeDot={{r:4}}/>
            <Line type="monotone" dataKey="velocity" name="Velocity" stroke="#58a6ff" strokeWidth={1.5} strokeDasharray="4 2" dot={false} activeDot={{r:4}}/>
          </LineChart>
        </ResponsiveContainer>
        <div className="flex flex-wrap gap-2">
          {Object.entries(scenarioCounts).sort((a,b)=>b[1]-a[1]).map(([sc,cnt]) => (
            <div key={sc} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[10px] font-semibold" style={{ background:`${SCENARIO_COLORS[sc]??'#8b949e'}15`, borderColor:`${SCENARIO_COLORS[sc]??'#8b949e'}40`, color:SCENARIO_COLORS[sc]??'#8b949e' }}>
              {sc.replace(/_/g,' ')} <span className="font-black">{cnt}w</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SimCharts({ logs }) {
  if (!logs?.length) return null
  return (
    <div className="mt-6">
      <p className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2 mb-3"><TrendingUp className="w-3.5 h-3.5" />Week-Over-Week Analysis</p>
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-2xl p-5">
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={logs} margin={{top:10,right:10,left:-15,bottom:10}}>
            <defs>
              <linearGradient id="gWL" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#06b6d4" stopOpacity={0.25}/><stop offset="95%" stopColor="#06b6d4" stopOpacity={0.02}/></linearGradient>
              <linearGradient id="gPL" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#a855f7" stopOpacity={0.25}/><stop offset="95%" stopColor="#a855f7" stopOpacity={0.02}/></linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.5} vertical={false}/>
            <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:11}} tickLine={false} axisLine={{stroke:'#334155'}}/>
            <YAxis yAxisId="left" tick={{fill:'#64748b',fontSize:11}} tickLine={false} axisLine={false}/>
            <YAxis yAxisId="right" orientation="right" tick={{fill:'#a855f7',fontSize:11}} tickLine={false} axisLine={false}/>
            <RechartTooltip content={<_SimTooltip/>}/>
            <Legend wrapperStyle={{paddingTop:16,fontSize:11,color:'#94a3b8'}}/>
            {/* D1 FIX: active_pools → pools_active (matches _snapshot return key) */}
            <Area yAxisId="left" type="monotone" dataKey="waitlist_count" name="Waitlist" stroke="#06b6d4" strokeWidth={2} fill="url(#gWL)" dot={false}/>
            <Area yAxisId="right" type="monotone" dataKey="pools_active" name="Active Pools" stroke="#a855f7" strokeWidth={2} fill="url(#gPL)" dot={false}/>
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ── CSV download helper ──────────────────────────────────────────────────────
function downloadCSV(rows, filename) {
  if (!rows?.length) return
  const headers = Object.keys(rows[0])
  const lines = [
    headers.join(','),
    ...rows.map(r => headers.map(h => {
      const v = r[h]
      if (v === null || v === undefined) return ''
      const s = typeof v === 'object' ? JSON.stringify(v) : String(v)
      return s.includes(',') ? `"${s.replace(/"/g,'""')}"` : s
    }).join(','))
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a'); a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ── Report Sub-Tabs ──────────────────────────────────────────────────────────
const REPORT_TABS = [
  { id: 'summary',    label: 'Summary',          short: 'Sum'  },
  { id: 'weekly',     label: 'Weekly Report',     short: 'Wkly' },
  { id: 'pools',      label: 'Pool Activity',     short: 'Pool' },
  { id: 'draws',      label: 'Draw Analysis',     short: 'Draw' },
  { id: 'cashflow',   label: 'Cash Flow',         short: 'Cash' },
  { id: 'levels',     label: 'Level Progression', short: 'Lvl'  },
]

// ── Weekly Report Table ──────────────────────────────────────────────────────
function WeeklyReportTable({ rows }) {
  if (!rows?.length) return <p className="text-xs text-slate-500 p-4">No weekly data</p>
  const cols = [
    { key: 'week', label: 'Week' },
    { key: 'week_start_date', label: 'Date' },
    { key: 'users_joined', label: 'Joined' },
    { key: 'active_users', label: 'Active' },
    { key: 'waitlist_count', label: 'Waitlist' },
    { key: 'pools_active', label: 'Pools' },
    { key: 'lpi', label: 'LPI%' },
    { key: 'draws_this_week', label: 'Draws' },
    { key: 'late_payers', label: 'Late' },
    { key: 'scenario', label: 'AI Phase' },
  ]
  return (
    <div className="overflow-auto max-h-96 rounded-xl border border-slate-700/60">
      <table className="w-full text-xs whitespace-nowrap">
        <thead className="bg-slate-800 sticky top-0 z-10">
          <tr>{cols.map(c=><th key={c.key} className="text-left px-3 py-2.5 text-slate-400 font-semibold">{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r,i)=>(
            <tr key={r.week} className={`border-b border-slate-800/50 ${r.high_pressure_mode?'bg-red-950/20':'i%2===0?bg-slate-900:bg-slate-900/50'}`}>
              {cols.map(c=>(
                <td key={c.key} className={`px-3 py-2 ${c.key==='lpi'?(parseFloat(r.lpi)>=50?'text-red-400 font-bold':parseFloat(r.lpi)>=25?'text-orange-400':parseFloat(r.lpi)>=14?'text-amber-400':'text-emerald-400'):c.key==='scenario'?'text-cyan-300 text-[10px]':'text-slate-300'}`}>
                  {c.key==='lpi'?`${r.lpi}%`:r[c.key]??'—'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Pool Activity Chart ───────────────────────────────────────────────────────
function PoolActivityChart({ logs }) {
  if (!logs?.length) return null
  // D2 FIX [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Switched from cycle_logs (week/pauses/draws/inflow only) to weekly_detail which
  // carries pools_active, pools_paused, pools_formed from the _snapshot() return.
  // Field renames: active_pools→pools_active, pauses→pools_paused, merges→pools_formed
  const data = logs.map(l=>({
    week:   l.week,
    active: l.pools_active  ?? 0,
    pauses: l.pools_paused  ?? 0,
    formed: l.pools_formed  ?? 0,
  }))
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{top:4,right:8,left:0,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4}/>
          <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} interval="preserveStartEnd"/>
          <YAxis tick={{fill:'#64748b',fontSize:10}}/>
          <RechartTooltip contentStyle={{background:'#0f172a',border:'1px solid #334155',borderRadius:12,fontSize:11}}/>
          <Area type="monotone" dataKey="active" stroke="#6366f1" fill="#6366f120" name="Active Pools" strokeWidth={1.5}/>
          <Area type="monotone" dataKey="pauses" stroke="#f59e0b" fill="#f59e0b10" name="Paused Pools" strokeWidth={1.5}/>
          <Area type="monotone" dataKey="formed" stroke="#10b981" fill="#10b98110" name="Pools Formed" strokeWidth={1.5}/>
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Level Progression Chart (A-1: full L5/L6 visibility) ─────────────────────
function LevelProgressionChart({ weekly, logs }) {
  if (!weekly?.length) return null

  // Main stacked area data
  const data = weekly.map(w=>({
    week: w.week,
    L1: w.level_distribution?.L1??0,
    L2: w.level_distribution?.L2??0,
    L3: w.level_distribution?.L3??0,
    L4: w.level_distribution?.L4??0,
    L5: w.level_distribution?.L5??w.l5_count??0,
    L6: w.level_distribution?.L6??w.l6_count??0,
    lpi: w.lpi??0,
  }))

  // Escalation events: compute per-cycle from cumulative weekly_detail fields
  const escalData = weekly.map((w,i)=>{
    const prev = i>0?weekly[i-1]:null
    return {
      week: w.week,
      ext2_exits:  Math.max(0,(w.ext2_exits_this_week??0)-(prev?.ext2_exits_this_week??0)),
      ext3_exits:  Math.max(0,(w.ext3_exits_this_week??0)-(prev?.ext3_exits_this_week??0)),
      accel_diss:  Math.max(0,(w.accel_diss_this_week??0)-(prev?.accel_diss_this_week??0)),
      pool_pauses: logs?.[i]?.pauses??0,
      l5_count:    w.l5_count??w.level_distribution?.L5??0,
      l6_count:    w.l6_count??w.level_distribution?.L6??0,
    }
  })

  // Find weeks where L5/L6 actually appeared (for WHY table)
  const escalWeeks = escalData.filter(w => w.l5_count>0 || w.l6_count>0 || w.ext2_exits>0 || w.ext3_exits>0 || w.accel_diss>0)

  const LEVEL_COLORS = ['#64748b','#3b82f6','#8b5cf6','#f59e0b','#ef4444','#bf00ff']

  return (
    <div className="space-y-5">
      {/* 1. Full stacked area — L1–L6 distribution */}
      <div>
        <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-2">Member Level Distribution (Proportional)</p>
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{top:4,right:8,left:0,bottom:0}} stackOffset="expand">
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4}/>
              <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} interval="preserveStartEnd"/>
              <YAxis tickFormatter={v=>`${(v*100).toFixed(0)}%`} tick={{fill:'#64748b',fontSize:10}}/>
              <RechartTooltip contentStyle={{background:'#0f172a',border:'1px solid #334155',borderRadius:12,fontSize:11}} formatter={(v,n)=>[v,n]}/>
              <Legend wrapperStyle={{fontSize:10}}/>
              {['L1','L2','L3','L4','L5','L6'].map((lv,i)=>(
                <Area key={lv} type="monotone" dataKey={lv} stackId="1"
                  stroke={LEVEL_COLORS[i]} fill={LEVEL_COLORS[i]+'40'} name={lv} strokeWidth={lv==='L5'||lv==='L6'?2:1}/>
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 2. L5+L6 Anti-Maturity Pressure spike chart */}
      <div>
        <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-2">L5+L6 Anti-Maturity Pressure + LPI</p>
        <div className="h-36">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{top:4,right:8,left:0,bottom:0}}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4}/>
              <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} interval="preserveStartEnd"/>
              <YAxis tick={{fill:'#64748b',fontSize:10}}/>
              <RechartTooltip contentStyle={{background:'#0f172a',border:'1px solid #334155',borderRadius:12,fontSize:11}}/>
              <Legend wrapperStyle={{fontSize:10}}/>
              <Line type="monotone" dataKey="L5" stroke="#ef4444" strokeWidth={2.5} dot={false} name="L5 Active"/>
              <Line type="monotone" dataKey="L6" stroke="#bf00ff" strokeWidth={2.5} dot={false} name="L6 Active"/>
              <Line type="monotone" dataKey="lpi" stroke="#f59e0b" strokeWidth={1} strokeDasharray="4 2" dot={false} name="LPI%"/>
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 3. Pool Pause Timeline + SDE Extension Events per week */}
      <div>
        <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-2">Pool Pauses + SDE Extension Events Per Week</p>
        <div className="h-36">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={escalData} margin={{top:4,right:8,left:0,bottom:0}}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4}/>
              <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} interval="preserveStartEnd"/>
              <YAxis tick={{fill:'#64748b',fontSize:10}}/>
              <RechartTooltip contentStyle={{background:'#0f172a',border:'1px solid #334155',borderRadius:12,fontSize:11}}/>
              <Legend wrapperStyle={{fontSize:10}}/>
              <Bar dataKey="pool_pauses" fill="#f59e0b"  name="Pool Pauses"   radius={[2,2,0,0]}/>
              <Bar dataKey="ext2_exits"  fill="#ef4444"  name="Ext-II (L5→exit)" radius={[2,2,0,0]}/>
              <Bar dataKey="ext3_exits"  fill="#bf00ff"  name="Ext-III (L6→exit)" radius={[2,2,0,0]}/>
              <Bar dataKey="accel_diss"  fill="#f97316"  name="Accel Diss"    radius={[2,2,0,0]}/>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 4. A-1: WHY table — escalation event breakdown */}
      {escalWeeks.length > 0 ? (
        <div className="border border-red-900/50 bg-red-950/20 rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-red-900/40">
            <p className="text-[10px] font-bold text-red-400 uppercase tracking-widest">⚠ A-1 Anti-Maturity Escalation — WHY Members Reached L5/L6</p>
            <p className="text-[9px] text-red-700 mt-0.5">
              Escalation cause: Accelerated dissolution (≥60% L4+ pool) runs both winners from L4+.
              Surviving L4 members advance +1 → reach L5. Ext-II catches them immediately next eligible draw.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] whitespace-nowrap">
              <thead className="bg-red-950/30">
                <tr>
                  {['Week','L5 Count','L6 Count','Ext-II Exits','Ext-III Exits','Accel Diss','Pool Pauses','Root Cause'].map(h=>(
                    <th key={h} className="text-left px-3 py-2 text-slate-500 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {escalWeeks.slice(0,20).map(w=>(
                  <tr key={w.week} className="border-t border-red-900/30">
                    <td className="px-3 py-2 font-mono font-bold text-slate-400">{w.week}</td>
                    <td className={`px-3 py-2 font-bold tabular-nums ${w.l5_count>0?'text-red-400':'text-slate-600'}`}>{w.l5_count}</td>
                    <td className={`px-3 py-2 font-bold tabular-nums ${w.l6_count>0?'text-purple-400':'text-slate-600'}`}>{w.l6_count}</td>
                    <td className="px-3 py-2 tabular-nums text-red-300">{w.ext2_exits}</td>
                    <td className="px-3 py-2 tabular-nums text-purple-300">{w.ext3_exits}</td>
                    <td className="px-3 py-2 tabular-nums text-orange-300">{w.accel_diss}</td>
                    <td className={`px-3 py-2 tabular-nums ${w.pool_pauses>0?'text-amber-400':'text-slate-600'}`}>{w.pool_pauses}</td>
                    <td className="px-3 py-2 text-slate-500">
                      {w.accel_diss>0 ? 'Accel diss → L4 survivors → L5' :
                       w.pool_pauses>0 ? 'Pool paused (under-capacity)' :
                       w.ext2_exits>0 ? 'Ext-II cleared L5' :
                       w.ext3_exits>0 ? 'Ext-III cleared L6' : '—'}
                    </td>
                  </tr>
                ))}
                {escalWeeks.length>20&&<tr><td colSpan={8} className="px-3 py-2 text-slate-600 text-center">…{escalWeeks.length-20} more weeks</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 p-3 bg-emerald-950/30 border border-emerald-800/40 rounded-xl text-[10px] text-emerald-400">
          <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0"/>
          <span>✓ No L5/L6 escalation detected — SDE cleared all L4 members before advancement.</span>
        </div>
      )}
    </div>
  )
}

// ── Cash Flow Chart ──────────────────────────────────────────────────────────
function CashFlowChart({ weekly }) {
  if (!weekly?.length) return null
  const data = weekly.map(w=>({ week:w.week, inflow:w.cash_inflow_inr??0, installments:w.installments_collected_inr??0, late_fees:w.late_fees_collected_inr??0 }))
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{top:4,right:8,left:0,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4}/>
          <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} interval="preserveStartEnd"/>
          <YAxis tick={{fill:'#64748b',fontSize:10}} tickFormatter={v=>v>=1000?`₹${(v/1000).toFixed(0)}k`:`₹${v}`}/>
          <RechartTooltip contentStyle={{background:'#0f172a',border:'1px solid #334155',borderRadius:12,fontSize:11}} formatter={v=>INR(v)}/>
          <Legend wrapperStyle={{fontSize:10}}/>
          <Bar dataKey="inflow"       stackId="a" fill="#10b981" name="New Deposits" radius={[0,0,0,0]}/>
          <Bar dataKey="installments" stackId="a" fill="#3b82f6" name="Installments" radius={[0,0,0,0]}/>
          <Bar dataKey="late_fees"    stackId="a" fill="#f59e0b" name="Late Fees"    radius={[4,4,0,0]}/>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Draw Analysis Chart ───────────────────────────────────────────────────────
function DrawAnalysisChart({ weekly }) {
  if (!weekly?.length) return null
  // D3 FIX [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // draw_type_breakdown was never populated in _snapshot() so all bars were zero.
  // Derive per-week counts from cumulative fields already present in weekly_detail:
  //   accel_diss_this_week  — cumulative accelerated dissolution draws (SDE-Accel)
  //   ext2_exits_this_week  — cumulative SDE Ext-II draws
  //   ext3_exits_this_week  — cumulative SDE Ext-III draws
  //   draws_this_week       — total draws this week (regular + all SDE types)
  // Per-week value = current_cumulative - previous_cumulative (delta decode).
  const data = weekly.map((w, i) => {
    const prev      = i > 0 ? weekly[i - 1] : null
    const accel     = Math.max(0, (w.accel_diss_this_week ?? 0) - (prev?.accel_diss_this_week ?? 0))
    const ext2      = Math.max(0, (w.ext2_exits_this_week  ?? 0) - (prev?.ext2_exits_this_week  ?? 0))
    const ext3      = Math.max(0, (w.ext3_exits_this_week  ?? 0) - (prev?.ext3_exits_this_week  ?? 0))
    const sde_total = accel + ext2 + ext3
    const regular   = Math.max(0, (w.draws_this_week ?? 0) - sde_total)
    return { week: w.week, regular, accel, ext2, ext3 }
  })
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{top:4,right:8,left:0,bottom:0}}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4}/>
          <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} interval="preserveStartEnd"/>
          <YAxis tick={{fill:'#64748b',fontSize:10}}/>
          <RechartTooltip contentStyle={{background:'#0f172a',border:'1px solid #334155',borderRadius:12,fontSize:11}}/>
          <Legend wrapperStyle={{fontSize:10}}/>
          <Bar dataKey="regular" stackId="a" fill="#10b981" name="Regular"       radius={[0,0,0,0]}/>
          <Bar dataKey="accel"   stackId="a" fill="#3b82f6" name="SDE Accel"     radius={[0,0,0,0]}/>
          <Bar dataKey="ext2"    stackId="a" fill="#f59e0b" name="SDE Ext-II"    radius={[0,0,0,0]}/>
          <Bar dataKey="ext3"    stackId="a" fill="#ef4444" name="SDE Ext-III"   radius={[4,4,0,0]}/>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function StressTestTab({ toast }) {
  const [cycles,       setCycles]       = useState(50)
  // ── Engine Mode ────────────────────────────────────────────────────────────
  // Real Engine: calls actual production services (draw, SDE, waitlist, Brain 2/3/5)
  //   on an isolated in-memory SQLite DB with mocked time — ZERO logic duplication.
  // Fast Preview: uses _AdvSimEngine (in-memory duplicate logic) — faster but may drift.
  const [useRealEngine, setUseRealEngine] = useState(true)
  // ── A/B/C Circular Late-Fee Parameters (A-2) ──────────────────────────────
  // A — Elimination %: what % of unpaid members are eliminated (don't attempt grace)
  // B — Late Fee Rate %: fee per day as % of ₹1000 deposit (min 5% = ₹50/day)
  // C — Grace Saver %: of at-risk members, what % actually pay the grace fee
  // Circular: B cost → affects C willingness → affects effective A elimination rate
  const [elimPctA,  setElimPctA]  = useState(80.0)   // A: 0.05–100%
  const [lateFeeB,  setLateFeeB]  = useState(5.0)    // B: 5–100% per day of deposit
  const [gracePctC, setGracePctC] = useState(15.0)   // C: 0.05–100%
  // late_users_ratio_pct: % of active members who miss the payment due date
  const [lateRatio, setLateRatio] = useState(2.0)
  const [vol,       setVol]       = useState(false)
  const [volMax,    setVolMax]    = useState(100)
  const [rdr,       setRdr]       = useState(40.0)
  // Real-engine–specific params
  const [usersPerWeek,  setUsersPerWeek]  = useState(24)
  const [initialUsers,  setInitialUsers]  = useState(24)
  const [organicRatio,  setOrganicRatio]  = useState(60)   // %
  // ── K-12 to K-17: Extended Injection Knobs ────────────────────────────────
  const [inflowPattern,      setInflowPattern]      = useState('linear')
  const [referralBurstWeek,  setReferralBurstWeek]  = useState(0)
  const [paymentShockWeek,   setPaymentShockWeek]   = useState(0)
  const [waitlistDropoutPct, setWaitlistDropoutPct] = useState(0)
  const [organicDecayRate,   setOrganicDecayRate]   = useState(0)
  const [simulationLabel,    setSimulationLabel]    = useState('')
  const [showKnobs,          setShowKnobs]          = useState(false)
  const [running,       setRunning]       = useState(false)
  const [result,        setResult]        = useState(null)
  const [showSetup,     setShowSetup]     = useState(false)
  const [showRealCfg,   setShowRealCfg]   = useState(false)
  const [reportTab,     setReportTab]     = useState('summary')   // Phase 2-C report sub-tab
  // ── Real Engine background job state ──────────────────────────────────────
  const [simJobId,      setSimJobId]      = useState(null)  // UUID returned by POST /dev/real-simulation
  const [simProgress,   setSimProgress]   = useState({ week: 0, total: 0, percent: 0 })
  const [simDebugger,   setSimDebugger]   = useState(null)  // debugger info on error

  // Derived: effective elimination = those who fail + those in grace who don't pay
  const effectiveElim = ((elimPctA / 100) + (1 - elimPctA / 100) * (1 - gracePctC / 100)) * 100
  const lateFeeINR    = Math.round(lateFeeB / 100 * 1000)

  // ── Real Engine polling ────────────────────────────────────────────────────
  // Polls every 3 s while simJobId is set and running is true.
  // Clears simJobId and sets running=false when job completes or fails.
  useEffect(() => {
    if (!simJobId || !running) return

    let cancelled = false

    const poll = async () => {
      if (cancelled) return
      try {
        const statusRes = await getRealSimStatus(simJobId)
        const { status, current_week, total_weeks, percent } = statusRes.data

        if (!cancelled) {
          setSimProgress({ week: current_week ?? 0, total: total_weeks ?? 0, percent: percent ?? 0 })
        }

        if (status === 'done') {
          // Fetch and store the full result
          try {
            const resultRes = await getRealSimResult(simJobId)
            if (!cancelled) {
              setResult(resultRes.data)
              const s = resultRes.data.simulation_summary ?? {}
              toast(
                `🔬 Real Engine — ${s.total_cycles_run ?? total_weeks} weeks · ${INR(s.final_virtual_liquidity_float)} liquidity`,
                'success'
              )
            }
          } catch (resultErr) {
            if (!cancelled) {
              const msg = `Result fetch failed: ${resultErr.message}`
              toast(msg, 'error')
              setResult({ _error: true, _msg: msg, _status: resultErr.response?.status })
            }
          } finally {
            if (!cancelled) { setRunning(false); setSimJobId(null) }
          }

        } else if (status === 'error') {
          const d = statusRes.data
          const debugInfo = {
            error_message:   d.error_message,
            error_type:      d.error_type,
            error_file:      d.error_file,
            error_line:      d.error_line,
            error_func:      d.error_func,
            error_source:    d.error_source,
            error_traceback: d.error_traceback,
          }
          if (!cancelled) {
            setSimDebugger(debugInfo)
            const loc = d.error_file
              ? `${d.error_file.split(/[/\\]/).pop()}:${d.error_line}`
              : 'unknown location'
            const msg = `Real Engine failed (${d.error_type ?? 'Error'}) at ${loc}: ${d.error_message ?? 'unknown'}`
            toast(msg, 'error')
            setResult({ _error: true, _msg: msg, _status: 500, _debugger: debugInfo })
            setRunning(false)
            setSimJobId(null)
          }
        }
      } catch (pollErr) {
        // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
        // 404 = server restarted — job is permanently gone from _SIM_STATUS.
        // This is terminal, not transient. Reset UI to idle immediately.
        if (pollErr.response?.status === 404) {
          if (!cancelled) {
            toast('Simulation session lost — server was restarted. Please start a new run.', 'warning')
            setRunning(false)
            setSimJobId(null)
          }
          return
        }
        // Transient network error during poll — don't abort, just log
        console.warn('[SimPoll] transient error:', pollErr.message)
      }
    }

    const interval = setInterval(poll, 3_000)
    poll() // immediate first check without waiting 3 s

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [simJobId, running]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    setRunning(true)
    setResult(null)
    setReportTab('summary')
    setSimDebugger(null)
    setSimProgress({ week: 0, total: cycles, percent: 0 })

    if (useRealEngine) {
      // ── Real Engine: background job mode ────────────────────────────────────
      // POST returns job_id immediately — no Render proxy timeout possible.
      // Polling useEffect drives progress; calls setRunning(false) when done.
      try {
        const jobRes = await startRealSimulation({
          weeks:                   cycles,
          users_per_week:          usersPerWeek,
          initial_users:           initialUsers,
          organic_ratio:           organicRatio / 100.0,
          late_users_ratio_pct:    lateRatio,
          elim_pct_a:              elimPctA,
          grace_saver_pct_c:       gracePctC,
          volatility_mode:         vol,
          volatility_max_inflow:   volMax,
          // K-12 to K-17: Extended Injection Knobs
          inflow_pattern:          inflowPattern,
          referral_burst_week:     referralBurstWeek,
          payment_shock_week:      paymentShockWeek,
          waitlist_dropout_pct:    waitlistDropoutPct,
          organic_decay_rate:      organicDecayRate / 100.0,
          simulation_label:        simulationLabel || '',
        })
        setSimJobId(jobRes.data.job_id)
        // setRunning stays true — polling useEffect clears it when job completes
      } catch (startErr) {
        const status = startErr.response?.status
        const raw    = startErr.response?.data?.detail ?? startErr.message ?? 'Unknown error'
        const detail = typeof raw === 'string' ? raw.slice(0, 300) : JSON.stringify(raw).slice(0, 300)
        const msg =
          status === 401 ? 'Session expired — re-login and try again.' :
          status === 403 ? 'Dev mode disabled on server (ENABLE_DEV_MODE must be true).' :
          status === 422 ? `Validation error: ${detail}` :
          `Failed to start simulation (HTTP ${status ?? 'network'}): ${detail}`
        console.error('[Simulation start]', status, startErr.response?.data)
        toast(msg, 'error')
        setResult({ _error: true, _msg: msg, _status: status })
        setRunning(false)
      }
      return   // do NOT fall through — polling handles the rest
    }

    // ── Fast Preview: synchronous in-memory engine ──────────────────────────
    try {
      const res = await advancedSimulationDev({
        total_cycles:          cycles,
        late_fee_pct:          lateFeeB,
        late_users_ratio_pct:  lateRatio,
        elim_pct_a:            elimPctA,
        grace_saver_pct_c:     gracePctC,
        volatility_mode:       vol,
        volatility_max_inflow: volMax,
        avg_rdr_pct:           rdr,
      })
      setResult(res.data)
      const s = res.data.simulation_summary
      toast(
        `⚡ Fast Preview — ${s.total_cycles_run} cycles · ${INR(s.final_virtual_liquidity_float)} liquidity`,
        'success'
      )
    } catch (err) {
      const status = err.response?.status
      const raw    = err.response?.data?.detail ?? err.message ?? 'Unknown error'
      const detail = typeof raw === 'string' ? raw.slice(0, 300) : JSON.stringify(raw).slice(0, 300)
      const msg =
        status === 401 ? 'Session expired — re-login and try again.' :
        status === 403 ? 'Dev mode disabled on server (ENABLE_DEV_MODE must be true).' :
        status === 504 ? 'Server timeout — reduce cycles and retry.' :
        status === 500 ? `Server error (500): ${detail}` :
        status === 422 ? `Validation: ${detail}` :
        `Simulation failed (HTTP ${status ?? 'network'}): ${detail}`
      console.error('[Simulation]', status, err.response?.data)
      toast(msg, 'error')
      setResult({ _error: true, _msg: msg, _status: status })
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="relative bg-slate-900 border border-slate-700/60 rounded-2xl overflow-hidden shadow-2xl shadow-violet-950/20">
      {running && <SimLockout progress={simProgress} isRealEngine={useRealEngine}/>}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-slate-700/60 bg-gradient-to-r from-violet-950/50 via-slate-900/80 to-slate-900">
        <div className={`p-3 rounded-xl border ${useRealEngine ? 'bg-emerald-900/40 border-emerald-700/50' : 'bg-violet-900/40 border-violet-700/50'}`}>
          <FlaskConical className={`w-5 h-5 ${useRealEngine ? 'text-emerald-400' : 'text-violet-400'}`}/>
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <p className="font-extrabold text-slate-100 text-base leading-none">AI Platform Stress-Tester</p>
            {useRealEngine
              ? <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-emerald-900/60 border border-emerald-700/60 text-emerald-300 uppercase tracking-wider">🔬 Real Engine</span>
              : <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-violet-900/60 border border-violet-700/60 text-violet-300 uppercase tracking-wider">⚡ Fast Preview</span>
            }
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            {useRealEngine
              ? 'Zero-duplication · Calls real production services · Isolated SQLite DB · Chronos time-travel'
              : 'In-memory engine · FIFO refill · Condensation · Draw safeguards'}
          </p>
        </div>
        {/* Engine toggle */}
        <div className="flex items-center bg-slate-800/80 border border-slate-700/60 rounded-xl p-1 gap-1">
          <button
            onClick={() => setUseRealEngine(true)} disabled={running}
            className={`text-[11px] font-bold px-3 py-1.5 rounded-lg transition-all ${useRealEngine ? 'bg-emerald-700 text-emerald-100 shadow-sm' : 'text-slate-400 hover:text-emerald-400'}`}
          >🔬 Real</button>
          <button
            onClick={() => setUseRealEngine(false)} disabled={running}
            className={`text-[11px] font-bold px-3 py-1.5 rounded-lg transition-all ${!useRealEngine ? 'bg-violet-700 text-violet-100 shadow-sm' : 'text-slate-400 hover:text-violet-400'}`}
          >⚡ Fast</button>
        </div>
      </div>
      <div className="p-6 space-y-6">
        {/* Cycles slider — Real Engine capped at 15; Fast Preview up to 1000 */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <label className="text-xs font-bold text-slate-300 uppercase tracking-wider">Test Rounds (Weeks)</label>
            <div className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 border ${
              useRealEngine
                ? 'bg-emerald-950/60 border-emerald-700/60'
                : 'bg-violet-950/60 border-violet-700/60'
            }`}>
              <span className={`text-xl font-black tabular-nums ${useRealEngine ? 'text-emerald-200' : 'text-violet-200'}`}>
                {Math.min(cycles, useRealEngine ? 200 : 1000).toLocaleString()}
              </span>
              <span className="text-[10px] text-slate-500 font-semibold">cycles</span>
            </div>
          </div>

          {useRealEngine ? (
            /* ── Real Engine: 1–200 weeks — background job, no proxy timeout ── */
            <>
              <input type="range" min={1} max={200} step={1}
                value={Math.min(cycles, 200)} disabled={running}
                onChange={e => setCycles(parseInt(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer accent-emerald-500 disabled:opacity-40"
                style={{background:`linear-gradient(to right,#059669 ${Math.min(cycles,200)/200*100}%,#334155 ${Math.min(cycles,200)/200*100}%)`}}
              />
              <div className="flex justify-between text-[10px] text-slate-600 mt-1.5 select-none">
                {[8,15,24,52,100,200].map(v=>(
                  <button key={v} onClick={()=>!running&&setCycles(v)} disabled={running}
                    className="hover:text-emerald-400 transition-colors">{v}</button>
                ))}
              </div>
              <div className="mt-3 flex items-start gap-2 p-2.5 rounded-xl border border-emerald-800/50 bg-emerald-950/20">
                <Activity className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5"/>
                <p className="text-[11px] text-emerald-300 leading-snug">
                  <span className="font-bold">Real Engine — background job mode.</span>{' '}
                  Runs in a daemon thread; no HTTP proxy timeout. Live week progress shown while running.
                  Each week calls real production services (draw, SDE, waitlist, A/B/C, Brain 2/3/5).
                  52 weeks ≈ 2–4 min on shared CPU.
                </p>
              </div>
            </>
          ) : (
            /* ── Fast Preview: 1–1000 cycles ──────────────────────────────── */
            <>
              <input type="range" min={1} max={1000} step={1}
                value={cycles} disabled={running}
                onChange={e=>setCycles(parseInt(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer accent-violet-500 disabled:opacity-40"
                style={{background:`linear-gradient(to right,#7c3aed ${cycles/10}%,#334155 ${cycles/10}%)`}}
              />
              <div className="flex justify-between text-[10px] text-slate-600 mt-1.5 select-none">
                {[1,250,500,750,1000].map(v=>(
                  <button key={v} onClick={()=>!running&&setCycles(v)} disabled={running}
                    className="hover:text-violet-400 transition-colors">{v.toLocaleString()}</button>
                ))}
              </div>
              {cycles>=500&&!running&&(
                <p className="text-[11px] text-amber-400 flex items-center gap-1.5 mt-2">
                  <AlertTriangle className="w-3.5 h-3.5"/>
                  {cycles>=800?`${cycles} cycles — expect 45–90s`:`${cycles} cycles — expect 20–45s`}
                </p>
              )}
            </>
          )}
        </div>

        {/* ── Real Engine Config (only visible when Real Engine is active) ──── */}
        {useRealEngine && (
          <div className="border border-emerald-800/50 rounded-xl overflow-hidden bg-emerald-950/10">
            <button
              onClick={() => setShowRealCfg(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3 bg-emerald-950/30 hover:bg-emerald-950/50 transition-colors"
            >
              <p className="text-xs font-bold text-emerald-400 uppercase tracking-widest flex items-center gap-2">
                🔬 Real Engine — Load Configuration
              </p>
              <span className="text-emerald-600 text-xs">{showRealCfg ? '▲ collapse' : '▼ expand'}</span>
            </button>
            {showRealCfg && (
              <div className="p-4 grid grid-cols-3 gap-4">
                {/* Users per week */}
                <div>
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                    Users / Week
                  </label>
                  <div className="flex items-center gap-2">
                    <input type="number" min={0} max={2000} value={usersPerWeek} disabled={running}
                      onChange={e => setUsersPerWeek(Math.max(0, parseInt(e.target.value) || 0))}
                      className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 font-bold disabled:opacity-40"
                    />
                    <span className="text-[10px] text-slate-500 whitespace-nowrap">users/wk</span>
                  </div>
                  <p className="text-[10px] text-slate-600 mt-1">New waitlist joins per week</p>
                </div>
                {/* Initial seed */}
                <div>
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                    Seed Users
                  </label>
                  <div className="flex items-center gap-2">
                    <input type="number" min={12} max={5000} value={initialUsers} disabled={running}
                      onChange={e => setInitialUsers(Math.max(12, parseInt(e.target.value) || 12))}
                      className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 font-bold disabled:opacity-40"
                    />
                    <span className="text-[10px] text-slate-500 whitespace-nowrap">before W1</span>
                  </div>
                  <p className="text-[10px] text-slate-600 mt-1">Pre-seeded before week 1</p>
                </div>
                {/* Organic ratio */}
                <div>
                  <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                    Organic % <span className="text-slate-600 normal-case font-normal">(Brain 3 RDR)</span>
                  </label>
                  <div className="flex items-center gap-2">
                    <input type="number" min={0} max={100} value={organicRatio} disabled={running}
                      onChange={e => setOrganicRatio(Math.max(0, Math.min(100, parseInt(e.target.value) || 0)))}
                      className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 font-bold disabled:opacity-40"
                    />
                    <span className="text-[10px] text-slate-500">%</span>
                  </div>
                  <p className="text-[10px] text-slate-600 mt-1">100% = all organic, 0% = all referral</p>
                </div>
              </div>
            )}
            {/* Architecture note */}
            <div className="px-4 pb-3">
              <div className="bg-emerald-950/30 border border-emerald-900/50 rounded-lg p-2.5 text-[10px] text-emerald-400/70 leading-relaxed">
                <span className="font-bold text-emerald-400">Zero-Duplication Guarantee:</span> This engine calls{' '}
                <code className="text-emerald-300">draw.execute_weekly_draw()</code>,{' '}
                <code className="text-emerald-300">sde_engine.run_sde_meta_pool()</code>,{' '}
                <code className="text-emerald-300">waitlist.assign_waitlist_to_pools()</code>, and{' '}
                <code className="text-emerald-300">brain5_lpi_engine</code> directly — on an isolated in-memory SQLite DB
                with mocked time. Any rule change in production is reflected automatically.
              </div>
            </div>
          </div>
        )}

        {/* ── K-12 to K-17: Advanced Injection Knobs (collapsible) ─────────── */}
        {useRealEngine && (
          <div className="border border-cyan-800/40 rounded-xl overflow-hidden bg-cyan-950/10">
            <button
              onClick={() => setShowKnobs(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3 bg-cyan-950/20 hover:bg-cyan-950/40 transition-colors"
            >
              <p className="text-xs font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2">
                🔬 K-12 to K-17 — Advanced Injection Knobs
              </p>
              <span className="text-cyan-600 text-xs">{showKnobs ? '▲ collapse' : '▼ expand'}</span>
            </button>
            {showKnobs && (
              <div className="p-4 space-y-4">
                {/* K-17: Simulation Label */}
                <DevInput label="K-17 — Simulation Label" hint="(free text, for multi-run comparison)" type="text"
                  placeholder="e.g. high-growth scenario" value={simulationLabel} disabled={running}
                  onChange={e => setSimulationLabel(e.target.value)} />

                {/* K-12: Inflow Pattern */}
                <DevSelect label="K-12 — Inflow Pattern" hint="(shape of weekly new-user arrival curve)"
                  value={inflowPattern} disabled={running} onChange={e => setInflowPattern(e.target.value)}>
                  <option value="linear">Linear — constant users_per_week (default)</option>
                  <option value="sine">Sine — ±50% oscillation, 12-week period</option>
                  <option value="burst">Burst — 3× spike every 8th week, normal otherwise</option>
                  <option value="step">Step — ramp 50%→150% of base over full run</option>
                </DevSelect>

                <div className="grid grid-cols-2 gap-4">
                  {/* K-13: Referral burst week */}
                  <div>
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                      K-13 — Referral Burst Week <span className="text-slate-600 font-normal">(0=off)</span>
                    </label>
                    <input type="number" min={0} max={200} value={referralBurstWeek} disabled={running}
                      onChange={e => setReferralBurstWeek(Math.max(0, parseInt(e.target.value)||0))}
                      className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 font-bold disabled:opacity-40" />
                    <p className="text-[10px] text-slate-600 mt-0.5">2× referral surge on this week</p>
                  </div>

                  {/* K-14: Payment shock week */}
                  <div>
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                      K-14 — Payment Shock Week <span className="text-slate-600 font-normal">(0=off)</span>
                    </label>
                    <input type="number" min={0} max={200} value={paymentShockWeek} disabled={running}
                      onChange={e => setPaymentShockWeek(Math.max(0, parseInt(e.target.value)||0))}
                      className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 font-bold disabled:opacity-40" />
                    <p className="text-[10px] text-slate-600 mt-0.5">Late ratio spikes to 20% this week</p>
                  </div>

                  {/* K-15: Waitlist dropout */}
                  <div>
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                      K-15 — Waitlist Dropout % <span className="text-slate-600 font-normal">(0–50)</span>
                    </label>
                    <div className="flex items-center gap-2">
                      <input type="number" min={0} max={50} step={0.5} value={waitlistDropoutPct} disabled={running}
                        onChange={e => setWaitlistDropoutPct(Math.max(0, Math.min(50, parseFloat(e.target.value)||0)))}
                        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 font-bold disabled:opacity-40" />
                      <span className="text-[10px] text-slate-500">%</span>
                    </div>
                    <p className="text-[10px] text-slate-600 mt-0.5">% of waitlist who never enter pools</p>
                  </div>

                  {/* K-16: Organic decay rate */}
                  <div>
                    <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1.5">
                      K-16 — Organic Decay Rate <span className="text-slate-600 font-normal">(0–100%)</span>
                    </label>
                    <div className="flex items-center gap-2">
                      <input type="number" min={0} max={100} step={0.5} value={organicDecayRate} disabled={running}
                        onChange={e => setOrganicDecayRate(Math.max(0, Math.min(100, parseFloat(e.target.value)||0)))}
                        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1.5 text-sm text-slate-200 font-bold disabled:opacity-40" />
                      <span className="text-[10px] text-slate-500">%/wk</span>
                    </div>
                    <p className="text-[10px] text-slate-600 mt-0.5">Organic ratio decays by this % each week</p>
                  </div>
                </div>

                {/* Active knobs summary */}
                {(inflowPattern !== 'linear' || referralBurstWeek > 0 || paymentShockWeek > 0 || waitlistDropoutPct > 0 || organicDecayRate > 0 || simulationLabel) && (
                  <div className="flex flex-wrap gap-1.5">
                    {inflowPattern !== 'linear' && <span className="px-2 py-0.5 bg-cyan-900/60 border border-cyan-700/60 rounded-full text-[10px] text-cyan-300 font-bold">K-12: {inflowPattern}</span>}
                    {referralBurstWeek > 0 && <span className="px-2 py-0.5 bg-cyan-900/60 border border-cyan-700/60 rounded-full text-[10px] text-cyan-300 font-bold">K-13: burst wk{referralBurstWeek}</span>}
                    {paymentShockWeek > 0 && <span className="px-2 py-0.5 bg-red-900/60 border border-red-700/60 rounded-full text-[10px] text-red-300 font-bold">K-14: shock wk{paymentShockWeek}</span>}
                    {waitlistDropoutPct > 0 && <span className="px-2 py-0.5 bg-amber-900/60 border border-amber-700/60 rounded-full text-[10px] text-amber-300 font-bold">K-15: {waitlistDropoutPct}% dropout</span>}
                    {organicDecayRate > 0 && <span className="px-2 py-0.5 bg-violet-900/60 border border-violet-700/60 rounded-full text-[10px] text-violet-300 font-bold">K-16: {organicDecayRate}%/wk decay</span>}
                    {simulationLabel && <span className="px-2 py-0.5 bg-slate-700/80 border border-slate-600 rounded-full text-[10px] text-slate-300 font-bold">K-17: "{simulationLabel}"</span>}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── A/B/C Circular Late-Fee Parameters ───────────────────────────── */}
        <div className="border border-slate-600/60 rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-slate-800/60 border-b border-slate-700/60">
            <p className="text-xs font-bold text-amber-400 uppercase tracking-widest flex items-center gap-2">
              <ShieldAlert className="w-3.5 h-3.5"/>Circular Late-Fee Parameters A ⟷ B ⟷ C
            </p>
            <p className="text-[10px] text-slate-500 mt-0.5">These three parameters are co-related. Changing one affects the system's real effective elimination rate.</p>
          </div>
          <div className="p-4 space-y-5">
            {/* Late payers ratio (who misses due date) */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs text-slate-300 font-semibold">Late Members % <span className="text-slate-500 font-normal">(of all active, miss due date)</span></label>
                <div className="bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1 text-sm font-black text-slate-200">{lateRatio.toFixed(1)}%</div>
              </div>
              <input type="range" min={0} max={30} step={0.5} value={lateRatio} disabled={running}
                onChange={e=>setLateRatio(parseFloat(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer accent-slate-400 disabled:opacity-40"
                style={{background:`linear-gradient(to right,#94a3b8 ${lateRatio/30*100}%,#334155 ${lateRatio/30*100}%)`}}/>
              <p className="text-[10px] text-slate-600 mt-1">Feeds into: A (direct elim pool) + C (grace period pool)</p>
            </div>

            {/* A — Elimination % */}
            <div className="p-3 rounded-xl border border-red-900/50 bg-red-950/20">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-bold text-red-300 uppercase tracking-wider">A — Elimination % <span className="text-red-500/60 font-normal normal-case">(skip grace, directly eliminated)</span></label>
                <div className="bg-red-950 border border-red-800 rounded-lg px-2.5 py-1 text-sm font-black text-red-300">{elimPctA.toFixed(2)}%</div>
              </div>
              <input type="range" min={0.05} max={100} step={0.05} value={elimPctA} disabled={running}
                onChange={e=>setElimPctA(parseFloat(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer disabled:opacity-40"
                style={{background:`linear-gradient(to right,#ef4444 ${elimPctA}%,#334155 ${elimPctA}%)`}}/>
              <div className="flex justify-between text-[10px] text-slate-600 mt-1 select-none"><span>0.05%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
            </div>

            {/* B — Late Fee Rate */}
            <div className="p-3 rounded-xl border border-amber-900/50 bg-amber-950/20">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-bold text-amber-300 uppercase tracking-wider">B — Late Fee Rate <span className="text-amber-500/60 font-normal normal-case">(% of ₹1000 deposit per day)</span></label>
                <div className="flex items-center gap-1.5">
                  <div className="bg-amber-950 border border-amber-800 rounded-lg px-2.5 py-1 text-sm font-black text-amber-300">{lateFeeB.toFixed(1)}%</div>
                  <div className="text-[10px] text-amber-600 font-semibold">= ₹{lateFeeINR}/day</div>
                </div>
              </div>
              <input type="range" min={5} max={100} step={0.5} value={lateFeeB} disabled={running}
                onChange={e=>setLateFeeB(parseFloat(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer disabled:opacity-40"
                style={{background:`linear-gradient(to right,#f59e0b ${(lateFeeB-5)/95*100}%,#334155 ${(lateFeeB-5)/95*100}%)`}}/>
              <div className="flex justify-between text-[10px] text-slate-600 mt-1 select-none"><span>5% min (₹50/day)</span><span>50%</span><span>100% (₹1000/day)</span></div>
              <p className="text-[10px] text-amber-700/80 mt-1">Higher B → fewer members attempt grace period (C↓ follows B↑)</p>
            </div>

            {/* C — Grace Saver % */}
            <div className="p-3 rounded-xl border border-violet-900/50 bg-violet-950/20">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-bold text-violet-300 uppercase tracking-wider">C — Grace Saver % <span className="text-violet-500/60 font-normal normal-case">(of at-risk, pay grace fee + late fee)</span></label>
                <div className="bg-violet-950 border border-violet-800 rounded-lg px-2.5 py-1 text-sm font-black text-violet-300">{gracePctC.toFixed(2)}%</div>
              </div>
              <input type="range" min={0.05} max={100} step={0.05} value={gracePctC} disabled={running}
                onChange={e=>setGracePctC(parseFloat(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer disabled:opacity-40"
                style={{background:`linear-gradient(to right,#7c3aed ${gracePctC}%,#334155 ${gracePctC}%)`}}/>
              <div className="flex justify-between text-[10px] text-slate-600 mt-1 select-none"><span>0.05%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
            </div>

            {/* Circular effect summary */}
            <div className="flex items-center gap-3 p-3 bg-slate-800/60 rounded-xl border border-slate-700/40">
              <div className="text-[10px] text-slate-400 flex-1 space-y-0.5">
                <p>↳ <span className="text-red-400 font-bold">A={elimPctA.toFixed(1)}%</span> eliminated directly · remaining <span className="text-violet-400 font-bold">{(100-elimPctA).toFixed(1)}%</span> enter grace period</p>
                <p>↳ Of grace-eligible: <span className="text-violet-400 font-bold">C={gracePctC.toFixed(1)}%</span> pay B=₹{lateFeeINR}/day + ₹500 seat fee → saved</p>
                <p>↳ <span className="text-orange-400 font-bold">Effective total elim = {effectiveElim.toFixed(1)}%</span> of late payers ({(effectiveElim/100*lateRatio).toFixed(2)}% of all active)</p>
              </div>
            </div>
          </div>
        </div>

        {/* Volatility */}
        <div className={`p-4 rounded-xl border select-none transition-colors ${vol?'bg-violet-950/30 border-violet-700/60':'bg-slate-800/50 border-slate-700/50'} ${running?'opacity-50 pointer-events-none':'cursor-pointer'}`} onClick={()=>!running&&setVol(v=>!v)}>
          <div className="flex items-center justify-between">
            <div>
              <p className={`text-xs font-semibold ${vol?'text-violet-300':'text-slate-300'}`}>Market Volatility Mode</p>
              <p className="text-[10px] text-slate-500 mt-0.5">Randomise weekly inflow (5–N users). Off = fixed 12/cycle.</p>
            </div>
            <Toggle checked={vol} onChange={()=>{}} label="Volatility" disabled={running}/>
          </div>
          {vol&&<div className="mt-4 pt-4 border-t border-violet-800/40" onClick={e=>e.stopPropagation()}>
            <DevInput label="Max Weekly Inflow" hint="(≥5)" type="number" min={5} value={volMax} disabled={running} onChange={e=>setVolMax(Math.max(5,parseInt(e.target.value)||5))}/>
          </div>}
        </div>

        {/* RDR */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-slate-400 font-medium">Avg RDR % (Referral Density Ratio)</label>
            <div className="bg-cyan-950/60 border border-cyan-800/60 rounded-xl px-3 py-1.5 min-w-[60px] text-center">
              <span className="text-sm font-black text-cyan-300">{rdr.toFixed(0)}</span>
              <span className="text-[10px] text-slate-500 font-semibold ml-0.5">%</span>
            </div>
          </div>
          <input type="range" min={0} max={100} step={1} value={rdr} disabled={running}
            onChange={e=>setRdr(parseFloat(e.target.value))}
            className="w-full h-2 rounded-full appearance-none cursor-pointer accent-cyan-500 disabled:opacity-40"
            style={{background:`linear-gradient(to right,#06b6d4 ${rdr}%,#334155 ${rdr}%)`}}
          />
          <div className="flex justify-between text-[10px] text-slate-600 mt-1 select-none">
            <span>Organic</span>
            <span className={rdr>70?'text-amber-400':''}>{rdr>70?'⚡ Flash Flood':rdr<30?'🌊 Sustainable Wave':'⚖️ Mixed'}</span>
            <span>Referral</span>
          </div>
        </div>

        {/* ── Pre-Test Setup (collapsible) ─────────────────────────────────── */}
        <div className={`border rounded-xl overflow-hidden transition-colors ${showSetup ? 'border-slate-600' : 'border-slate-700/40'}`}>
          <button
            type="button"
            onClick={() => setShowSetup(v => !v)}
            disabled={running}
            className={`w-full flex items-center justify-between px-5 py-3.5 transition-colors text-left ${showSetup ? 'bg-slate-800' : 'bg-slate-800/30 hover:bg-slate-800/60'} disabled:opacity-40`}
          >
            <div className="flex items-center gap-2.5">
              <Settings className="w-4 h-4 text-slate-500 flex-shrink-0" />
              <span className="text-xs font-bold text-slate-300 uppercase tracking-wider">Pre-Test Setup</span>
              <span className="hidden sm:inline text-[10px] text-slate-600 ml-1">Set DB payment state before launching</span>
            </div>
            <ChevronRight className={`w-4 h-4 text-slate-500 flex-shrink-0 transition-transform duration-200 ${showSetup ? 'rotate-90' : ''}`} />
          </button>
          {showSetup && (
            <div className="border-t border-slate-700/60">
              <ControlsTab toast={toast} />
            </div>
          )}
        </div>

        <button onClick={run} disabled={running}
          className={`w-full relative overflow-hidden flex items-center justify-center gap-2.5 font-extrabold py-4 px-6 rounded-xl text-base transition-all duration-300 ${
            running?'bg-slate-800 text-slate-500 cursor-not-allowed':'bg-gradient-to-r from-violet-700 via-purple-700 to-violet-700 hover:from-violet-600 hover:via-purple-600 hover:to-violet-600 text-white shadow-2xl shadow-violet-900/50 active:scale-[0.98]'
          }`}>
          {!running&&<span className="absolute inset-0 opacity-0 hover:opacity-100 transition-opacity duration-500" style={{background:'linear-gradient(105deg,transparent 40%,rgba(167,139,250,0.3) 50%,transparent 60%)'}}/>}
          {running?<><Spinner className="w-5 h-5 text-slate-500"/>Running {cycles.toLocaleString()} cycles…</>:<><FlaskConical className="w-5 h-5"/>Launch System Stress-Test</>}
        </button>

        {result&&!running&&(
          <div className="border-t border-slate-700/60 pt-6">

            {/* ── Error panel + Debugger ─────────────────────────────────────── */}
            {result._error && <SimErrorDebugger result={result} />}

            {/* Report header + download buttons (only when simulation succeeded) */}
            {!result._error && <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0"/>
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">
                  Simulation Complete — {result.simulation_summary.total_cycles_run.toLocaleString()} cycles
                </p>
                {result.engine === 'real'
                  ? <span className="text-[9px] font-black px-1.5 py-0.5 rounded-full bg-emerald-900/60 border border-emerald-700/60 text-emerald-300 uppercase tracking-wider">🔬 Real Engine</span>
                  : <span className="text-[9px] font-black px-1.5 py-0.5 rounded-full bg-violet-900/60 border border-violet-700/60 text-violet-300 uppercase tracking-wider">⚡ Fast Preview</span>
                }
                {result.simulation_summary.simulation_label && result.simulation_summary.simulation_label !== 'default' && (
                  <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-cyan-900/60 border border-cyan-700/60 text-cyan-300">
                    K-17: "{result.simulation_summary.simulation_label}"
                  </span>
                )}
                {result.simulation_summary.injection_knobs && (() => {
                  const k = result.simulation_summary.injection_knobs
                  const active = []
                  if (k.inflow_pattern && k.inflow_pattern !== 'linear') active.push(`K-12:${k.inflow_pattern}`)
                  if (k.referral_burst_week > 0) active.push(`K-13:wk${k.referral_burst_week}`)
                  if (k.payment_shock_week > 0) active.push(`K-14:wk${k.payment_shock_week}`)
                  if (k.waitlist_dropout_pct > 0) active.push(`K-15:${k.waitlist_dropout_pct}%drop`)
                  if (k.organic_decay_rate > 0) active.push(`K-16:decay${(k.organic_decay_rate*100).toFixed(1)}%`)
                  return active.map(tag => (
                    <span key={tag} className="text-[8px] font-bold px-1.5 py-0.5 rounded-full bg-slate-700/80 border border-slate-600 text-slate-400">{tag}</span>
                  ))
                })()}
              </div>
              <div className="flex gap-2">
                <button onClick={()=>downloadCSV(result.weekly_detail, `sim_weekly_${Date.now()}.csv`)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold bg-slate-800 border border-slate-600 rounded-lg text-slate-300 hover:bg-slate-700 transition">
                  <Download className="w-3 h-3"/>CSV
                </button>
                <button onClick={()=>{
                  const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'})
                  const url=URL.createObjectURL(blob); const a=document.createElement('a')
                  a.href=url; a.download=`sim_report_${Date.now()}.json`
                  document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
                }} className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold bg-slate-800 border border-slate-600 rounded-lg text-slate-300 hover:bg-slate-700 transition">
                  <Download className="w-3 h-3"/>JSON
                </button>
              </div>
            </div>}

            {/* 6-tab report navigation + all tab content — only when no error */}
            {!result._error && (
              <>
                <div className="flex gap-1 flex-wrap mb-5">
                  {REPORT_TABS.map(t=>(
                    <button key={t.id} onClick={()=>setReportTab(t.id)}
                      className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-colors ${
                        reportTab===t.id
                          ?'bg-violet-700 text-white'
                          :'bg-slate-800 text-slate-400 border border-slate-700/60 hover:bg-slate-700/80'
                      }`}>
                      <span className="hidden sm:inline">{t.label}</span>
                      <span className="sm:hidden">{t.short}</span>
                    </button>
                  ))}
                </div>

                {/* ── Tab: Summary ── */}
                {reportTab==='summary'&&(
                  <div>
                    {result.simulation_summary.system_health?.max_l5_count>0&&(
                      <div className="flex gap-2.5 p-3 mb-4 rounded-xl bg-red-950/30 border border-red-800/40 text-xs text-red-300">
                        <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5"/>
                        <span>
                          <strong>Anti-Maturity Pressure Detected:</strong>&nbsp;
                          L5 peak = {result.simulation_summary.system_health.max_l5_count},&nbsp;
                          L6 peak = {result.simulation_summary.system_health.max_l6_count}.&nbsp;
                          Longest high-LPI streak = {result.simulation_summary.system_health.max_high_lpi_streak_weeks} weeks.
                          {result.simulation_summary.system_health.max_l6_count>=3&&' ⚠️ Pool pauses likely.'}
                        </span>
                      </div>
                    )}
                    <SimStatsGrid s={result.simulation_summary}/>
                    <SystemHealth fm={result.simulation_summary.financial_metrics} sh={result.simulation_summary.system_health}/>
                    <LevelMatrix levelWise={result.simulation_summary.level_wise_metrics}/>
                  </div>
                )}

                {/* ── Tab: Weekly Report ── */}
                {reportTab==='weekly'&&(
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <p className="text-xs text-slate-400">{result.weekly_detail?.length??0} weeks of data</p>
                      <button onClick={()=>downloadCSV(result.weekly_detail, `sim_weekly_${Date.now()}.csv`)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-bold bg-slate-800 border border-slate-600 rounded-lg text-slate-300 hover:bg-slate-700 transition">
                        <Download className="w-3 h-3"/>Export CSV
                      </button>
                    </div>
                    <WeeklyReportTable rows={result.weekly_detail}/>
                  </div>
                )}

                {/* ── Tab: Pool Activity ── */}
                {reportTab==='pools'&&(
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-3">Active Pools · Pauses · Merges Per Week</p>
                    {/* D2 FIX: weekly_detail has pools_active/pools_paused/pools_formed */}
                    <PoolActivityChart logs={result.weekly_detail}/>
                    <div className="mt-4 grid grid-cols-3 gap-3">
                      <StatPill label="Total Pools Formed" value={result.simulation_summary.total_pools_auto_scaled} accent="violet"/>
                      <StatPill label="Total Condensations" value={result.simulation_summary.total_condensation_events} accent="amber"/>
                      <StatPill label="Total Draw Pauses"  value={result.simulation_summary.total_draw_pauses_triggered} accent="red"/>
                    </div>
                  </div>
                )}

                {/* ── Tab: Draw Analysis ── */}
                {reportTab==='draws'&&(
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-3">Draw Type Breakdown Per Week</p>
                    <DrawAnalysisChart weekly={result.weekly_detail}/>
                    <div className="mt-4 grid grid-cols-4 gap-3">
                      <StatPill label="Total Draws"  value={result.simulation_summary.total_winners_drawn/2} accent="blue"/>
                      <StatPill label="SDE Exits"    value={result.simulation_summary.system_health?.total_sde_exits??0} accent="red"/>
                      <StatPill label="Type A Draws" value={result.simulation_summary.system_health?.total_type_a_draws??0} accent="violet"/>
                      <StatPill label="Type B Draws" value={result.simulation_summary.system_health?.total_type_b_draws??0} accent="amber"/>
                    </div>
                  </div>
                )}

                {/* ── Tab: Cash Flow ── */}
                {reportTab==='cashflow'&&(
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-3">Cash Inflow Breakdown Per Week</p>
                    <CashFlowChart weekly={result.weekly_detail}/>
                    <div className="mt-4 grid grid-cols-3 gap-3">
                      <StatPill label="Total Collected" value={INR(result.simulation_summary.financial_metrics?.total_collected_inr??0)} accent="emerald"/>
                      <StatPill label="Total Paid Out"  value={INR(result.simulation_summary.financial_metrics?.total_distributed_inr??0)} accent="red"/>
                      <StatPill label="Net Float"       value={INR(result.simulation_summary.final_virtual_liquidity_float??0)} accent="blue"/>
                    </div>
                  </div>
                )}

                {/* ── Tab: Level Progression ── */}
                {reportTab==='levels'&&(
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-3">Member Level Distribution Over Time</p>
                    <LevelProgressionChart weekly={result.weekly_detail} logs={result.cycle_logs}/>
                    <div className="mt-4 grid grid-cols-3 gap-3">
                      <StatPill label="L5 Peak" value={result.simulation_summary.system_health?.max_l5_count??0} accent={result.simulation_summary.system_health?.max_l5_count>0?'red':'slate'}/>
                      <StatPill label="L6 Peak" value={result.simulation_summary.system_health?.max_l6_count??0} accent={result.simulation_summary.system_health?.max_l6_count>0?'red':'slate'}/>
                      <StatPill label="High-LPI Streak" value={`${result.simulation_summary.system_health?.max_high_lpi_streak_weeks??0} wks`} accent={result.simulation_summary.system_health?.max_high_lpi_streak_weeks>=3?'amber':'slate'}/>
                    </div>
                  </div>
                )}

                {/* Classic charts at bottom of Summary tab only */}
                {reportTab==='summary'&&(
                  <>
                    {/* D1 FIX [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
                        SimCharts now receives weekly_detail (has pools_active, waitlist_count)
                        instead of cycle_logs (which only has week/pauses/draws/inflow). */}
                    <SimCharts logs={result.weekly_detail}/>
                    <AiBrainCharts logs={result.cycle_logs}/>
                  </>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// TAB 1 — DRAW CONTROL (Force Draw + Time Travel + Date override)
// ─────────────────────────────────────────────────────────────────────────────

function WinnerCard({ slot, winner }) {
  return (
    <div className="bg-slate-800 rounded-xl border border-slate-600/50 p-4 space-y-2.5">
      <div className="flex items-center gap-2"><span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">{slot}</span><span className="bg-purple-900/60 border border-purple-700/60 text-purple-300 text-[10px] font-bold px-2 py-0.5 rounded-full">LEVEL {winner.level}</span></div>
      <p className="text-base font-bold text-white">{winner.username}</p>
      <p className="text-xl font-bold text-emerald-400 tabular-nums">{INR(winner.net_payout_inr)}</p>
      <div><p className="text-[10px] text-slate-500 font-medium mb-1">WITHDRAW TOKEN</p><code className="block text-xs font-mono bg-slate-900/80 rounded-lg px-3 py-2 text-amber-300 tracking-widest border border-slate-700/60">{winner.withdraw_token}</code></div>
      {winner.replaced_by&&<p className="text-[10px] text-slate-500">Filled by <span className="text-slate-300 font-semibold">{winner.replaced_by}</span></p>}
    </div>
  )
}

function RefillSummary({ refill }) {
  if (!refill) return null
  const hasP3 = (refill.phase3_transfers??0) > 0
  return (
    <div className="mt-4 bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 space-y-3">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">Triple-Phase FIFO Refill</p>
      <div><p className="text-[9px] font-bold text-blue-400 uppercase tracking-widest mb-1.5">Phase 1 — Waitlist Fill</p><StatPill label="Assigned" value={refill.phase1_assigned} accent="blue"/></div>
      <div><p className="text-[9px] font-bold text-emerald-400 uppercase tracking-widest mb-1.5">Phase 2 — Auto-Scale</p><StatPill label="New Pool" value={refill.phase2_pool_created??'none'} accent={refill.phase2_pool_created?'emerald':'slate'}/></div>
      <div><p className="text-[9px] font-bold text-amber-400 uppercase tracking-widest mb-1.5">Phase 3 — Condensation</p>
        {!hasP3?<p className="text-[10px] text-slate-600 italic">No condensation needed.</p>:<StatPill label="Members Transferred" value={refill.phase3_transfers} accent="amber"/>}
      </div>
    </div>
  )
}

function DrawControlTab({ toast }) {
  const [drawPoolId, setDrawPoolId] = useState('')
  const [autoPayInst, setAutoPayInst] = useState(false)
  const [drawLoading, setDrawLoading] = useState(false)
  const [drawResult, setDrawResult] = useState(null)
  // Sim cycle
  const [simCycles, setSimCycles] = useState(3)
  const [simCleanup, setSimCleanup] = useState(true)
  const [simAutoPayInst, setSimAutoPayInst] = useState(false)
  const [simLoading, setSimLoading] = useState(false)
  const [simResult, setSimResult] = useState(null)

  const handleDraw = async () => {
    setDrawLoading(true); setDrawResult(null)
    try {
      const pid = drawPoolId.trim() ? parseInt(drawPoolId.trim(),10) : undefined
      const res = await forceDrawDev(pid, autoPayInst)
      setDrawResult(res.data)
      const msg = res.data.mode==='mass_draw' ? `Mass draw — ${res.data.pools_drawn} pool(s)` : `Draw — ${res.data.pool_name}`
      toast(msg, 'success')
    } catch(err){ toast(err.response?.data?.detail??'Draw failed','error') }
    finally { setDrawLoading(false) }
  }

  const handleSim = async () => {
    setSimLoading(true); setSimResult(null)
    try {
      const res = await simulateCycleDev(simCycles, simCleanup, simAutoPayInst)
      setSimResult(res.data)
      toast(`${res.data.n_executed} cycles simulated`, 'success')
    } catch(err){ toast(err.response?.data?.detail??'Sim failed','error') }
    finally { setSimLoading(false) }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Force Draw */}
        <DevCard icon={Zap} iconBg="bg-amber-900/40 border border-amber-700/50" iconColor="text-amber-400" title="Force Draw" subtitle="Execute the Sunday dual-draw instantly">
          <div className="space-y-4">
            <DevInput label="Target Pool ID" hint="(optional — blank = mass draw)" type="number" min={1} value={drawPoolId} onChange={e=>setDrawPoolId(e.target.value)} placeholder="Leave blank for all pools"/>
            <div className={`flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer select-none transition-colors ${autoPayInst?'bg-amber-950/30 border-amber-700/60':'bg-slate-800/50 border-slate-700/50'}`} onClick={()=>setAutoPayInst(v=>!v)}>
              <div className={`mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${autoPayInst?'bg-amber-500 border-amber-500':'border-slate-500'}`}>
                {autoPayInst&&<svg viewBox="0 0 12 12" className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth={2.5}><polyline points="1.5,6 4.5,9 10.5,3"/></svg>}
              </div>
              <div><p className={`text-xs font-semibold ${autoPayInst?'text-amber-300':'text-slate-300'}`}>Simulate Token Cash Inflow</p><p className="text-[10px] text-slate-500 mt-1">Creates real Burned DEP records for accurate stats.</p></div>
            </div>
            <button onClick={handleDraw} disabled={drawLoading} className="w-full flex items-center justify-center gap-2 bg-amber-700 hover:bg-amber-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 rounded-xl transition shadow-lg shadow-amber-900/20">
              {drawLoading?<><Spinner className="w-4 h-4"/>Running…</>:<><Zap className="w-4 h-4"/>Execute Draw</>}
            </button>
            {drawResult&&<ResultBox>
              {drawResult.mode==='mass_draw'?(
                <>
                  <div className="flex flex-wrap gap-2">
                    <span className="bg-purple-950 border border-purple-800 text-purple-300 text-xs px-3 py-1.5 rounded-lg">{drawResult.pools_drawn} pool(s) drawn</span>
                    {drawResult.skipped_pools?.length>0&&<span className="bg-red-950 border border-red-800 text-red-300 text-xs px-3 py-1.5 rounded-lg">Skipped: {drawResult.skipped_pools.join(', ')}</span>}
                  </div>
                  {drawResult.draws?.length>0&&<div className="overflow-x-auto rounded-xl border border-slate-700/60 mt-2"><table className="w-full text-xs whitespace-nowrap"><thead className="bg-slate-800/80"><tr>{['Pool','W1','Lvl','₹','W2','Lvl','₹','Mode'].map(h=><th key={h} className="text-left py-2.5 px-3 text-slate-400 text-[10px]">{h}</th>)}</tr></thead><tbody>{drawResult.draws.map(d=><tr key={d.pool_id} className="border-b border-slate-800/60"><td className="py-2.5 px-3 font-bold text-slate-300">{d.pool_name}</td><td className="py-2.5 px-3 font-mono text-slate-300 max-w-[100px]"><span className="block truncate">{d.winner_1.username}</span></td><td className="py-2.5 px-3"><span className="bg-purple-900/60 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">L{d.winner_1.level}</span></td><td className="py-2.5 px-3 text-emerald-400 font-bold">{INR(d.winner_1.net_payout_inr)}</td><td className="py-2.5 px-3 font-mono text-slate-300 max-w-[100px]"><span className="block truncate">{d.winner_2.username}</span></td><td className="py-2.5 px-3"><span className="bg-purple-900/60 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">L{d.winner_2.level}</span></td><td className="py-2.5 px-3 text-emerald-400 font-bold">{INR(d.winner_2.net_payout_inr)}</td><td className="py-2.5 px-3 text-[10px]">{d.edge_case_used?<span className="text-amber-300">⚡ Early</span>:<span className="text-emerald-300">✓ Normal</span>}</td></tr>)}</tbody></table></div>}
                  <RefillSummary refill={drawResult.refill}/>
                </>
              ):(
                <><div className="grid grid-cols-2 gap-3"><WinnerCard slot="Winner 1 — Low" winner={drawResult.winner_1}/><WinnerCard slot="Winner 2 — High" winner={drawResult.winner_2}/></div></>
              )}
            </ResultBox>}
          </div>
        </DevCard>

        {/* Time-Travel Simulator */}
        <DevCard icon={Clock} iconBg="bg-blue-900/40 border border-blue-700/50" iconColor="text-blue-400" title="Time-Travel Simulator" subtitle="Fast-forward N weekly draw cycles on a generated pool">
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <DevInput label="Cycles" hint="(1–12)" type="number" min={1} max={12} value={simCycles} onChange={e=>setSimCycles(Math.min(12,Math.max(1,parseInt(e.target.value,10)||1)))}/>
              <div><p className="text-xs text-slate-400 font-medium mb-1.5">Cleanup After Run</p>
                <div className="flex items-center gap-3 h-10"><Toggle checked={simCleanup} onChange={setSimCleanup} label="Cleanup"/><span className="text-xs text-slate-300">{simCleanup?'Yes — purge':'No — keep'}</span></div>
              </div>
            </div>
            <div className={`flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer select-none transition-colors ${simAutoPayInst?'bg-blue-950/40 border-blue-700/60':'bg-slate-800/50 border-slate-700/50'}`} onClick={()=>setSimAutoPayInst(v=>!v)}>
              <div className={`mt-0.5 w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${simAutoPayInst?'bg-blue-500 border-blue-500':'border-slate-500'}`}>
                {simAutoPayInst&&<svg viewBox="0 0 12 12" className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth={2.5}><polyline points="1.5,6 4.5,9 10.5,3"/></svg>}
              </div>
              <div><p className={`text-xs font-semibold ${simAutoPayInst?'text-blue-300':'text-slate-300'}`}>Simulate Token Cash Inflow</p><p className="text-[10px] text-slate-500 mt-1">Creates real Burned DEP records each cycle for accurate stats.</p></div>
            </div>
            <button onClick={handleSim} disabled={simLoading} className="w-full flex items-center justify-center gap-2 bg-blue-700 hover:bg-blue-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 rounded-xl transition">
              {simLoading?<><Spinner className="w-4 h-4"/>Simulating…</>:<><Play className="w-4 h-4"/>Run {simCycles} Cycle{simCycles!==1?'s':''}</>}
            </button>
            {simResult&&<ResultBox>
              <div className="grid grid-cols-4 gap-3 mb-4">
                <StatPill label="Cycles"   value={`${simResult.n_executed}/${simResult.n_requested}`} accent="blue"/>
                <StatPill label="Users"    value={simResult.users_created} accent="slate"/>
                <StatPill label="Paid Out" value={INR(simResult.total_paid_out_inr)} accent="emerald"/>
                <StatPill label="Pool"     value={simResult.pool_id?`#${simResult.pool_id}`:'Cleaned'} accent={simResult.pool_id?'purple':'amber'}/>
              </div>
              <div className="overflow-x-auto rounded-xl border border-slate-700/60"><table className="w-full text-xs whitespace-nowrap"><thead className="bg-slate-800/80"><tr>{['#','W1','Lvl','₹','W2','Lvl','₹','Mode'].map(h=><th key={h} className="text-left py-2.5 px-3 text-slate-400 text-[10px]">{h}</th>)}</tr></thead><tbody>{simResult.draws.map((d,idx)=><tr key={d.cycle} className={`border-b border-slate-800/60 ${d.edge_case?'bg-amber-950/10':'bg-emerald-950/10'}`}><td className="py-2.5 px-3 font-bold text-slate-300">W{d.cycle}</td><td className="py-2.5 px-3 font-mono text-slate-300 max-w-[120px]"><span className="block truncate">{d.winner_1}</span></td><td className="py-2.5 px-3"><span className="bg-purple-900/60 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">L{d.level_1}</span></td><td className="py-2.5 px-3 text-emerald-400 font-bold">{INR(d.payout_1_inr)}</td><td className="py-2.5 px-3 font-mono text-slate-300 max-w-[120px]"><span className="block truncate">{d.winner_2}</span></td><td className="py-2.5 px-3"><span className="bg-purple-900/60 text-purple-300 px-1.5 py-0.5 rounded-full font-bold">L{d.level_2}</span></td><td className="py-2.5 px-3 text-emerald-400 font-bold">{INR(d.payout_2_inr)}</td><td className="py-2.5 px-3 text-[10px]">{d.edge_case?<span className="text-amber-300">⚡ Early</span>:<span className="text-emerald-300">✓ Mature</span>}</td></tr>)}</tbody></table></div>
            </ResultBox>}
          </div>
        </DevCard>
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// TAB 2 — INJECTION (timed + date/time + cadence)
// ─────────────────────────────────────────────────────────────────────────────

function InjectionTab({ toast }) {
  // Standard bulk inject
  const [count, setCount] = useState(1_000)
  const [autoPool, setAutoPool] = useState(true)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  // Timed inject
  const [tCount, setTCount] = useState(500)
  const [baseDate, setBaseDate] = useState('')
  const [spreadDays, setSpreadDays] = useState(7)
  const [randomize, setRandomize] = useState(true)
  const [useDailyCadence, setUseDailyCadence] = useState(false)
  const [dailyCount, setDailyCount] = useState(50)
  const [timedAutoPool, setTimedAutoPool] = useState(true)
  const [timedLoading, setTimedLoading] = useState(false)
  const [timedResult, setTimedResult] = useState(null)
  // Background pool-formation polling
  const [bgStatus, setBgStatus] = useState(null)   // null | {status, pools_formed, waitlist_remaining, error}
  const [bgPrefix, setBgPrefix] = useState(null)   // prefix key to poll
  const [bgPolling, setBgPolling] = useState(false)

  // Auto-poll injection status while bg task is running (every 2s)
  useEffect(() => {
    if (!bgPrefix || bgStatus?.status === 'done' || bgStatus?.status === 'error') return
    setBgPolling(true)
    const id = setInterval(async () => {
      try {
        const res = await getInjectionStatus(bgPrefix)
        setBgStatus(res.data)
        if (res.data.status === 'done') {
          toast(`Pool formation complete — ${res.data.pools_formed} pool(s) formed`, 'success')
          setBgPolling(false)
          clearInterval(id)
        } else if (res.data.status === 'error') {
          toast(`Pool formation error: ${res.data.error}`, 'error')
          setBgPolling(false)
          clearInterval(id)
        }
      } catch { /* ignore transient poll errors */ }
    }, 2_000)
    return () => { clearInterval(id); setBgPolling(false) }
  }, [bgPrefix, bgStatus?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleBulk = async () => {
    setLoading(true); setResult(null); setBgStatus(null); setBgPrefix(null)
    try {
      const res = await simulateUsersDev(count, autoPool)
      setResult(res.data)
      // When auto_pool=true, pool formation runs in background — start polling.
      // The response always has pools_formed=0 because formation is async;
      // the `prefix` field is the job key to poll.
      if (autoPool && res.data.prefix) {
        setBgPrefix(res.data.prefix)
        setBgStatus({ status: 'running', pools_formed: 0, waitlist_remaining: null, error: null })
        toast(
          `${res.data.users_created.toLocaleString()} users injected — pool formation running in background…`,
          'info'
        )
      } else {
        toast(`${res.data.users_created.toLocaleString()} users injected`, 'success')
      }
    } catch(err) { toast(err.response?.data?.detail ?? 'Injection failed', 'error') }
    finally{ setLoading(false) }
  }

  const handleTimed = async () => {
    setTimedLoading(true); setTimedResult(null); setBgStatus(null); setBgPrefix(null)
    try {
      const params = {
        count: tCount,
        base_date_iso: baseDate ? new Date(baseDate).toISOString() : null,
        spread_days: spreadDays,
        randomize_dates: randomize,
        daily_count: useDailyCadence ? dailyCount : null,
        auto_pool: timedAutoPool,
      }
      const res = await devInjectTimed(params)
      setTimedResult(res.data)
      if (res.data.pool_formation === 'background' && res.data.status_key) {
        // Large batch — pool formation running in background; start polling
        setBgPrefix(res.data.status_key)
        setBgStatus({ status: 'running', pools_formed: 0, waitlist_remaining: null, error: null })
        toast(`${res.data.users_created.toLocaleString()} users injected — pool formation running…`, 'info')
      } else {
        toast(`${res.data.users_created.toLocaleString()} timed users injected`, 'success')
      }
    } catch(err){ toast(err.response?.data?.detail??'Timed injection failed','error') }
    finally{ setTimedLoading(false) }
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Standard Bulk */}
        <DevCard icon={UserPlus} iconBg="bg-emerald-900/40 border border-emerald-700/50" iconColor="text-emerald-400" title="Mass User Injection" subtitle="Bulk-create users via SQLAlchemy Core batch inserts">
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
              <div className="sm:col-span-2"><DevInput label="Number of Users" hint="(1–100,000)" type="number" min={1} max={100_000} value={count} onChange={e=>setCount(Math.min(100_000,Math.max(1,parseInt(e.target.value,10)||1)))} /></div><div><p className="text-xs text-slate-400 font-medium mb-1.5">Auto-Form Pools</p>
                <div className="flex items-center gap-3 h-10"><Toggle checked={autoPool} onChange={setAutoPool} label="Auto-pool"/><span className="text-xs text-slate-300">{autoPool?'Yes':'No'}</span></div>
              </div>
            </div>
            {count>=10_000&&<InfoBanner text={`${count.toLocaleString()} users — large batch. Backend uses 5,000-row batches.`}/>}
            <button onClick={handleBulk} disabled={loading} className="w-full flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 rounded-xl transition">
              {loading?<><Spinner className="w-4 h-4"/>Injecting…</>:<><UserPlus className="w-4 h-4"/>Inject {count.toLocaleString()} Users</>}
            </button>
            {result&&<ResultBox>
              <div className="grid grid-cols-4 gap-3">
                <StatPill label="Users" value={result.users_created.toLocaleString('en-IN')} accent="emerald"/>
                <StatPill label="DEP Tokens" value={result.dep_tokens_created.toLocaleString('en-IN')} accent="emerald"/>
                <StatPill label="Pools Formed" value={result.pools_formed} accent={result.pools_formed>0?'blue':'slate'}/>
                <StatPill label="Elapsed" value={`${result.elapsed_ms.toLocaleString()}ms`} accent="purple"/>
              </div>
              <p className="text-xs text-slate-400 mt-2 font-mono leading-relaxed">{result.note}</p>
            </ResultBox>}
          </div>
        </DevCard>

        {/* Timed Injection */}
        <DevCard icon={CalendarDays} iconBg="bg-cyan-900/40 border border-cyan-700/50" iconColor="text-cyan-400" title="Timed Injection" subtitle="Inject with custom date/time distribution & cadence control">
          <div className="space-y-4">
            <DevInput label="Number of Users" hint="(1–100,000)" type="number" min={1} max={100_000} value={tCount} onChange={e=>setTCount(Math.min(100_000,Math.max(1,parseInt(e.target.value)||1)))}/>

            <div>
              <label className="block text-xs text-slate-400 font-medium mb-1.5">Anchor Date/Time <span className="text-slate-600">(blank = now)</span></label>
              <input type="datetime-local" value={baseDate} onChange={e=>setBaseDate(e.target.value)}
                className="w-full bg-slate-800 border border-slate-600 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-600 focus:border-transparent transition-colors"/>
            </div>

            <DevInput label="Spread Across N Days" hint="(0 = all at anchor)" type="number" min={0} max={365} value={spreadDays} onChange={e=>setSpreadDays(Math.max(0,parseInt(e.target.value)||0))}/>

            <div className="grid grid-cols-2 gap-4">
              <div><p className="text-xs text-slate-400 font-medium mb-1.5">Randomize Dates</p>
                <div className="flex items-center gap-3 h-10"><Toggle checked={randomize} onChange={setRandomize} label="Randomize"/><span className="text-xs text-slate-300">{randomize?'Random scatter':'Linear spread'}</span></div>
              </div>
              <div><p className="text-xs text-slate-400 font-medium mb-1.5">Daily Cadence Mode</p>
                <div className="flex items-center gap-3 h-10"><Toggle checked={useDailyCadence} onChange={setUseDailyCadence} label="Daily cadence"/><span className="text-xs text-slate-300">{useDailyCadence?'Active':'Off'}</span></div>
              </div>
            </div>

            {useDailyCadence&&<DevInput label="Users Per Day" hint="(injected per day for spread_days)" type="number" min={1} value={dailyCount} onChange={e=>setDailyCount(Math.max(1,parseInt(e.target.value)||1))}/>}

            <div className="flex items-center gap-3"><Toggle checked={timedAutoPool} onChange={setTimedAutoPool} label="Auto-pool"/><span className="text-xs text-slate-300">Auto-form pools after injection</span></div>

            <button onClick={handleTimed} disabled={timedLoading} className="w-full flex items-center justify-center gap-2 bg-cyan-700 hover:bg-cyan-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 rounded-xl transition">
              {timedLoading?<><Spinner className="w-4 h-4"/>Injecting…</>:<><Shuffle className="w-4 h-4"/>Inject {tCount.toLocaleString()} Timed Users</>}
            </button>

            {timedResult&&<ResultBox>
              <div className="grid grid-cols-2 gap-3">
                <StatPill label="Users Created" value={timedResult.users_created.toLocaleString('en-IN')} accent="cyan"/>
                <StatPill label="Pools Formed"
                  value={timedResult.pool_formation==='background' ? '…' : (timedResult.pools_formed??0)}
                  accent={timedResult.pools_formed>0?'blue':'slate'}/>
                <StatPill label="Date From" value={timedResult.date_from?new Date(timedResult.date_from).toLocaleDateString('en-IN'):'—'} accent="slate"/>
                <StatPill label="Date To"   value={timedResult.date_to  ?new Date(timedResult.date_to  ).toLocaleDateString('en-IN'):'—'} accent="slate"/>
              </div>
              <p className="text-xs text-slate-400 mt-2 font-mono leading-relaxed">{timedResult.note}</p>
            </ResultBox>}

            {/* Background pool-formation status banner */}
            {bgStatus && (
              <div className={`rounded-xl border px-4 py-3 text-xs font-mono ${
                bgStatus.status === 'running' ? 'bg-amber-950/40 border-amber-700/50 text-amber-300' :
                bgStatus.status === 'done'    ? 'bg-emerald-950/40 border-emerald-700/50 text-emerald-300' :
                                                'bg-red-950/40 border-red-700/50 text-red-300'
              }`}>
                <div className="flex items-center gap-2">
                  {bgStatus.status === 'running' && <Spinner className="w-3 h-3"/>}
                  {bgStatus.status === 'done'    && <CheckCircle2 className="w-3.5 h-3.5"/>}
                  {bgStatus.status === 'error'   && <XCircle className="w-3.5 h-3.5"/>}
                  <span className="font-bold uppercase tracking-wider">{bgStatus.status}</span>
                  {bgStatus.status === 'running' && <span className="text-amber-400 ml-1">— Pool formation in progress…</span>}
                </div>
                {bgStatus.status === 'done' && (
                  <div className="mt-1.5 flex gap-4">
                    <span>Pools formed: <span className="font-bold text-white">{bgStatus.pools_formed}</span></span>
                    <span>Waitlist remaining: <span className="font-bold text-white">{(bgStatus.waitlist_remaining??'—').toLocaleString?.() ?? bgStatus.waitlist_remaining}</span></span>
                  </div>
                )}
                {bgStatus.status === 'error' && <p className="mt-1 text-red-400">{bgStatus.error}</p>}
              </div>
            )}
          </div>
        </DevCard>
      </div>
    </div>
  )
}


// ─── (LiveStatsTab, LevelMapTab, WinnersTab, ProjectionsTab removed — these
//      tabs were consolidated into StressTestTab's 6-sub-tab report panel) ───



// ─────────────────────────────────────────────────────────────────────────────
// TAB 7 — CONTROLS (payment scenarios + auto-paid + late %)
// ─────────────────────────────────────────────────────────────────────────────

function ControlsTab({ toast }) {
  const [masterPaidLoading, setMasterPaidLoading] = useState(false)
  const [masterPaidResult, setMasterPaidResult] = useState(null)
  // Payment scenario
  // NOTE: lateFeeInr was removed (Phase 2-B) — it conflicted with the stress-test
  // engine's late_fee_pct parameter.  Pre-Test Setup applies a fixed ₹50 default fee
  // when applyLateFee=true.  The stress-test engine controls simulation-level late fees
  // independently via its own "Late Fee %" and "Late Users Ratio %" controls.
  const [paidPct, setPaidPct] = useState(100)
  const [applyLateFee, setApplyLateFee] = useState(false)
  const [elimPct, setElimPct] = useState(0)
  const [scenarioLoading, setScenarioLoading] = useState(false)
  const [scenarioResult, setScenarioResult] = useState(null)

  const handleMasterPaid = async () => {
    setMasterPaidLoading(true); setMasterPaidResult(null)
    try {
      const res = await devMarkAllPaid()
      setMasterPaidResult(res.data)
      toast(`${res.data.marked_paid} member(s) marked Paid`, 'success')
    } catch(err){ toast(err.response?.data?.detail??'Failed','error') }
    finally{ setMasterPaidLoading(false) }
  }

  const handleScenario = async () => {
    setScenarioLoading(true); setScenarioResult(null)
    try {
      // late_fee_inr uses fixed ₹50 default when applyLateFee=true
      // (the field is kept in the API for backward-compat but hidden from this UI)
      const res = await devSetPaymentScenario({
        paid_pct:             paidPct,
        apply_late_fee:       applyLateFee,
        late_fee_inr:         applyLateFee ? 50 : 0,
        eliminate_unpaid_pct: elimPct,
      })
      setScenarioResult(res.data)
      toast(res.data.message, paidPct<50?'warning':'success')
    } catch(err){ toast(err.response?.data?.detail??'Failed','error') }
    finally{ setScenarioLoading(false) }
  }

  return (
    <div className="space-y-6">
      {/* Scope clarification banner */}
      <div className="flex gap-2.5 p-3.5 rounded-xl bg-blue-950/30 border border-blue-800/40 text-xs text-blue-300 leading-relaxed">
        <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
        <span><strong>Pre-Test Setup</strong> writes to the live DB before the stress-test runs.
        &nbsp;The Stress-Test engine's own <em>Late Fee %</em> and <em>Late Users Ratio %</em> controls
        affect the in-memory simulation engine independently — they don't touch the DB.</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Master Paid Toggle */}
        <DevCard icon={ToggleRight} iconBg="bg-emerald-900/40 border border-emerald-700/50" iconColor="text-emerald-400" title="Master Paid Toggle" subtitle="Mark ALL active pool members as Paid with one click">
          <div className="space-y-4">
            <div className="bg-emerald-950/30 border border-emerald-800/40 rounded-xl p-4">
              <p className="text-xs text-emerald-300 leading-relaxed">
                Instantly clears all weekly Unpaid flags across every active pool member.
                Use this before running Force Draw to avoid payment validation failures.
              </p>
            </div>
            <button onClick={handleMasterPaid} disabled={masterPaidLoading}
              className="w-full flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 rounded-xl transition">
              {masterPaidLoading?<><Spinner className="w-4 h-4"/>Marking…</>:<><ToggleRight className="w-4 h-4"/>Mark All Members Paid</>}
            </button>
            {masterPaidResult&&<ResultBox>
              <div className="grid grid-cols-3 gap-3">
                <StatPill label="Marked Paid"  value={masterPaidResult.marked_paid}  accent="emerald"/>
                <StatPill label="Total Active" value={masterPaidResult.total_active} accent="blue"/>
                <StatPill label="Status"       value="All Paid"                       accent="emerald"/>
              </div>
            </ResultBox>}
          </div>
        </DevCard>

        {/* Payment Scenario */}
        <DevCard icon={Settings} iconBg="bg-blue-900/40 border border-blue-700/50" iconColor="text-blue-400" title="Payment Scenario" subtitle="Set DB payment state (paid %, late fees, elimination) before running">
          <div className="space-y-4">
            {/* Paid % slider */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs text-slate-400 font-medium">Paid Members %</label>
                <div className="bg-slate-800 border border-slate-600 rounded-lg px-2.5 py-1 text-sm font-black text-emerald-300">{paidPct}%</div>
              </div>
              <input type="range" min={0} max={100} step={5} value={paidPct} onChange={e=>setPaidPct(parseInt(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer accent-emerald-500"
                style={{background:`linear-gradient(to right,#10b981 ${paidPct}%,#334155 ${paidPct}%)`}}
              />
              <div className="flex justify-between text-[10px] text-slate-600 mt-1 select-none">
                <span>0% (All Unpaid)</span><span>50%</span><span>100% (All Paid)</span>
              </div>
            </div>

            {/* Late fee toggle — no amount input (uses fixed ₹50 default) */}
            <div className={`rounded-xl border p-3.5 cursor-pointer select-none transition-colors ${applyLateFee?'bg-amber-950/30 border-amber-700/60':'bg-slate-800/50 border-slate-700/50'}`} onClick={()=>setApplyLateFee(v=>!v)}>
              <div className="flex items-center justify-between">
                <div>
                  <p className={`text-xs font-semibold ${applyLateFee?'text-amber-300':'text-slate-300'}`}>Apply Late Fee to Unpaid</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">Creates ₹50/member late-fee tokens for all unpaid members</p>
                </div>
                <Toggle checked={applyLateFee} onChange={()=>{}} label="Apply late fee"/>
              </div>
            </div>

            {/* Elimination % — granular 0.05–100% range (Phase 2-B) */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs text-slate-400 font-medium">
                  Eliminate Unpaid %&nbsp;<span className="text-slate-600">(of unpaid members)</span>
                </label>
                <div className={`border rounded-lg px-2.5 py-1 text-sm font-black tabular-nums ${
                  elimPct>0?'bg-red-950 border-red-800 text-red-300':'bg-slate-800 border-slate-600 text-slate-500'
                }`}>{elimPct.toFixed(2)}%</div>
              </div>
              {/* Fine-grained 0.05% steps — allows testing "eliminate 1 in 2000 members" */}
              <input type="range" min={0} max={100} step={0.05} value={elimPct}
                onChange={e=>setElimPct(parseFloat(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer"
                style={{background:elimPct>0
                  ?`linear-gradient(to right,#ef4444 ${elimPct}%,#334155 ${elimPct}%)`
                  :`linear-gradient(to right,#334155 0%,#334155 100%)`}}
              />
              <div className="flex justify-between text-[10px] text-slate-600 mt-1 select-none">
                <span>0.05%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span>
              </div>
              {elimPct>0&&<InfoBanner text={`${elimPct.toFixed(2)}% of unpaid members will be permanently eliminated. This cannot be undone without a DB reset.`} accent="red"/>}
            </div>

            <button onClick={handleScenario} disabled={scenarioLoading}
              className="w-full flex items-center justify-center gap-2 bg-blue-700 hover:bg-blue-600 disabled:bg-slate-700 disabled:text-slate-500 text-white font-bold py-3 rounded-xl transition">
              {scenarioLoading?<><Spinner className="w-4 h-4"/>Applying…</>:<><Settings className="w-4 h-4"/>Apply Scenario</>}
            </button>

            {scenarioResult&&<ResultBox>
              <div className="grid grid-cols-3 gap-3">
                <StatPill label="Marked Paid"   value={scenarioResult.marked_paid}     accent="emerald"/>
                <StatPill label="Marked Unpaid" value={scenarioResult.marked_unpaid}   accent="amber"/>
                <StatPill label="Eliminated"    value={scenarioResult.eliminated}      accent={scenarioResult.eliminated>0?'red':'slate'}/>
              </div>
              <p className="text-xs text-slate-400 mt-2">{scenarioResult.message}</p>
            </ResultBox>}
          </div>
        </DevCard>
      </div>

      <InfoBanner text="Payment scenarios affect PRODUCTION data. All changes are immediately applied to the live database. Use only in dev/staging environments." accent="red"/>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// TAB 8 — DANGER ZONE
// ─────────────────────────────────────────────────────────────────────────────

function DangerTab({ toast }) {
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleNuke = async () => {
    setLoading(true); setResult(null)
    try {
      const res = await resetDataDev()
      setResult(res.data)
      setConfirm('')
      toast('Database nuked — all data cleared', 'warning')
    } catch(err){ toast(err.response?.data?.detail??'Failed','error') }
    finally{ setLoading(false) }
  }

  return (
    <div className="max-w-2xl">
      <div className="bg-red-950/20 border-2 border-red-800/50 rounded-2xl overflow-hidden shadow-2xl shadow-red-950/20">
        <div className="flex items-center gap-3 px-6 py-4 bg-red-950/60 border-b-2 border-red-800/50">
          <div className="bg-red-800/50 border border-red-600/50 p-2.5 rounded-xl"><Skull className="w-4 h-4 text-red-300"/></div>
          <div className="flex-1">
            <p className="font-bold text-red-100 text-sm tracking-wider">DANGER ZONE</p>
            <p className="text-xs text-red-400/70 mt-0.5">Irreversible operations · Admin accounts are never affected</p>
          </div>
          <span className="text-[10px] font-mono font-bold bg-red-900/60 border border-red-700 text-red-300 px-2.5 py-1 rounded-lg tracking-widest">DESTRUCTIVE</span>
        </div>
        <div className="p-6 space-y-5">
          <div className="bg-red-900/15 border border-red-800/30 rounded-xl p-4 space-y-2">
            <p className="text-xs font-bold text-red-200 flex items-center gap-2"><AlertTriangle className="w-3.5 h-3.5 text-red-400"/>What "Nuke Database" does</p>
            {/* SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
                Reset now wipes ALL transactional tables for a true clean slate
                (required before a clean simulation run). */}
            <ul className="text-xs text-red-300/70 space-y-1 pl-5 list-disc leading-relaxed">
              <li>Deletes <strong className="text-red-200">all rows</strong> from <code className="bg-red-900/50 px-1 rounded font-mono">users</code>, <code className="bg-red-900/50 px-1 rounded font-mono">pools</code>, <code className="bg-red-900/50 px-1 rounded font-mono">tokens</code>, <code className="bg-red-900/50 px-1 rounded font-mono">draw_history</code>, <code className="bg-red-900/50 px-1 rounded font-mono">weekly_draw_state</code>, <code className="bg-red-900/50 px-1 rounded font-mono">system_locks</code>, SDE sessions and elimination events</li>
              <li>Resets PostgreSQL auto-increment sequences — next user gets <code className="bg-red-900/50 px-1 rounded font-mono">id = 1</code></li>
              <li><strong className="text-red-100">Admin accounts and system settings are NOT deleted</strong></li>
              <li className="text-red-400">This action <strong>cannot be undone</strong></li>
            </ul>
          </div>
          <div className="flex flex-col sm:flex-row items-start sm:items-end gap-4">
            <div className="flex-1 w-full">
              <label className="block text-xs font-medium mb-1.5">
                <span className="text-slate-400">Type </span>
                <code className="text-red-300 font-mono font-bold bg-red-950 px-1.5 py-0.5 rounded border border-red-800">DELETE</code>
                <span className="text-slate-400"> to unlock</span>
              </label>
              <input type="text" value={confirm} onChange={e=>setConfirm(e.target.value)} placeholder="DELETE" autoComplete="off" spellCheck={false}
                className={`w-full bg-slate-900 border rounded-xl px-4 py-2.5 text-sm font-mono focus:outline-none focus:ring-2 focus:border-transparent transition-all duration-200 ${
                  confirm==='DELETE'?'border-red-600 text-red-300 focus:ring-red-700 shadow-lg shadow-red-950/40':'border-slate-700 text-slate-300 focus:ring-slate-600'
                }`}
              />
            </div>
            <button onClick={handleNuke} disabled={confirm!=='DELETE'||loading}
              className={`flex-shrink-0 flex items-center gap-2.5 font-bold py-3 px-7 rounded-xl transition-all duration-200 ${
                confirm==='DELETE'&&!loading?'bg-red-700 hover:bg-red-600 text-white shadow-xl shadow-red-900/40 animate-pulse':'bg-slate-800 text-slate-600 cursor-not-allowed border border-slate-700'
              }`}>
              {loading?<><Spinner className="w-4 h-4 text-white"/>Nuking…</>:<><Skull className="w-4 h-4"/>NUKE DATABASE</>}
            </button>
          </div>
          {result&&<ResultBox>
            <div className="grid grid-cols-3 gap-3">
              <StatPill label="Users Deleted"  value={result.users_deleted.toLocaleString('en-IN')}  accent="red"/>
              <StatPill label="Tokens Deleted" value={result.tokens_deleted.toLocaleString('en-IN')} accent="red"/>
              <StatPill label="Pools Deleted"  value={result.pools_deleted.toLocaleString('en-IN')}  accent="red"/>
            </div>
            {result.sequences_reset
              ?<p className="text-emerald-400 text-xs flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5"/>All auto-increment IDs reset to 1.</p>
              :<p className="text-amber-400 text-xs flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5"/>Sequence reset skipped (non-PostgreSQL).</p>
            }
          </ResultBox>}
        </div>
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// TAB NAV
// ─────────────────────────────────────────────────────────────────────────────

const TABS = [
  { id:0, icon:FlaskConical, label:'Stress Test',  short:'Stress'  },
  { id:1, icon:Zap,          label:'Draw Control', short:'Draw'    },
  { id:2, icon:UserPlus,     label:'Injection',    short:'Inject'  },
  { id:3, icon:Skull,        label:'Danger Zone',  short:'Danger', danger:true },
]

function TabNav({ active, setActive }) {
  return (
    <div className="flex gap-0.5 overflow-x-auto pb-1 scrollbar-hide">
      {TABS.map(t=>(
        <button
          key={t.id}
          onClick={()=>setActive(t.id)}
          className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-xs font-semibold transition-all whitespace-nowrap ${
            active===t.id
              ? t.danger
                ? 'bg-red-800/80 text-red-100 shadow-md'
                : 'bg-violet-700 text-white shadow-md'
              : t.danger
                ? 'text-red-400/70 hover:text-red-300 hover:bg-red-900/30 border border-red-900/40'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
          }`}
        >
          <t.icon className="w-3.5 h-3.5 flex-shrink-0"/>
          <span className="hidden sm:inline">{t.label}</span>
          <span className="inline sm:hidden">{t.short}</span>
        </button>
      ))}
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// MAIN DevTools export
// ─────────────────────────────────────────────────────────────────────────────

export default function DevTools() {
  const toast = useToast()
  const [tab, setTab] = useState(0)
  const [serverDevError, setServerDevError] = useState(null)

  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // ── Global System Debugger state ─────────────────────────────────────────
  const [debuggerOn,     setDebuggerOn]     = useState(false)
  const [debugLogs,      setDebugLogs]      = useState([])
  const [debugStatus,    setDebugStatus]    = useState(null)
  const [showDebugPanel, setShowDebugPanel] = useState(false)

  useEffect(() => {
    const poll = () =>
      getDebuggerStatus()
        .then(r => { setDebugStatus(r.data); setDebuggerOn(r.data.enabled) })
        .catch(() => {})
    poll()
    const id = setInterval(poll, 10_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!debuggerOn) return
    const poll = () =>
      getDebuggerLogs({ limit: 50 })
        .then(r => setDebugLogs(r.data.logs ?? []))
        .catch(() => {})
    poll()
    const id = setInterval(poll, 5_000)
    return () => clearInterval(id)
  }, [debuggerOn])

  const handleDebuggerToggle = async (on) => {
    try {
      await toggleDebugger(on)
      setDebuggerOn(on)
      if (!on) setDebugLogs([])
      toast(on ? 'System Debugger ON' : 'System Debugger OFF', on ? 'success' : 'info')
    } catch {
      toast('Debugger toggle failed — check server logs', 'error')
    }
  }

  return (
    <div className="min-h-full bg-slate-950">

      {/* ── Warning Header ──────────────────────────────────────────────────── */}
      <div className="bg-gradient-to-r from-red-950 via-slate-900 to-slate-950 border-b-2 border-red-800/50 px-8 py-5 sticky top-0 z-10">
        <div className="flex items-center gap-4 max-w-7xl mx-auto">
          <div className="bg-red-800/30 border border-red-700/50 p-3 rounded-xl flex-shrink-0">
            <Terminal className="w-5 h-5 text-red-400"/>
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-base font-bold text-red-100 leading-none tracking-wide">Developer Tools — God Mode</h1>
            <p className="text-xs text-red-400/70 mt-0.5">Direct database mutations · Irreversible · Staging only</p>
          </div>
          <div className="hidden sm:flex items-center gap-2 bg-red-950/80 border border-red-800 rounded-lg px-3 py-1.5 flex-shrink-0">
            <span className="w-1.5 h-1.5 bg-red-400 rounded-full animate-pulse block"/>
            <code className="text-xs font-mono font-bold text-red-300 tracking-wider">ENABLE_DEV_MODE=true</code>
          </div>
          {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
          {/* Debugger Mode toggle badge */}
          <button
            onClick={() => setShowDebugPanel(v => !v)}
            className={`hidden sm:flex items-center gap-2 border rounded-lg px-3 py-1.5 flex-shrink-0 transition-colors ${
              debuggerOn
                ? 'bg-emerald-950/80 border-emerald-700 text-emerald-300'
                : 'bg-slate-900/60 border-slate-700 text-slate-400 hover:border-slate-500'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full block ${debuggerOn ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'}`}/>
            <code className="text-xs font-mono font-bold tracking-wider">DEBUGGER</code>
            <Toggle checked={debuggerOn} onChange={handleDebuggerToggle} label="System Debugger"/>
          </button>
        </div>
      </div>

      <div className="p-8 max-w-7xl mx-auto space-y-4">

        {/* 403 banner */}
        {serverDevError&&(
          <div className="bg-red-950 border-2 border-red-600/80 rounded-2xl p-6 flex items-start gap-4">
            <XCircle className="w-6 h-6 text-red-400 flex-shrink-0 mt-0.5"/>
            <div className="flex-1">
              <h2 className="text-red-100 font-bold">ENABLE_DEV_MODE is false on the server</h2>
              <p className="text-red-300 text-sm mt-2">Set <code className="bg-red-900/60 px-1.5 py-0.5 rounded font-mono">ENABLE_DEV_MODE=true</code> in Render env vars and redeploy.</p>
              <p className="text-red-500 text-xs font-mono mt-3 bg-red-950/60 rounded px-3 py-2 border border-red-900">{serverDevError}</p>
              <button onClick={()=>setServerDevError(null)} className="mt-3 text-xs text-red-400 hover:text-red-200 underline transition">Dismiss</button>
            </div>
          </div>
        )}

        {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
        {/* ── Global System Debugger log panel ─────────────────────────────── */}
        {showDebugPanel&&(
          <div className="bg-slate-900 border border-emerald-800/40 rounded-2xl overflow-hidden">
            <div className="flex items-center gap-3 px-5 py-3 bg-emerald-950/40 border-b border-emerald-800/30">
              <Activity className="w-4 h-4 text-emerald-400"/>
              <span className="text-sm font-bold text-emerald-300">System Debugger</span>
              {debugStatus&&(
                <span className="text-xs text-slate-400 ml-1">
                  run_id: <code className="text-emerald-300">{debugStatus.run_id||'—'}</code>
                  {' '}·{' '}week: <code className="text-emerald-300">{debugStatus.week||0}</code>
                  {' '}·{' '}<code className="text-emerald-300">{debugStatus.log_count??0}</code> logs
                </span>
              )}
              <div className="ml-auto flex items-center gap-3">
                <Toggle checked={debuggerOn} onChange={handleDebuggerToggle} label="Debugger on/off"/>
                <span className={`text-xs font-bold ${debuggerOn?'text-emerald-400':'text-slate-500'}`}>
                  {debuggerOn?'ON':'OFF'}
                </span>
                {debugLogs.length>0&&(
                  <button
                    onClick={()=>clearDebuggerLogs().then(()=>setDebugLogs([])).catch(()=>{})}
                    className="text-xs text-red-400 hover:text-red-300 underline transition"
                  >Clear logs</button>
                )}
              </div>
            </div>
            {debugLogs.length===0?(
              <div className="px-5 py-6 text-center text-slate-500 text-sm">
                {debuggerOn?'Waiting for log entries…':'Enable debugger and run a simulation to see logs.'}
              </div>
            ):(
              <div className="overflow-x-auto max-h-72">
                <table className="w-full text-[11px] font-mono">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-500 uppercase text-[10px]">
                      <th className="px-3 py-2 text-left">Phase</th>
                      <th className="px-3 py-2 text-left">Event</th>
                      <th className="px-3 py-2 text-left">Week</th>
                      <th className="px-3 py-2 text-right">ms</th>
                      <th className="px-3 py-2 text-left">Data</th>
                      <th className="px-3 py-2 text-left">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {debugLogs.map(l=>(
                      <tr key={l.id} className="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
                        <td className="px-3 py-1.5 text-cyan-400">{l.phase}</td>
                        <td className="px-3 py-1.5 text-slate-300">{l.event}</td>
                        <td className="px-3 py-1.5 text-slate-400">{l.week_num??'—'}</td>
                        <td className="px-3 py-1.5 text-right text-violet-300">{l.duration_ms!=null?l.duration_ms.toFixed(1):'—'}</td>
                        <td className="px-3 py-1.5 text-slate-400 max-w-[200px] truncate">{l.data_json??'—'}</td>
                        <td className="px-3 py-1.5 text-red-400 max-w-[150px] truncate">{l.error??''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Tab navigation */}
        <TabNav active={tab} setActive={setTab}/>

        {/* Tab content */}
        <div>
          {tab===0&&<StressTestTab  toast={toast}/>}
          {tab===1&&<DrawControlTab toast={toast}/>}
          {tab===2&&<InjectionTab   toast={toast}/>}
          {tab===3&&<DangerTab      toast={toast}/>}
        </div>

        <div className="h-8"/>
      </div>
    </div>
  )
}
