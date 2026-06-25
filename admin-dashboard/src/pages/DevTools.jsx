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
  // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Pruned Stress-Test-only icons (FlaskConical, TrendingUp, GitMerge, ShieldAlert,
  // DollarSign, Layers, Target, Cpu, TableProperties) + the entire recharts import
  // (all chart helpers lived in the removed StressTestTab). Kept BarChart3, Trophy,
  // Download — still referenced by the surviving tabs.
  Terminal, Zap, Clock, UserPlus, Skull,
  AlertTriangle, CheckCircle2, XCircle, Play, Info, Users,
  IndianRupee, BarChart3,
  Database, RefreshCw, Trophy,
  Settings, CalendarDays, Activity, ToggleLeft, ToggleRight,
  Shuffle, ChevronRight, Download,
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  ScrollText, Search, Trash2, Filter, FileJson, Radio,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import {
  forceDrawDev, simulateCycleDev, simulateUsersDev,
  resetDataDev,
  // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Removed startRealSimulation / getRealSimStatus / getRealSimResult imports —
  // they were consumed only by the now-deleted StressTestTab. The wrappers remain
  // exported from client.js and the backend /dev/stress-test* routes stay dormant.
  devInjectTimed, devMarkAllPaid,
  devSetPaymentScenario, getInjectionStatus,
  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  getDebuggerStatus, toggleDebugger, getDebuggerLogs, clearDebuggerLogs,
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  getForensicStatus, toggleForensic, getForensicEvents, getForensicSummary,
  exportForensicEvents, clearForensicEvents,
  // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
  manualSimStart, manualSimState, manualSimJumpNext, manualSimJumpTo,
  manualSimStop, manualSimLink, manualSimAction,
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

// ─────────────────────────────────────────────────────────────────────────────
// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
// TAB 4 — FORENSIC DEBUGGER (event-level "every breath of the system" recorder)
// -----------------------------------------------------------------------------
// Surfaces the forensic_events stream the engine now emits (member join / win,
// level advance, elimination, pool create / merge / dissolve, L4 SDE flag,
// SDE meta-pool, Case-E hold, posture decision, per-week heartbeat, anomalies).
// Toggle ON → the backend recorder buffers + bulk-flushes every domain event;
// toggle OFF → zero rows, zero overhead. Filter, paginate, export (CSV/JSON),
// and clear. All /dev/forensic/* calls are dev-mode gated server-side.
// ─────────────────────────────────────────────────────────────────────────────

const FX_CATEGORIES = ['', 'MEMBERSHIP', 'POOL', 'DRAW', 'SDE', 'MERGER',
  'PAYMENT', 'LEVEL', 'ELIMINATION', 'GRACE', 'REFILL', 'POSTURE', 'SYSTEM', 'ANOMALY']
const FX_SEVERITIES = ['', 'info', 'notice', 'warning', 'critical']

const fxCatColor = (c) => ({
  MEMBERSHIP: 'text-sky-300',   POOL: 'text-indigo-300', DRAW: 'text-emerald-300',
  SDE: 'text-rose-300',         MERGER: 'text-orange-300', PAYMENT: 'text-cyan-300',
  LEVEL: 'text-violet-300',     ELIMINATION: 'text-red-300', GRACE: 'text-amber-300',
  REFILL: 'text-teal-300',      POSTURE: 'text-fuchsia-300', SYSTEM: 'text-slate-300',
  ANOMALY: 'text-red-400 font-bold',
}[c] || 'text-slate-300')

const fxSevPill = (s) => ({
  info:     'bg-slate-800 text-slate-400 border-slate-700',
  notice:   'bg-emerald-950 text-emerald-300 border-emerald-800',
  warning:  'bg-amber-950 text-amber-300 border-amber-800',
  critical: 'bg-red-950 text-red-300 border-red-800',
}[s] || 'bg-slate-800 text-slate-400 border-slate-700')

function ForensicTab({ toast }) {
  const FX_LIMIT = 100
  const [status,  setStatus]  = useState(null)
  const [on,      setOn]      = useState(false)
  const [runId,   setRunId]   = useState('')
  const [filters, setFilters] = useState({
    category: '', severity: '', event_type: '', week_id: '',
    entity_id: '', search: '', order: 'desc', run_id: '',
  })
  const [events,  setEvents]  = useState([])
  const [total,   setTotal]   = useState(0)
  const [offset,  setOffset]  = useState(0)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)

  // Normalise the filter object into query params (drop empties; coerce ints).
  const queryParams = useCallback((extra = {}) => {
    const p = {}
    if (filters.category)   p.category   = filters.category
    if (filters.severity)   p.severity   = filters.severity
    if (filters.event_type) p.event_type = filters.event_type
    if (filters.search)     p.search     = filters.search
    if (filters.run_id)     p.run_id     = filters.run_id
    if (filters.week_id  !== '') p.week_id   = parseInt(filters.week_id, 10)
    if (filters.entity_id!== '') p.entity_id = parseInt(filters.entity_id, 10)
    return { ...p, ...extra }
  }, [filters])

  const fetchStatus = useCallback(() => {
    getForensicStatus()
      .then(r => { setStatus(r.data); setOn(!!r.data.enabled) })
      .catch(() => {})
  }, [])

  const fetchEvents = useCallback((off = offset) => {
    setLoading(true)
    getForensicEvents(queryParams({ order: filters.order, limit: FX_LIMIT, offset: off }))
      .then(r => { setEvents(r.data.events ?? []); setTotal(r.data.total ?? 0); setOffset(off) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [queryParams, filters.order, offset])

  const fetchSummary = useCallback(() => {
    getForensicSummary(filters.run_id ? { run_id: filters.run_id } : {})
      .then(r => setSummary(r.data))
      .catch(() => {})
  }, [filters.run_id])

  // Initial + status polling.
  useEffect(() => { fetchStatus() }, [fetchStatus])
  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(() => {
      fetchStatus()
      if (on) { fetchEvents(0); fetchSummary() }
    }, 6000)
    return () => clearInterval(id)
  }, [autoRefresh, on, fetchStatus, fetchEvents, fetchSummary])

  // First data load.
  useEffect(() => { fetchEvents(0); fetchSummary() /* eslint-disable-next-line */ }, [])

  const handleToggle = async (next) => {
    try {
      await toggleForensic(next, next ? (runId || undefined) : undefined)
      setOn(next)
      toast(next ? 'Forensic Debugger ON — recording every event' : 'Forensic Debugger OFF', next ? 'success' : 'info')
      setTimeout(() => { fetchStatus(); fetchEvents(0); fetchSummary() }, 300)
    } catch {
      toast('Forensic toggle failed — check ENABLE_DEV_MODE / server logs', 'error')
    }
  }

  const applyFilters = () => { fetchEvents(0); fetchSummary() }

  const resetFilters = () => {
    setFilters({ category: '', severity: '', event_type: '', week_id: '',
      entity_id: '', search: '', order: 'desc', run_id: '' })
    setTimeout(() => { fetchEvents(0); fetchSummary() }, 0)
  }

  const doExport = async (fmt) => {
    try {
      const res = await exportForensicEvents(fmt, queryParams())
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `forensic_events.${fmt}`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast(`Exported forensic events (${fmt.toUpperCase()})`, 'success')
    } catch {
      toast('Export failed', 'error')
    }
  }

  const doClear = async () => {
    const scope = filters.run_id ? `run '${filters.run_id}'` : 'the ENTIRE table'
    if (!window.confirm(`Delete forensic events for ${scope}? This cannot be undone.`)) return
    try {
      const r = await clearForensicEvents(filters.run_id || undefined)
      toast(`Cleared ${r.data.deleted} event(s)`, 'success')
      fetchEvents(0); fetchSummary(); fetchStatus()
    } catch {
      toast('Clear failed', 'error')
    }
  }

  const setF = (k, v) => setFilters(f => ({ ...f, [k]: v }))

  const pageStart = total === 0 ? 0 : offset + 1
  const pageEnd   = Math.min(offset + FX_LIMIT, total)

  return (
    <div className="space-y-4">
      {/* ── Control header ─────────────────────────────────────────────────── */}
      <DevCard
        icon={ScrollText} iconBg="bg-emerald-900/40" iconColor="text-emerald-300"
        title="Forensic Debugger — Event-Level Recorder"
        subtitle="Records every domain event the engine emits — 'every breath of the system'"
      >
        <div className="space-y-4">
          <InfoBanner accent={on ? 'green' : 'blue'} text={
            on
              ? 'RECORDING. Every member join/win, level advance, elimination, pool create/merge/dissolve, L4 SDE flag, SDE meta-pool, Case-E hold, posture decision, per-week heartbeat and anomaly is being captured into forensic_events. Buffered events flush per Chronos tick + at week end via an independent session (the money/draw path is never coupled to a forensic write).'
              : 'OFF — zero rows, zero overhead. Enable, then run a stress test (or live cycle) to capture the full event timeline. Disabling flushes any pending buffer first.'
          }/>

          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[180px]">
              <DevInput
                label="Capture run_id" hint="(optional tag)"
                value={runId} onChange={e => setRunId(e.target.value)}
                placeholder="e.g. reprocsv / live" disabled={on}
              />
            </div>
            <button
              onClick={() => handleToggle(!on)}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all ${
                on ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-emerald-700 hover:bg-emerald-600 text-white'
              }`}
            >
              {on ? <ToggleRight className="w-4 h-4"/> : <ToggleLeft className="w-4 h-4"/>}
              {on ? 'Stop Recording' : 'Start Recording'}
            </button>
            <button
              onClick={() => setAutoRefresh(v => !v)}
              className={`flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-xs font-semibold border transition-colors ${
                autoRefresh ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300' : 'bg-slate-800 border-slate-700 text-slate-400'
              }`}
            >
              <Radio className={`w-3.5 h-3.5 ${autoRefresh ? 'animate-pulse' : ''}`}/>
              {autoRefresh ? 'Live' : 'Paused'}
            </button>
          </div>

          {/* Status pills */}
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2.5">
            <StatPill label="State"    value={on ? 'ON' : 'OFF'} accent={on ? 'emerald' : 'slate'}/>
            <StatPill label="Run"      value={status?.run_id || '—'} accent="cyan"/>
            <StatPill label="Week"     value={status?.week ?? '—'} accent="blue"/>
            <StatPill label="Tick"     value={status?.tick || '—'} accent="purple"/>
            <StatPill label="Buffered" value={NUM(status?.buffered)} accent="amber"/>
            <StatPill label="Total"    value={NUM(status?.event_count)} accent="slate"/>
          </div>
        </div>
      </DevCard>

      {/* ── Summary breakdown ──────────────────────────────────────────────── */}
      {summary && (summary.total > 0) && (
        <DevCard
          icon={BarChart3} iconBg="bg-cyan-900/40" iconColor="text-cyan-300"
          title="Event Summary" subtitle={`${NUM(summary.total)} events${filters.run_id ? ` · run '${filters.run_id}'` : ''}`}
        >
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              <StatPill label="Total Events" value={NUM(summary.total)} accent="slate"/>
              <StatPill label="Alerts (warn+crit)" value={NUM(summary.alert_count)} accent={summary.alert_count > 0 ? 'amber' : 'slate'}/>
              <StatPill label="Anomalies" value={NUM(summary.anomaly_count)} accent={summary.anomaly_count > 0 ? 'red' : 'emerald'}/>
              <StatPill label="Categories" value={NUM(summary.by_category?.length)} accent="cyan"/>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(summary.by_category ?? []).map(c => (
                <button
                  key={c.category}
                  onClick={() => { setF('category', c.category === filters.category ? '' : c.category); setTimeout(applyFilters, 0) }}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[10px] font-semibold transition-colors ${
                    filters.category === c.category ? 'border-emerald-600 bg-emerald-950/40' : 'border-slate-700 bg-slate-800/40 hover:border-slate-500'
                  }`}
                >
                  <span className={fxCatColor(c.category)}>{c.category}</span>
                  <span className="text-slate-500 font-black">{NUM(c.count)}</span>
                </button>
              ))}
            </div>
          </div>
        </DevCard>
      )}

      {/* ── Filters + actions ──────────────────────────────────────────────── */}
      <DevCard
        icon={Filter} iconBg="bg-violet-900/40" iconColor="text-violet-300"
        title="Event Timeline" subtitle={`${NUM(pageStart)}–${NUM(pageEnd)} of ${NUM(total)} matching events`}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <DevSelect label="Category" value={filters.category} onChange={e => setF('category', e.target.value)}>
              {FX_CATEGORIES.map(c => <option key={c} value={c}>{c || 'All categories'}</option>)}
            </DevSelect>
            <DevSelect label="Severity" value={filters.severity} onChange={e => setF('severity', e.target.value)}>
              {FX_SEVERITIES.map(s => <option key={s} value={s}>{s || 'All severities'}</option>)}
            </DevSelect>
            <DevInput label="Event type" placeholder="member_won…" value={filters.event_type} onChange={e => setF('event_type', e.target.value)}/>
            <DevSelect label="Order" value={filters.order} onChange={e => setF('order', e.target.value)}>
              <option value="desc">Newest first</option>
              <option value="asc">Chronological</option>
            </DevSelect>
            <DevInput label="Week" type="number" placeholder="wk #" value={filters.week_id} onChange={e => setF('week_id', e.target.value)}/>
            <DevInput label="Entity ID" type="number" placeholder="user/pool id" value={filters.entity_id} onChange={e => setF('entity_id', e.target.value)}/>
            <DevInput label="Run ID" placeholder="run filter" value={filters.run_id} onChange={e => setF('run_id', e.target.value)}/>
            <DevInput label="Search message" placeholder="substring…" value={filters.search} onChange={e => setF('search', e.target.value)}/>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button onClick={applyFilters} className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-violet-700 hover:bg-violet-600 text-white text-xs font-bold transition-colors">
              <Search className="w-3.5 h-3.5"/> Apply filters
            </button>
            <button onClick={resetFilters} className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition-colors">
              <RefreshCw className="w-3.5 h-3.5"/> Reset
            </button>
            <div className="ml-auto flex items-center gap-2">
              <button onClick={() => doExport('csv')} className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-emerald-300 text-xs font-semibold transition-colors">
                <Download className="w-3.5 h-3.5"/> CSV
              </button>
              <button onClick={() => doExport('json')} className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-cyan-300 text-xs font-semibold transition-colors">
                <FileJson className="w-3.5 h-3.5"/> JSON
              </button>
              <button onClick={doClear} className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-red-950/60 hover:bg-red-900/60 border border-red-800 text-red-300 text-xs font-semibold transition-colors">
                <Trash2 className="w-3.5 h-3.5"/> Clear
              </button>
            </div>
          </div>

          {/* Timeline table */}
          <div className="overflow-auto max-h-[32rem] rounded-xl border border-slate-700/60">
            <table className="w-full text-[11px] whitespace-nowrap">
              <thead className="bg-slate-800 sticky top-0 z-10">
                <tr className="text-slate-500 uppercase text-[10px]">
                  <th className="px-3 py-2.5 text-right">Seq</th>
                  <th className="px-3 py-2.5 text-left">Wk</th>
                  <th className="px-3 py-2.5 text-left">Tick</th>
                  <th className="px-3 py-2.5 text-left">Category</th>
                  <th className="px-3 py-2.5 text-left">Event</th>
                  <th className="px-3 py-2.5 text-left">Sev</th>
                  <th className="px-3 py-2.5 text-left">Entity</th>
                  <th className="px-3 py-2.5 text-right">₹</th>
                  <th className="px-3 py-2.5 text-left">Message</th>
                </tr>
              </thead>
              <tbody>
                {events.length === 0 ? (
                  <tr><td colSpan={9} className="px-3 py-8 text-center text-slate-500">
                    {loading ? 'Loading…' : on ? 'No events match — run a simulation or widen the filters.' : 'Forensic recorder is OFF — enable it and run a cycle to populate the timeline.'}
                  </td></tr>
                ) : events.map(ev => (
                  <tr key={ev.id} className="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors align-top">
                    <td className="px-3 py-1.5 text-right text-slate-600 tabular-nums">{ev.seq ?? '—'}</td>
                    <td className="px-3 py-1.5 text-slate-400 tabular-nums">{ev.week_id ?? '—'}</td>
                    <td className="px-3 py-1.5 text-slate-500 font-mono text-[10px]">{ev.tick ?? '—'}</td>
                    <td className={`px-3 py-1.5 font-bold ${fxCatColor(ev.category)}`}>{ev.category}</td>
                    <td className="px-3 py-1.5 text-slate-300 font-mono">{ev.event_type}</td>
                    <td className="px-3 py-1.5">
                      <span className={`inline-block px-1.5 py-0.5 rounded border text-[9px] font-bold ${fxSevPill(ev.severity)}`}>{ev.severity}</span>
                    </td>
                    <td className="px-3 py-1.5 text-slate-400">{ev.entity_ref || (ev.entity_id != null ? `#${ev.entity_id}` : '—')}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-emerald-400">{ev.amount_inr != null ? INR(ev.amount_inr) : ''}</td>
                    <td className="px-3 py-1.5 text-slate-300 max-w-[420px] whitespace-normal break-words">{ev.message || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-500">Showing {NUM(pageStart)}–{NUM(pageEnd)} of {NUM(total)}</span>
            <div className="flex items-center gap-2">
              <button
                disabled={offset <= 0 || loading}
                onClick={() => fetchEvents(Math.max(0, offset - FX_LIMIT))}
                className="px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 text-xs font-semibold disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700 transition-colors"
              >Prev</button>
              <button
                disabled={pageEnd >= total || loading}
                onClick={() => fetchEvents(offset + FX_LIMIT)}
                className="px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 text-xs font-semibold disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-700 transition-colors"
              >Next</button>
            </div>
          </div>
        </div>
      </DevCard>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// TAB 5 — TIME MACHINE (Manual Event-Timeline Simulator)
// SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Event-to-event time travel.  The watch shows the simulated day + date + time;
// jumping to an event activates exactly that event's real actions; every action
// runs a production service at the simulated instant (backend manual_clock).
// ─────────────────────────────────────────────────────────────────────────────

// Frontend presentation for each event's actions.  `ep` is the backend route key
// (/dev/manual-sim/action/<ep>); `fields` drive the inline inputs.  The action
// LIST itself always comes from the backend (state.available_actions) so the panel
// can never offer something the server would reject.
const MS_EVENT_ICONS = {
  CYCLE_START: Play, DUE_DATE: IndianRupee, GRACE_PERIOD_START: Shuffle,
  G_CLOSE: Skull, T_02H: Settings, T_00H: Trophy, T_05M: RefreshCw,
}
const MS_ACTIONS = {
  inject_users:          { ep:'inject',  label:'Inject users', icon:UserPlus, accent:'cyan',
    fields:[{k:'count',label:'Count',def:24,step:1},{k:'organic_ratio',label:'Organic ratio',def:0.6,step:0.1}] },
  pay_all_installments:  { ep:'pay-all', label:'Pay all installments', icon:IndianRupee, accent:'emerald' },
  set_late_pct:          { ep:'set-late', label:'Set late %', icon:AlertTriangle, accent:'amber',
    fields:[{k:'late_pct',label:'Late %',def:15,step:1}] },
  pay_remaining:         { ep:'pay-remaining', label:'Pay remaining', icon:CheckCircle2, accent:'emerald' },
  grace_settlement:      { ep:'grace-settle', label:'Run grace settlement', icon:Shuffle, accent:'purple',
    fields:[{k:'late_pct',label:'Late % (blank=use set)',step:1},{k:'elim_pct_a',label:'Eliminate % (A)',def:80,step:1},{k:'grace_pct_c',label:'Grace-pay % (C)',def:15,step:1}] },
  // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Finalize is the REAL guillotine now (mutates) — it eliminates A (non-payment)
  // + B (grace-expired) and refills vacancies from the waitlist.  No longer read-only.
  finalize_eliminations: { ep:'finalize-eliminations', label:'Run guillotine (eliminate A+B)', icon:Skull, accent:'red' },
  prepare_draw:          { ep:'prepare-draw', label:'Prepare draw (−2h)', icon:Settings, accent:'blue' },
  execute_draw:          { ep:'execute-draw', label:'Execute draw', icon:Trophy, accent:'purple' },
  run_cleanup:           { ep:'cleanup', label:'Run cleanup (+5m)', icon:RefreshCw, accent:'slate' },
}

const _btnAccent = {
  cyan:'bg-cyan-700 hover:bg-cyan-600', emerald:'bg-emerald-700 hover:bg-emerald-600',
  amber:'bg-amber-700 hover:bg-amber-600', purple:'bg-purple-700 hover:bg-purple-600',
  red:'bg-red-800 hover:bg-red-700', blue:'bg-blue-700 hover:bg-blue-600',
  slate:'bg-slate-700 hover:bg-slate-600',
}

function MsCountdown({ seconds }) {
  if (seconds == null) return null
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60
  const txt = h > 0 ? `${h}h ${String(m).padStart(2,'0')}m` : `${m}m ${String(s).padStart(2,'0')}s`
  return <span className="tabular-nums">{txt}</span>
}

// SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Human-legible summary of the most consequential action results so the operator
// reads the outcome without parsing raw JSON.  Truthful to the new production
// lifecycle: grace settlement shows the A/B/C buckets (A+B eliminated, only C
// survives); finalize shows the real guillotine count + per-reason split + seats
// refilled; inject surfaces the draw-window "held on waitlist" hold (bug #3).
function MsActionSummary({ action, result: r }) {
  if (!r || typeof r !== 'object') return null
  const INR = (v) => `₹${Number(v ?? 0).toLocaleString('en-IN')}`

  if (action === 'grace_settlement') {
    const reconcile = r.buckets_reconcile !== false
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <StatPill label="At-risk cohort"      value={NUM(r.at_risk)}              accent="rose" />
        <StatPill label="A · eliminate"       value={NUM(r.eliminate_pending_A)}  accent="red" />
        <StatPill label="C · grace-pay (live)" value={NUM(r.grace_saved_C)}        accent="emerald" />
        <StatPill label="B · grace-expires"   value={NUM(r.grace_pending_B)}       accent="amber" />
        <StatPill label="Late-fee revenue"    value={INR(r.late_fee_revenue_inr)}  accent="blue" />
        <StatPill label="Grace-fee revenue"   value={INR(r.grace_fee_revenue_inr)} accent="purple" />
        <StatPill label="A+B+C reconciles"    value={reconcile ? 'YES' : 'NO'}     accent={reconcile ? 'emerald' : 'red'} />
        <StatPill label="Survive (C only)"    value={NUM(r.grace_saved_C)}         accent="emerald" />
      </div>
    )
  }

  if (action === 'finalize_eliminations') {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <StatPill label="Eliminated"        value={NUM(r.eliminated_this_cycle)} accent="red" />
        <StatPill label="A · non-payment"   value={NUM(r.reason_non_payment)}    accent="rose" />
        <StatPill label="B · grace-expired" value={NUM(r.reason_grace_expired)}  accent="amber" />
        <StatPill label="Forfeited"         value={INR(r.total_forfeited_inr)}   accent="purple" />
        <StatPill label="Seats refilled"    value={NUM(r.seats_refilled)}        accent="emerald" />
        <StatPill label="ISO week"          value={r.iso_week ?? '—'}            accent="slate" />
      </div>
    )
  }

  if (action === 'inject_users') {
    const held = r.held_on_waitlist === true
    return (
      <div className="space-y-2.5">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          <StatPill label="Injected"     value={NUM(r.injected)}     accent="cyan" />
          <StatPill label="Pools formed" value={NUM(r.pools_formed)} accent={r.pools_formed > 0 ? 'blue' : 'slate'} />
          <StatPill label="Held on waitlist" value={held ? 'YES' : 'no'} accent={held ? 'amber' : 'slate'} />
        </div>
        {held && (
          <div className="flex items-start gap-2 rounded-xl border border-amber-700/50 bg-amber-950/40 px-3 py-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-amber-200">{r.note || 'Roster frozen at G_CLOSE — joiners held on the waitlist for the next cycle.'}</p>
          </div>
        )}
      </div>
    )
  }

  return null
}

function TimeMachineTab({ toast }) {
  const [state, setState]       = useState({ active: false })
  const [busy, setBusy]         = useState(null)        // action key currently running
  const [last, setLast]         = useState(null)        // { action, result }
  const [inputs, setInputs]     = useState({})          // action field values
  const [ttlLocal, setTtlLocal] = useState(null)        // smooth per-second TTL display
  // start-form
  const [anchor, setAnchor]     = useState('')
  const [linkOnStart, setLink]  = useState(true)
  const [ttlHours, setTtlHours] = useState(6)

  const active = state?.active === true

  const handleErr = useCallback((e, what) => {
    const sc = e?.response?.status
    const detail = e?.response?.data?.detail || e?.message || 'unknown error'
    if (sc === 403)      toast('ENABLE_DEV_MODE is false on the server', 'error')
    else if (sc === 409) toast(detail, 'info')
    else                 toast(`${what} failed: ${detail}`, 'error')
  }, [toast])

  const refresh = useCallback(async () => {
    try { const { data } = await manualSimState(); setState(data); if (data?.ttl_remaining_seconds != null) setTtlLocal(data.ttl_remaining_seconds) }
    catch (e) { if (e?.response?.status === 403) setState({ active:false, dev_mode:false }) }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Poll state every 6s while active (keeps snapshot + TTL fresh across jumps).
  useEffect(() => {
    if (!active) return
    const id = setInterval(refresh, 6_000)
    return () => clearInterval(id)
  }, [active, refresh])

  // Smooth 1s TTL countdown between polls.
  useEffect(() => {
    if (!active || ttlLocal == null) return
    const id = setInterval(() => setTtlLocal(v => (v == null ? v : Math.max(0, v - 1))), 1_000)
    return () => clearInterval(id)
  }, [active, ttlLocal])

  const setField = (k, v) => setInputs(p => ({ ...p, [k]: v }))

  const buildBody = (actionKey) => {
    const reg = MS_ACTIONS[actionKey]
    if (!reg?.fields) return undefined
    const body = {}
    for (const f of reg.fields) {
      const raw = inputs[f.k] ?? f.def
      if (raw !== '' && raw != null) body[f.k] = Number(raw)
    }
    return body
  }

  const start = async () => {
    setBusy('__start')
    try {
      const params = { link_global: linkOnStart, ttl_hours: Number(ttlHours) || 6 }
      if (anchor.trim()) params.draw_anchor = anchor.trim()
      const { data } = await manualSimStart(params)
      setState(data); setTtlLocal(data?.ttl_remaining_seconds ?? null); setLast(null)
      toast('Time Machine started', 'success')
    } catch (e) { handleErr(e, 'Start') } finally { setBusy(null) }
  }

  const stop = async () => {
    setBusy('__stop')
    try { await manualSimStop(); setState({ active:false }); setLast(null); toast('Time Machine stopped', 'info') }
    catch (e) { handleErr(e, 'Stop') } finally { setBusy(null) }
  }

  const jumpNext = async () => {
    setBusy('__next')
    try { const { data } = await manualSimJumpNext(); setState(data); setTtlLocal(data?.ttl_remaining_seconds ?? null) }
    catch (e) { handleErr(e, 'Jump next') } finally { setBusy(null) }
  }

  const jumpTo = async (event) => {
    setBusy('__to:' + event)
    try { const { data } = await manualSimJumpTo(event); setState(data); setTtlLocal(data?.ttl_remaining_seconds ?? null) }
    catch (e) { handleErr(e, 'Jump to ' + event) } finally { setBusy(null) }
  }

  const toggleLink = async (v) => {
    try { const { data } = await manualSimLink(v); setState(data) }
    catch (e) { handleErr(e, 'Link toggle') }
  }

  const runAction = async (actionKey) => {
    const reg = MS_ACTIONS[actionKey]
    if (!reg) return
    setBusy(actionKey)
    try {
      const { data } = await manualSimAction(reg.ep, buildBody(actionKey))
      setState(data.state); setTtlLocal(data.state?.ttl_remaining_seconds ?? null)
      setLast({ action: data.action, result: data.result })
      toast(`${reg.label} ✓`, 'success')
    } catch (e) { handleErr(e, reg.label) } finally { setBusy(null) }
  }

  const snap = state?.snapshot
  const curMeta = active ? (state.current_event_meta || {}) : {}
  const avail = active ? (state.available_actions || []) : []

  // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Event-driven gating + compliance/task telemetry. Every value is computed on
  // the backend from production tables — the UI only presents it; it never decides
  // gating itself and never overrides (the server re-checks and 409s if bypassed).
  const canAdvance      = active ? state.can_advance !== false : true
  const advanceReason   = state?.advance_block_reason || ''
  const requiredAction  = active ? (state.required_action || []) : []
  const requiredDone    = active ? state.required_done !== false : true
  const disabledActions = active ? (state.disabled_actions || []) : []
  // SESSION EDIT [Claude Session Jun-25 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Per-action truthful dim reason (e.g. "All members already paid — nothing due").
  const disabledReasons = active ? (state.disabled_reasons || {}) : {}
  const compliance      = active ? state.compliance : null
  const tasks           = active ? (state.task_list || []) : []
  const settlement      = active ? (state.settlement || {}) : {}
  const actLabel        = (k) => MS_ACTIONS[k]?.label || k

  return (
    <div className="space-y-4">

      {/* ── Red LIVE banner ─────────────────────────────────────────────────── */}
      {active && (
        <div className="bg-gradient-to-r from-red-900 via-red-950 to-slate-950 border-2 border-red-700/70 rounded-2xl px-5 py-3 flex items-center gap-3 shadow-lg shadow-red-950/40">
          <span className="w-2.5 h-2.5 rounded-full bg-red-400 animate-pulse block flex-shrink-0" />
          <span className="text-sm font-extrabold text-red-100 tracking-wide">TIME MACHINE IS LIVE</span>
          <span className="text-xs text-red-300/80">simulated clock · dev DB only · production untouched</span>
          <div className="ml-auto flex items-center gap-3 text-xs">
            <span className="text-red-300/80">auto-revert in <span className="font-bold text-red-200"><MsCountdown seconds={ttlLocal} /></span></span>
          </div>
        </div>
      )}

      {/* ── The Watch ───────────────────────────────────────────────────────── */}
      <DevCard icon={Clock} iconBg="bg-violet-950" iconColor="text-violet-400"
               title="Simulation Watch" subtitle="event-to-event time travel on the dev database">
        {active ? (
          <div className="space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-end gap-4 sm:gap-8">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-violet-400/80">{state.day_of_week}</p>
                <p className="text-4xl font-black tabular-nums text-slate-100 leading-tight mt-1">{state.time_str}</p>
                <p className="text-sm text-slate-400 mt-0.5">{state.date_str} · UTC</p>
              </div>
              <div className="flex items-center gap-4 sm:ml-auto">
                <div className="text-center px-3">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider">Cycle</p>
                  <p className="text-xl font-black text-cyan-300 tabular-nums">{state.cycle_num}</p>
                </div>
                <div className="text-center px-3 border-l border-slate-700">
                  <p className="text-[10px] text-slate-500 uppercase tracking-wider">Event</p>
                  <p className="text-sm font-bold text-violet-300">{curMeta.label || state.current_event}</p>
                </div>
                <div className="flex items-center gap-2 pl-3 border-l border-slate-700">
                  <Radio className={`w-4 h-4 ${state.link_global ? 'text-emerald-400' : 'text-slate-600'}`} />
                  <span className="text-xs text-slate-400">Link watch</span>
                  <Toggle checked={!!state.link_global} onChange={toggleLink} label="Link global watch" />
                </div>
              </div>
            </div>
            {curMeta.note && <p className="text-xs text-slate-500 italic">— {curMeta.note}</p>}

            {/* controls */}
            {/* SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
            {/* Event-driven gating: until this event's required action is done, the */}
            {/* "Jump to next event" button is DIM + carries a note explaining why. */}
            {/* The server hard-blocks (409) even if the button is forced — no override. */}
            <div className="flex flex-wrap items-center gap-2.5">
              <button onClick={jumpNext} disabled={!!busy || !canAdvance}
                title={canAdvance ? 'Advance to the next event' : advanceReason}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-white text-sm font-semibold transition-colors disabled:opacity-40 ${
                  canAdvance ? 'bg-violet-700 hover:bg-violet-600' : 'bg-slate-700 cursor-not-allowed'
                }`}>
                {busy === '__next' ? <Spinner className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />} Jump to next event
              </button>
              <button onClick={stop} disabled={!!busy}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-red-900/60 text-slate-300 hover:text-red-200 text-sm font-semibold border border-slate-700 hover:border-red-800 disabled:opacity-40 transition-colors">
                {busy === '__stop' ? <Spinner className="w-4 h-4" /> : <XCircle className="w-4 h-4" />} Stop & revert
              </button>
            </div>
            {!canAdvance && (
              <div className="flex items-start gap-2 rounded-xl border border-amber-700/50 bg-amber-950/40 px-3 py-2">
                <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-amber-200/90 leading-relaxed">
                  <span className="font-bold">Next event locked — why dim:</span> {advanceReason || 'this event still has a required action pending.'}
                  {requiredAction.length > 0 && (
                    <> Complete <span className="font-semibold text-amber-100">{requiredAction.map(actLabel).join(' or ')}</span> in the actions below to unlock. No skipping — event-driven only.</>
                  )}
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <InfoBanner accent="blue" text="Start a session to anchor cycle 1's draw. The clock opens at that cycle's CYCLE_START; jump event→event to activate each instant's real actions. All synthetic users are dev-prefixed (msim…); production DB is never touched." />
            <div className="grid sm:grid-cols-3 gap-3">
              <DevInput label="Draw anchor (T_00H)" hint="ISO · optional" placeholder="next Sunday 00:00 UTC"
                value={anchor} onChange={e => setAnchor(e.target.value)} />
              <DevInput label="TTL (hours)" type="number" min="1" max="72"
                value={ttlHours} onChange={e => setTtlHours(e.target.value)} />
              <div className="flex items-end gap-3 pb-1">
                <div className="flex items-center gap-2">
                  <Toggle checked={linkOnStart} onChange={setLink} label="Link global watch on start" />
                  <span className="text-xs text-slate-400">Link global watch</span>
                </div>
              </div>
            </div>
            <button onClick={start} disabled={!!busy}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-violet-700 hover:bg-violet-600 text-white text-sm font-bold disabled:opacity-40 transition-colors">
              {busy === '__start' ? <Spinner className="w-4 h-4" /> : <Play className="w-4 h-4" />} Start Time Machine
            </button>
          </div>
        )}
      </DevCard>

      {/* ── Event timeline ──────────────────────────────────────────────────── */}
      {active && (
        <DevCard icon={CalendarDays} iconBg="bg-cyan-950" iconColor="text-cyan-400"
                 title="Event timeline" subtitle="click a future event to jump forward · time only moves forward">
          <div className="flex items-stretch gap-1 overflow-x-auto pb-1">
            {(state.events || []).map((ev, i) => {
              const Icon = MS_EVENT_ICONS[ev.name] || Clock
              const t = ev.iso ? new Date(ev.iso).toISOString().slice(11, 16) : ''
              const clickable = !ev.is_current && !ev.is_past
              return (
                <Fragment key={ev.name}>
                  {i > 0 && <div className={`flex-shrink-0 self-center w-4 h-px ${ev.is_past || ev.is_current ? 'bg-violet-700' : 'bg-slate-700'}`} />}
                  <button
                    disabled={!clickable || !!busy}
                    onClick={() => clickable && jumpTo(ev.name)}
                    title={ev.note}
                    className={`flex-1 min-w-[92px] flex flex-col items-center gap-1.5 px-2 py-3 rounded-xl border transition-all ${
                      ev.is_current
                        ? 'bg-violet-700/30 border-violet-500 ring-2 ring-violet-500/40'
                        : ev.is_past
                          ? 'bg-slate-800/40 border-slate-700/60 opacity-60'
                          : 'bg-slate-800/70 border-slate-700 hover:border-cyan-600 hover:bg-cyan-950/30 cursor-pointer'
                    } ${(!clickable || busy) ? 'cursor-default' : ''}`}
                  >
                    <div className={`p-1.5 rounded-lg ${ev.is_current ? 'bg-violet-600' : ev.is_past ? 'bg-slate-700' : 'bg-slate-700'}`}>
                      {busy === '__to:' + ev.name ? <Spinner className="w-3.5 h-3.5" /> : <Icon className={`w-3.5 h-3.5 ${ev.is_current ? 'text-white' : ev.is_past ? 'text-emerald-400' : 'text-slate-300'}`} />}
                    </div>
                    <span className={`text-[10px] font-bold text-center leading-tight ${ev.is_current ? 'text-violet-200' : 'text-slate-400'}`}>{ev.short}</span>
                    <span className="text-[9px] tabular-nums text-slate-500">{t}</span>
                  </button>
                </Fragment>
              )
            })}
          </div>
        </DevCard>
      )}

      {/* ── Payment compliance + per-event task list ────────────────────────── */}
      {/* SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
      {/* Separate panel (user req #3): before the next event, show unpaid / late / */}
      {/* grace / eliminated counts + an event-wise task list, all from production    */}
      {/* tables (backend _compliance + task_list). Presentation only — no override.  */}
      {active && compliance && (
        <DevCard icon={Users} iconBg="bg-blue-950" iconColor="text-blue-400"
                 title="Payment compliance & tasks"
                 subtitle={`real dev-DB counts before next event · cycle ${state.cycle_num} · ${curMeta.label || state.current_event}`}>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
            <StatPill label="Active members"   value={NUM(compliance.active)}                accent="emerald" />
            <StatPill label="Paid on time"     value={NUM(compliance.paid_on_time)}          accent="blue" />
            <StatPill label="Unpaid"           value={NUM(compliance.unpaid)}                accent="amber" />
            <StatPill label="Late payers"      value={NUM(compliance.late_payers)}           accent="rose" />
            <StatPill label="Grace active"     value={NUM(compliance.grace_active)}          accent="purple" />
            <StatPill label="Grace-fee paid"   value={NUM(compliance.grace_fee_paid)}        accent="cyan" />
            <StatPill label="At-risk (Type B)" value={NUM(compliance.at_risk)}               accent="amber" />
            <StatPill label="Eliminated (cyc)" value={NUM(compliance.eliminated_this_cycle)} accent="rose" />
          </div>
          {tasks.length > 0 && (
            <div className="mt-4">
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-2">
                Task list — {curMeta.label || state.current_event}
              </p>
              <ul className="space-y-1.5">
                {tasks.map((t, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-slate-300 leading-relaxed">
                    <ChevronRight className="w-3.5 h-3.5 text-cyan-500 flex-shrink-0 mt-0.5" />
                    <span>{t}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </DevCard>
      )}

      {/* ── A / B / C settlement guide (grace event only) ───────────────────── */}
      {/* SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
      {/* TRUTHFUL production lifecycle (the synthetic apply_abc_model re-sampler was   */}
      {/* REMOVED). The base cohort is the REAL at-risk set (Active · Unpaid · risk=    */}
      {/* True, carried forward from Due-date) — NOT a fresh random re-sample. It splits */}
      {/* into A (eliminate non-payment) · C (grace-fee paid → survive) · B (remainder, */}
      {/* grace granted but EXPIRES at G_CLOSE → eliminated grace_expired). Preview      */}
      {/* mirrors the backend's clamping split exactly so A + B + C == at_risk always.   */}
      {active && state.current_event === 'GRACE_PERIOD_START' && (() => {
        const gRisk = compliance?.at_risk ?? 0
        const gA = Number(inputs.elim_pct_a ?? settlement.elim_pct_a ?? 80)
        const gC = Number(inputs.grace_pct_c ?? settlement.grace_pct_c ?? 15)
        // Exact mirror of dev.py grace_settle: floor + clamp so B is never negative.
        const pA = Math.min(gRisk, Math.floor(gRisk * gA / 100))
        const pC = Math.min(gRisk - pA, Math.floor(gRisk * gC / 100))
        const pB = gRisk - pA - pC
        const squeezed = (gA + gC) > 100
        return (
          <DevCard icon={Info} iconBg="bg-purple-950" iconColor="text-purple-300"
                   title="A / B / C settlement — how to fill the model"
                   subtitle="real at-risk cohort (carried forward from Due-date) splits into three buckets — no re-sampling">
            <div className="space-y-3">
              <p className="text-xs text-slate-300 leading-relaxed">
                The <span className="font-bold text-rose-300">{gRisk}</span> at-risk member(s) this cycle are the genuine
                Unpaid old members flagged at Due-date (paid members &amp; fresh joiners are never touched). The model
                splits this cohort three ways — <span className="font-semibold text-slate-200">A%</span> and{' '}
                <span className="font-semibold text-slate-200">C%</span> are percentages <em>of the at-risk set</em>;
                B is whatever remains.
              </p>
              <div className="grid sm:grid-cols-3 gap-2.5">
                <div className="rounded-xl border border-red-800/50 bg-red-950/30 p-3">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-red-300">A · Eliminate</p>
                  <p className="text-2xl font-black text-red-200 tabular-nums mt-1">{pA}</p>
                  <p className="text-[11px] text-slate-400 mt-1">{gA}% → guillotine at G_CLOSE (reason <span className="font-mono">non_payment</span>).</p>
                </div>
                <div className="rounded-xl border border-emerald-800/50 bg-emerald-950/30 p-3">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-300">C · Grace-pay</p>
                  <p className="text-2xl font-black text-emerald-200 tabular-nums mt-1">{pC}</p>
                  <p className="text-[11px] text-slate-400 mt-1">{gC}% → pay grace + late fee now → <span className="font-semibold text-emerald-300">survive</span>.</p>
                </div>
                <div className="rounded-xl border border-amber-800/50 bg-amber-950/30 p-3">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-amber-300">B · Grace-expires</p>
                  <p className="text-2xl font-black text-amber-200 tabular-nums mt-1">{pB}</p>
                  <p className="text-[11px] text-slate-400 mt-1">rest → grace granted but lapses at G_CLOSE → eliminated <span className="font-mono">grace_expired</span>.</p>
                </div>
              </div>
              {squeezed ? (
                <div className="flex items-start gap-2 rounded-xl border border-amber-700/60 bg-amber-950/50 px-3 py-2">
                  <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-200">A% + C% = {gA + gC}% exceeds 100%. The model does not reject this —
                    A takes its share first, then <span className="font-semibold">C is clamped to the remainder</span> (here {pC}),
                    leaving B = {pB}. A + B + C still equals the at-risk count.</p>
                </div>
              ) : (
                <p className="text-[11px] text-slate-500">
                  Invariant (always holds, B clamps):{' '}
                  <span className="font-mono text-slate-300">A + B + C = {pA} + {pB} + {pC} = {pA + pB + pC} = at-risk ({gRisk})</span>.
                  Fill the fields in <span className="font-semibold">“Run grace settlement”</span> below; only C survives — A and B are both eliminated at G_CLOSE.
                </p>
              )}
            </div>
          </DevCard>
        )
      })()}

      {/* ── Action panel for the current event ──────────────────────────────── */}
      {active && (
        <DevCard icon={Zap} iconBg="bg-amber-950" iconColor="text-amber-400"
                 title={`Actions — ${curMeta.label || state.current_event}`}
                 subtitle="each runs a real production service at the simulated instant">
          <div className="space-y-3">
            {avail.map(key => {
              const reg = MS_ACTIONS[key]
              if (!reg) return null
              const Icon = reg.icon
              // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
              // Locked = already-done / mutually-exclusive at this event (backend
              // disabled_actions). Required = the gating action still pending.
              const locked = disabledActions.includes(key)
              const isRequired = requiredAction.includes(key) && !requiredDone
              return (
                <div key={key}
                  className={`flex flex-wrap items-end gap-3 rounded-xl p-3 border transition-colors ${
                    locked
                      ? 'bg-slate-900/40 border-slate-800/60 opacity-50'
                      : isRequired
                        ? 'bg-amber-950/20 border-amber-700/50 ring-1 ring-amber-700/40'
                        : 'bg-slate-800/40 border-slate-700/50'
                  }`}>
                  {(reg.fields || []).map(f => (
                    <div key={f.k} className="w-32">
                      <label className="block text-[11px] text-slate-400 font-medium mb-1">{f.label}</label>
                      <input
                        type="number" step={f.step ?? 1}
                        disabled={locked || !!busy}
                        value={inputs[f.k] ?? (f.def ?? '')}
                        onChange={e => setField(f.k, e.target.value)}
                        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-600 disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                    </div>
                  ))}
                  <div className="ml-auto flex items-center gap-2">
                    {locked && (
                      <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-400/80">
                        <CheckCircle2 className="w-3.5 h-3.5" /> {disabledReasons[key] || 'done — locked'}
                      </span>
                    )}
                    {isRequired && !locked && (
                      <span className="text-[11px] font-semibold text-amber-300">required here</span>
                    )}
                    <button onClick={() => runAction(key)} disabled={!!busy || locked}
                      title={locked ? (disabledReasons[key] || 'Already completed at this event — no override / overwrite') : reg.label}
                      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-white text-sm font-semibold disabled:opacity-40 transition-colors ${
                        locked ? 'bg-slate-700 cursor-not-allowed' : (_btnAccent[reg.accent] || _btnAccent.slate)
                      }`}>
                      {busy === key ? <Spinner className="w-4 h-4" /> : <Icon className="w-4 h-4" />} {reg.label}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </DevCard>
      )}

      {/* ── Snapshot + last result ──────────────────────────────────────────── */}
      {active && snap && (
        <DevCard icon={Database} iconBg="bg-emerald-950" iconColor="text-emerald-400"
                 title="Live snapshot" subtitle="real dev-DB counts at the simulated instant">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
            <StatPill label="Live members" value={NUM(snap.live_members)} accent="emerald" />
            <StatPill label="Waitlist"     value={NUM(snap.waitlist)}     accent="cyan" />
            <StatPill label="Paid on time" value={NUM(snap.paid_on_time)} accent="blue" />
            <StatPill label="Unpaid"       value={NUM(snap.unpaid)}       accent="amber" />
            <StatPill label="Pools active" value={NUM(snap.pools_active)} accent="purple" />
            <StatPill label="Pools paused" value={NUM(snap.pools_paused)} accent="rose" />
          </div>

          {last && (
            <ResultBox>
              <p className="text-xs text-slate-400 mb-2">
                Last action: <code className="text-violet-300 font-bold">{last.action}</code>
              </p>
              {/* SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
              {/* Legible outcome summary (A/B/C buckets · guillotine reasons · waitlist hold) */}
              {/* above the raw response so the operator reads the result at a glance.        */}
              <MsActionSummary action={last.action} result={last.result} />
              <pre className="text-[11px] font-mono text-slate-300 bg-slate-950/70 border border-slate-800 rounded-xl p-3 overflow-x-auto max-h-60 mt-3">
{JSON.stringify(last.result, null, 2)}
              </pre>
            </ResultBox>
          )}
        </DevCard>
      )}
    </div>
  )
}


// SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Stress Test tab removed (synthetic-data tool retired — production validation now
// runs through the Time Machine). Tabs renumbered: Draw 0, Injection 1, Danger 2,
// Forensic 3, Time Machine 4. TIME_MACHINE_TAB is the default (prominence).
const TIME_MACHINE_TAB = 4
const TABS = [
  { id:0, icon:Zap,          label:'Draw Control', short:'Draw'    },
  { id:1, icon:UserPlus,     label:'Injection',    short:'Inject'  },
  { id:2, icon:Skull,        label:'Danger Zone',  short:'Danger', danger:true },
  // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
  { id:3, icon:ScrollText,   label:'Forensic',     short:'Forensic' },
  // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
  { id:TIME_MACHINE_TAB, icon:Clock, label:'Time Machine', short:'Time'   },
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
  // SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Default to the Time Machine tab (production-fidelity manual simulator).
  const [tab, setTab] = useState(TIME_MACHINE_TAB)
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
        {/* SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
        {/* Stress Test removed; tabs renumbered (Draw 0, Inject 1, Danger 2, Forensic 3, Time Machine 4). */}
        <div>
          {tab===0&&<DrawControlTab toast={toast}/>}
          {tab===1&&<InjectionTab   toast={toast}/>}
          {tab===2&&<DangerTab      toast={toast}/>}
          {/* SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
          {tab===3&&<ForensicTab    toast={toast}/>}
          {/* SESSION EDIT [Claude Session Jun-24 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
          {tab===TIME_MACHINE_TAB&&<TimeMachineTab toast={toast}/>}
        </div>

        <div className="h-8"/>
      </div>
    </div>
  )
}
