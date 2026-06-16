import { useState, useEffect, useCallback, Fragment } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BarChart3, TrendingUp, TrendingDown, RefreshCw,
  IndianRupee, Users, Layers, Clock, Zap, AlertTriangle,
  CheckCircle2, XCircle, Shield, Target, Activity,
  ChevronDown, ChevronRight, CheckCheck, AlertCircle,
  Calculator, Info, Cpu, CalendarRange, Download, TableProperties,
  Gavel, DollarSign, Trophy, Award, GitFork,
} from 'lucide-react'

// ── Framer-motion variants ─────────────────────────────────────────────────────
const _fadeUp  = { initial:{opacity:0,y:12}, animate:{opacity:1,y:0}, exit:{opacity:0,y:-8},
                   transition:{duration:0.32,ease:[0.25,1,0.5,1]} }
const _stagger = { animate:{ transition:{ staggerChildren:0.06 }}}
import {
  ResponsiveContainer,
  AreaChart, Area,
  BarChart,
  ComposedChart, Bar, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
  Cell,
} from 'recharts'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import {
  getFinancials, getPoolStats, getTokenStats,
  getAiForecast, getChartData, getLevelBreakdown,
  getAdminTokens, updateTokenStatus, burnToken,
  getBrain5Lpi,
  devLiveStats, devLevelMap, devWinnersAnalytics, devProjection,
  getPauseCalendar, getWeeklyPoolReports,
  getReferralTrend, getWinnerLevelTrend,
  getWeeklyTimeline,
} from '../api/client'
import { useToast } from '../context/ToastContext'

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const INR = v =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0,
  }).format(parseFloat(v ?? 0))

const INR_COMPACT = v => {
  const n = parseFloat(v ?? 0)
  if (n >= 10_00_000) return `₹${(n / 10_00_000).toFixed(1)}Cr`
  if (n >= 1_00_000)  return `₹${(n / 1_00_000).toFixed(1)}L`
  if (n >= 1_000)     return `₹${(n / 1_000).toFixed(1)}K`
  return `₹${n}`
}

const NUM  = v  => new Intl.NumberFormat('en-IN').format(v ?? 0)
const fP   = v  => parseFloat(v  ?? 0)
const fI   = v  => parseInt(v    ?? 0, 10)

// Recharts colour palette — hex so they work inside SVG
const C = {
  emerald : '#10b981',
  rose    : '#f43f5e',
  blue    : '#3b82f6',
  amber   : '#f59e0b',
  violet  : '#7c3aed',
  slate   : '#94a3b8',
  teal    : '#0d9488',
}

// Level → net payout mapping (mirrors backend LEVEL_PAYOUTS)
const LEVEL_PAYOUT = { 1: 2000, 2: 3000, 3: 4000, 4: 5500, 5: 6500, 6: 8000 }

// ─────────────────────────────────────────────────────────────────────────────
// Micro-components
// ─────────────────────────────────────────────────────────────────────────────

function Skeleton({ className = '' }) {
  return <div className={`animate-pulse bg-slate-100 rounded-xl ${className}`} />
}

function SectionCard({ title, icon: Icon, iconColor = 'text-slate-400', action, children }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
        {Icon && <Icon className={`w-4 h-4 flex-shrink-0 ${iconColor}`} />}
        <h2 className="font-semibold text-slate-800">{title}</h2>
        {action && <div className="ml-auto flex-shrink-0">{action}</div>}
      </div>
      {children}
    </div>
  )
}

function KPICard({ label, value, sub, icon: Icon, iconBg, iconColor, trend, loading: isLoading }) {
  if (isLoading) {
    return (
      <div className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100 space-y-3">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-8 w-36" />
        <Skeleton className="h-3 w-48" />
      </div>
    )
  }
  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider leading-none">
            {label}
          </p>
          <p className={`mt-2 text-2xl font-black tabular-nums leading-none ${
            trend === 'positive' ? 'text-emerald-600' :
            trend === 'negative' ? 'text-red-600'     :
            trend === 'warn'     ? 'text-amber-600'   :
            'text-slate-900'
          }`}>
            {value}
          </p>
          {sub && (
            <p className="mt-1.5 text-[11px] text-slate-400 leading-tight">{sub}</p>
          )}
        </div>
        <div className={`${iconBg} p-2.5 rounded-xl flex-shrink-0`}>
          <Icon className={`w-5 h-5 ${iconColor}`} />
        </div>
      </div>
      {(trend === 'positive' || trend === 'negative') && (
        <div className={`mt-3 flex items-center gap-1 text-[11px] font-semibold ${
          trend === 'positive' ? 'text-emerald-600' : 'text-red-600'
        }`}>
          {trend === 'positive'
            ? <TrendingUp  className="w-3.5 h-3.5" />
            : <TrendingDown className="w-3.5 h-3.5" />
          }
          {trend === 'positive' ? 'Cash-flow positive' : 'Monitor closely'}
        </div>
      )}
    </div>
  )
}

// Hover tooltip for financial metric explanations
function InfoTooltip({ text }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative inline-flex ml-auto">
      <button
        type="button"
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        onFocus={() => setShow(true)}
        onBlur={() => setShow(false)}
        className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 transition-colors bg-white/20 hover:bg-white/35 text-white/60 hover:text-white focus:outline-none"
        aria-label="More information"
      >
        <Info className="w-3 h-3" />
      </button>
      {show && (
        <div
          className="absolute z-50 bottom-full right-0 mb-2.5 w-72 bg-slate-900 border border-slate-700 text-slate-100 text-[11px] rounded-2xl px-4 py-3 shadow-2xl leading-relaxed pointer-events-none"
        >
          {text}
          {/* Downward arrow */}
          <div
            className="absolute top-full right-4"
            style={{
              width: 0, height: 0,
              borderLeft: '6px solid transparent',
              borderRight: '6px solid transparent',
              borderTop: '6px solid #1e293b',
            }}
          />
        </div>
      )}
    </div>
  )
}

function ConfidenceBadge({ confidence }) {
  const styles = {
    high:              'bg-emerald-50 text-emerald-700 border-emerald-200',
    medium:            'bg-amber-50   text-amber-700   border-amber-200',
    low:               'bg-red-50     text-red-700     border-red-200',
    insufficient_data: 'bg-slate-50   text-slate-500   border-slate-200',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold border ${
      styles[confidence] ?? styles.insufficient_data
    }`}>
      {(confidence ?? 'unknown').replace('_', ' ')}
    </span>
  )
}

function LevelBadge({ level }) {
  const styles = [
    '', 'bg-slate-100 text-slate-600', 'bg-blue-50 text-blue-700',
    'bg-teal-50 text-teal-700', 'bg-violet-50 text-violet-700',
    'bg-amber-50 text-amber-700', 'bg-rose-50 text-rose-700',
  ]
  return (
    <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${
      styles[level] ?? styles[1]
    }`}>
      {level}
    </span>
  )
}

// Custom Recharts tooltip — consistent across both charts
function ChartTip({ active, payload, label, currency }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-lg px-4 py-3 text-sm min-w-[160px]">
      <p className="font-semibold text-slate-700 mb-2 text-xs">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center justify-between gap-4 text-xs mb-1">
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="font-bold text-slate-800 tabular-nums">
            {currency ? INR(p.value) : NUM(p.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

// Error inline banner
function InlineError({ message }) {
  if (!message) return null
  return (
    <div className="flex items-center gap-2 bg-red-50 border border-red-100 rounded-xl px-4 py-3 text-sm text-red-600">
      <AlertCircle className="w-4 h-4 flex-shrink-0" />
      {message}
    </div>
  )
}

// ── Brain 5 LPI Semicircle Gauge ─────────────────────────────────────────────
// Renders a top-semicircle arc (9 o'clock → 12 o'clock → 3 o'clock) filled
// proportionally to `lpi`.  SVG arc: M 10 60 A 50 50 0 0 0 110 60
// sweep=0 → counter-clockwise from left → traces OVER the top ✓
function LpiGauge({ lpi = 0 }) {
  const r    = 50
  const half = Math.PI * r                    // ≈ 157.08 — total path length
  const fill = half * Math.min(100, Math.max(0, lpi)) / 100

  const color = lpi < 14 ? '#10b981'
              : lpi < 25 ? '#f59e0b'
              : lpi < 50 ? '#f97316'
              :             '#ef4444'
  const zone  = lpi < 14 ? 'Healthy'
              : lpi < 25 ? 'Caution'
              : lpi < 50 ? 'Elevated'
              :             'Critical'

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 120 68" className="w-44 select-none">
        {/* Background track */}
        <path d="M 10 60 A 50 50 0 0 0 110 60"
              fill="none" stroke="#e2e8f0" strokeWidth="10" strokeLinecap="round" />
        {/* Filled arc — proportion = lpi / 100 */}
        <path d="M 10 60 A 50 50 0 0 0 110 60"
              fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
              strokeDasharray={`${fill} ${half}`}
              style={{ transition: 'stroke-dasharray 0.9s cubic-bezier(0.25,1,0.5,1)' }}
        />
        {/* LPI value */}
        <text x="60" y="52" textAnchor="middle" fontSize="17" fontWeight="800"
              fill={color} fontFamily="ui-monospace,monospace">
          {lpi.toFixed(1)}%
        </text>
        {/* Sub-label */}
        <text x="60" y="64" textAnchor="middle" fontSize="7.5" fill="#94a3b8" letterSpacing="1.2">
          PRESSURE INDEX
        </text>
      </svg>
      <span className={`text-[11px] font-bold -mt-1 ${
        lpi < 14 ? 'text-emerald-600'
      : lpi < 25 ? 'text-amber-600'
      : lpi < 50 ? 'text-orange-600'
      :             'text-red-600'
      }`}>
        {zone}
      </span>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Statistics sub-tab panel helpers (light theme, always accessible)
// ─────────────────────────────────────────────────────────────────────────────

const LVL_PILL_COLORS = ['#94a3b8','#3b82f6','#8b5cf6','#f59e0b','#f97316','#ef4444']

function AnalyticsCard({ title, icon: Icon, iconColor = 'text-violet-500', children, className = '' }) {
  return (
    <div className={`bg-white rounded-2xl shadow-sm border border-slate-100 ${className}`}>
      <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
        {Icon && <Icon className={`w-4 h-4 flex-shrink-0 ${iconColor}`} />}
        <h3 className="font-semibold text-slate-800 text-sm">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

function ARow({ label, value, color = 'text-slate-900' }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
      <span className="text-sm text-slate-500">{label}</span>
      <span className={`text-sm font-bold tabular-nums ${color}`}>{value}</span>
    </div>
  )
}

// ── Live Stats panel ─────────────────────────────────────────────────────────
function LiveStatsPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastUp,  setLastUp]  = useState(null)
  const fetch_ = useCallback(async () => {
    try { const r = await devLiveStats(); setData(r.data); setLastUp(new Date()) }
    catch  { toast('Failed to load live stats', 'error') }
    finally { setLoading(false) }
  }, [toast])
  useEffect(() => { fetch_() }, [fetch_])
  useEffect(() => { const id = setInterval(fetch_, 30_000); return () => clearInterval(id) }, [fetch_])

  if (loading) return <div className="flex items-center justify-center h-48"><Spinner className="w-8 h-8 text-violet-500" /></div>
  if (!data)   return null

  const lvlData = Object.entries(data.levels).map(([k, v]) => ({ level: k, count: v }))
  const INR_    = n => `₹${Number(n ?? 0).toLocaleString('en-IN')}`

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400">
          {lastUp ? `Updated ${lastUp.toLocaleTimeString()} · auto-refresh 30 s` : ''}
        </p>
        <button onClick={fetch_} className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 rounded-xl text-xs text-slate-500 hover:bg-slate-50 transition">
          <RefreshCw className="w-3.5 h-3.5"/>Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <AnalyticsCard title="User Distribution" icon={Users}>
          <ARow label="Active in Pools" value={data.users.active}  color="text-emerald-600" />
          <ARow label="Waitlist"        value={data.users.waitlist} color="text-blue-600"    />
          <ARow label="Winners"         value={data.users.won}     color="text-violet-600"  />
          <ARow label="Eliminated"      value={data.users.unpaid}  color="text-red-500"     />
          <ARow label="Total"           value={data.users.total}                             />
        </AnalyticsCard>

        <AnalyticsCard title="Pool Overview" icon={Layers}>
          <ARow label="Active Pools" value={data.pools.active}  color="text-emerald-600" />
          <ARow label="Paused"       value={data.pools.paused}  color="text-amber-600"   />
          <ARow label="Waiting"      value={data.pools.waiting} color="text-blue-600"    />
          <ARow label="Total Pools"  value={data.pools.total}                            />
        </AnalyticsCard>

        <AnalyticsCard title="Brain 5 — SDE / LPI" icon={Cpu}>
          <ARow label="LPI" value={`${data.sde.lpi}%`}
            color={data.sde.lpi >= 25 ? 'text-red-600' : data.sde.lpi >= 14 ? 'text-amber-600' : 'text-emerald-600'} />
          <ARow label="L4 Flagged"  value={data.sde.l4_flagged} color={data.sde.l4_flagged > 0 ? 'text-red-600' : 'text-slate-400'} />
          <ARow label="AI Scenario" value={data.ai.scenario.replace(/_/g,' ')} color="text-violet-700" />
          <ARow label="Velocity"    value={`${data.ai.velocity}/wk`}           color="text-blue-600"   />
        </AnalyticsCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <AnalyticsCard title="Level Distribution (Active Members)" icon={BarChart3}>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={lvlData} margin={{top:4,right:4,left:-20,bottom:4}}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
              <XAxis dataKey="level" tick={{fill:'#64748b',fontSize:11,fontWeight:700}} tickLine={false} axisLine={false}/>
              <YAxis tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} axisLine={false}/>
              <Tooltip contentStyle={{background:'#fff',border:'1px solid #e2e8f0',borderRadius:8,fontSize:11}}/>
              <Bar dataKey="count" name="Members" radius={[4,4,0,0]} maxBarSize={40}>
                {lvlData.map((e,i) => <Cell key={i} fill={LVL_PILL_COLORS[i % 6]}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </AnalyticsCard>

        <AnalyticsCard title="Financial Snapshot" icon={IndianRupee}>
          <ARow label="Total Collected" value={INR_(data.financials.total_collected_inr)} color="text-emerald-600" />
          <ARow label="Total Paid Out"  value={INR_(data.financials.total_paid_out_inr)}  color="text-rose-500"   />
          <ARow label="Net Float"       value={INR_(data.financials.net_float_inr)}
            color={data.financials.net_float_inr >= 0 ? 'text-blue-600' : 'text-red-600'} />
          {(data.payments?.paid_in_pools != null) && (
            <>
              <div className="mt-3 pt-3 border-t border-slate-100">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs text-slate-500">Weekly payment rate</span>
                  <span className="text-xs font-bold text-emerald-600">{data.payments.paid_pct}%</span>
                </div>
                <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full bg-emerald-400 transition-all"
                       style={{width:`${data.payments.paid_pct}%`}}/>
                </div>
              </div>
            </>
          )}
        </AnalyticsCard>
      </div>
    </div>
  )
}

// ── Level Map panel ──────────────────────────────────────────────────────────
function LevelMapPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter,  setFilter]  = useState('all')
  const [expanded, setExpanded] = useState(new Set())
  const fetch_ = useCallback(async () => {
    setLoading(true)
    try { const r = await devLevelMap(); setData(r.data) }
    catch { toast('Failed to load level map', 'error') }
    finally { setLoading(false) }
  }, [toast])
  useEffect(() => { fetch_() }, [fetch_])

  if (loading) return <div className="flex items-center justify-center h-48"><Spinner className="w-8 h-8 text-violet-500"/></div>
  if (!data)   return null

  const LEVEL_PILL_CLS = [
    'bg-slate-100 text-slate-600', 'bg-blue-50 text-blue-700',
    'bg-violet-50 text-violet-700', 'bg-amber-50 text-amber-700',
    'bg-orange-50 text-orange-700', 'bg-rose-50 text-rose-700',
  ]
  const lks = ['L1','L2','L3','L4','L5','L6']
  const s   = data.summary
  const filtered = data.pools.filter(p => {
    if (filter === 'all') return true
    return (p.level_counts[filter.toUpperCase()] ?? 0) > 0
  })

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-7 gap-2">
        {lks.map((lk, i) => (
          <div key={lk} className={`${LEVEL_PILL_CLS[i]} rounded-xl p-3 text-center border border-slate-100`}>
            <p className="text-[10px] uppercase tracking-wide mb-1 font-semibold opacity-70">{lk}</p>
            <p className="text-xl font-black">{(s.by_level[lk] ?? 0).toLocaleString('en-IN')}</p>
          </div>
        ))}
        <div className="bg-slate-50 rounded-xl p-3 text-center border border-slate-100">
          <p className="text-[10px] uppercase tracking-wide mb-1 font-semibold text-slate-400">Active</p>
          <p className="text-xl font-black text-slate-700">{s.total_active_members.toLocaleString('en-IN')}</p>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {['all','L1','L2','L3','L4'].map(f => (
          <button key={f} onClick={() => setFilter(f.toLowerCase())}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition border ${
              filter === f.toLowerCase()
                ? 'bg-violet-600 text-white border-violet-600'
                : 'bg-white text-slate-500 border-slate-200 hover:bg-slate-50'
            }`}>
            {f === 'all' ? 'All Pools' : `${f} Members`}
          </button>
        ))}
        <button onClick={fetch_} className="ml-auto px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-500 hover:bg-slate-50 transition flex items-center gap-1.5">
          <RefreshCw className="w-3 h-3"/>Refresh
        </button>
      </div>

      <p className="text-xs text-slate-400">{filtered.length} of {data.pools.length} pools</p>

      <div className="space-y-2">
        {filtered.map(pool => (
          <div key={pool.id} className="bg-white rounded-xl border border-slate-100 shadow-sm overflow-hidden">
            <div className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-slate-50 transition"
                 onClick={() => setExpanded(prev => { const n = new Set(prev); n.has(pool.id) ? n.delete(pool.id) : n.add(pool.id); return n })}>
              <ChevronRight className={`w-4 h-4 text-slate-400 flex-shrink-0 transition-transform ${expanded.has(pool.id) ? 'rotate-90' : ''}`}/>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="font-semibold text-slate-800 text-sm">{pool.name}</p>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border ${
                    pool.status === 'Active' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200'
                  }`}>{pool.status}</span>
                  {pool.contains_l4 && <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-red-50 text-red-700 border border-red-200">⚠ L4</span>}
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">{pool.member_count}/12 members · {pool.pool_draw_type}</p>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                {lks.map((lk, i) => {
                  const cnt = pool.level_counts[lk] ?? 0
                  if (!cnt) return null
                  return (
                    <span key={lk} className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${LEVEL_PILL_CLS[i]}`}>
                      {lk}:{cnt}
                    </span>
                  )
                })}
              </div>
            </div>
            {expanded.has(pool.id) && (
              <div className="border-t border-slate-100 px-4 pb-3 pt-2">
                {lks.map((lk, i) => {
                  const mbrs = pool.members_by_level[lk] ?? []
                  if (!mbrs.length) return null
                  return (
                    <div key={lk} className="flex items-start gap-2 py-1.5 border-b border-slate-50 last:border-0">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded flex-shrink-0 mt-0.5 ${LEVEL_PILL_CLS[i]}`}>{lk}</span>
                      <div className="flex flex-wrap gap-1.5">
                        {mbrs.map(m => (
                          <span key={m.id} className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                            m.sde_required ? 'bg-rose-50 border-rose-200 text-rose-700' :
                            m.paid ? 'bg-emerald-50 border-emerald-200 text-emerald-700' :
                            'bg-slate-50 border-slate-200 text-slate-500'
                          }`}>
                            @{m.username}{m.sde_required ? ' SDE' : ''}
                          </span>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Winners Analytics panel ──────────────────────────────────────────────────
function WinnersPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    devWinnersAnalytics()
      .then(r => setData(r.data))
      .catch(() => toast('Failed to load winners', 'error'))
      .finally(() => setLoading(false))
  }, [toast])

  if (loading) return <div className="flex items-center justify-center h-48"><Spinner className="w-8 h-8 text-violet-500"/></div>
  if (!data)   return null

  const barData = data.by_level.map((d, i) => ({
    level: `L${d.level}`, winners: d.winners,
    payout: d.total_payout_inr / 1000, avg: d.avg_payout_inr / 1000,
    fill: LVL_PILL_COLORS[i],
  }))
  const INR_ = n => `₹${Number(n ?? 0).toLocaleString('en-IN')}`

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Total Winners',  value: data.summary.total_winners,                          color: 'text-violet-700' },
          { label: 'Total Paid Out', value: INR_(data.summary.total_payout_inr),                  color: 'text-rose-600'   },
          { label: 'Avg Payout',     value: INR_(data.summary.avg_payout_inr),                   color: 'text-slate-700'  },
          { label: 'SDE Exits',      value: data.summary.sde_exits, color: data.summary.sde_exits > 0 ? 'text-cyan-600' : 'text-slate-400' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4 text-center">
            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">{label}</p>
            <p className={`text-xl font-black ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      <AnalyticsCard title="Winners per Level" icon={Target}>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={barData} margin={{top:4,right:4,left:-20,bottom:4}}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
            <XAxis dataKey="level" tick={{fill:'#64748b',fontSize:11,fontWeight:700}} tickLine={false} axisLine={false}/>
            <YAxis tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} axisLine={false}/>
            <Tooltip contentStyle={{background:'#fff',border:'1px solid #e2e8f0',borderRadius:8,fontSize:11}}/>
            <Bar dataKey="winners" name="Winners" radius={[4,4,0,0]} maxBarSize={40}>
              {barData.map((e,i) => <Cell key={i} fill={e.fill}/>)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </AnalyticsCard>

      <AnalyticsCard title="Level-Wise Distribution" icon={BarChart3}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-100">
              {['Level','Winners','Total Payout','Avg Payout','SDE %','% of Total'].map(h => (
                <th key={h} className="text-left px-3 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {data.by_level.map((d, i) => (
                <tr key={d.level} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                  <td className="px-3 py-2.5"><LevelBadge level={d.level}/></td>
                  <td className="px-3 py-2.5 font-semibold text-slate-700 tabular-nums">{d.winners.toLocaleString('en-IN')}</td>
                  <td className="px-3 py-2.5 text-rose-600 tabular-nums">{INR_(d.total_payout_inr)}</td>
                  <td className="px-3 py-2.5 text-slate-500 tabular-nums">{INR_(d.avg_payout_inr)}</td>
                  <td className="px-3 py-2.5 tabular-nums text-slate-500">{d.sde_pct}%</td>
                  <td className="px-3 py-2.5 font-semibold text-violet-700 tabular-nums">{d.pct_of_total}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AnalyticsCard>
    </div>
  )
}

// ── Projections panel ────────────────────────────────────────────────────────
function ProjectionsPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const fetch_ = useCallback(async () => {
    setLoading(true)
    try { const r = await devProjection(); setData(r.data) }
    catch { toast('Failed to load projections', 'error') }
    finally { setLoading(false) }
  }, [toast])
  useEffect(() => { fetch_() }, [fetch_])

  if (loading) return <div className="flex items-center justify-center h-48"><Spinner className="w-8 h-8 text-violet-500"/></div>
  if (!data)   return null

  const t    = data.totals
  const INR_ = n => `₹${Number(n ?? 0).toLocaleString('en-IN')}`

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: 'Eligible Pools',    value: data.eligible_pools,               color: 'text-blue-600'  },
          { label: 'Proj. Collection',  value: INR_(t.projected_collection_inr),  color: 'text-emerald-600' },
          { label: 'Proj. Payout',      value: INR_(t.projected_payout_inr),      color: 'text-rose-600'  },
          { label: 'Proj. Profit',      value: INR_(t.projected_profit_inr),      color: t.projected_profit_inr >= 0 ? 'text-violet-700' : 'text-red-600' },
          { label: 'Fee Income',        value: INR_(t.fee_income_inr),            color: 'text-slate-700' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4 text-center">
            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">{label}</p>
            <p className={`text-lg font-black ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <AnalyticsCard title="LPI Projection (Post-Draw)" icon={Cpu}>
          <ARow label="Current LPI"     value={`${data.post_draw_lpi.current_lpi}%`}
            color={data.post_draw_lpi.current_lpi >= 25 ? 'text-red-600' : 'text-emerald-600'} />
          <ARow label="Est. Post-Draw"  value={`${data.post_draw_lpi.estimated_lpi}%`}
            color={data.post_draw_lpi.estimated_lpi >= 25 ? 'text-amber-600' : 'text-emerald-600'} />
          <ARow label="Current L4"      value={data.post_draw_lpi.current_l4}      color="text-amber-600" />
          <ARow label="New L4 After"    value={data.post_draw_lpi.total_new_l4_after}
            color={data.post_draw_lpi.total_new_l4_after > 0 ? 'text-red-600' : 'text-slate-400'} />
        </AnalyticsCard>

        <AnalyticsCard title="Waitlist Pool Formation" icon={Layers}>
          <ARow label="Current Waitlist" value={data.waitlist_projection.current_waitlist}  color="text-blue-600"    />
          <ARow label="Threshold"         value={data.waitlist_projection.threshold}         />
          <ARow label="Pools Can Form"    value={data.waitlist_projection.pools_can_form}
            color={data.waitlist_projection.pools_can_form > 0 ? 'text-emerald-600' : 'text-slate-400'} />
          <ARow label="Remaining After"   value={data.waitlist_projection.waitlist_remaining} />
        </AnalyticsCard>
      </div>

      {data.pool_projections?.length > 0 && (
        <AnalyticsCard title={`Per-Pool Projections (${data.eligible_pools} eligible)`} icon={Target}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[700px]">
              <thead><tr className="border-b border-slate-100">
                {['Pool','Draw Type','Members','Lower Win','Upper Win','Proj. Payout','Profit','New L4+'].map(h => (
                  <th key={h} className="text-left px-3 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {data.pool_projections.map((p, i) => (
                  <tr key={p.pool_id} className={`border-b border-slate-50 ${i%2===0?'':'bg-slate-50/30'}`}>
                    <td className="px-3 py-2.5 font-semibold text-slate-800">{p.pool_name}</td>
                    <td className="px-3 py-2.5"><span className="text-[10px] bg-violet-50 text-violet-700 border border-violet-200 px-1.5 py-0.5 rounded font-semibold">{p.draw_type}</span></td>
                    <td className="px-3 py-2.5 text-slate-500">{p.member_count}/12</td>
                    <td className="px-3 py-2.5"><span className="bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-[10px] font-bold">L{p.proj_lower_level}</span> <span className="text-[10px] text-slate-400">{INR_(p.proj_lower_payout)}</span></td>
                    <td className="px-3 py-2.5"><span className="bg-amber-50 text-amber-700 px-1.5 py-0.5 rounded text-[10px] font-bold">L{p.proj_upper_level}</span> <span className="text-[10px] text-slate-400">{INR_(p.proj_upper_payout)}</span></td>
                    <td className="px-3 py-2.5 text-rose-600 font-semibold tabular-nums">{INR_(p.proj_total_payout)}</td>
                    <td className={`px-3 py-2.5 font-semibold tabular-nums ${p.proj_profit >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>{INR_(p.proj_profit)}</td>
                    <td className="px-3 py-2.5">{p.new_l4_after_draw > 0 ? <span className="text-red-600 font-bold">+{p.new_l4_after_draw}</span> : <span className="text-slate-300">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </AnalyticsCard>
      )}

      {data.eligible_pools === 0 && (
        <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-xl p-4">
          <AlertCircle className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5"/>
          <p className="text-sm text-blue-700">No eligible pools found. Pools need exactly 12 active members to be draw-eligible.</p>
        </div>
      )}

      <div className="flex justify-end">
        <button onClick={fetch_} className="flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-xl text-xs text-slate-500 hover:bg-slate-50 transition">
          <RefreshCw className="w-3 h-3"/>Refresh Projections
        </button>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════
// S-01: LPI History Chart — rolling weekly LPI from draw_history
// ═══════════════════════════════════════════════════════════════════════════
function LpiHistoryPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [weeks,   setWeeks]   = useState(24)

  const fetch_ = useCallback(async () => {
    setLoading(true)
    try {
      const r = await getWeeklyPoolReports(weeks)
      setData(r.data)
    } catch { toast('Failed to load LPI history', 'error') }
    finally  { setLoading(false) }
  }, [weeks, toast])

  useEffect(() => { fetch_() }, [fetch_])

  if (loading) return <div className="flex justify-center h-48"><Spinner className="w-8 h-8 text-violet-500 mt-16"/></div>
  if (!data?.weeks?.length) return <p className="text-slate-400 text-sm p-4">No draw history yet. Run at least one draw cycle.</p>

  const lpiHistory = data.weeks.map(w => ({
    week: w.week_id,
    lpi:  fP(w.avg_lpi_snapshot ?? 0),
    draws: fI(w.draw_count),
    winners: fI(w.winner_count),
  }))

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-800">LPI History — Level Pressure Index Trend</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Weekly LPI evolution. &gt;25% → SDE proactive, &gt;50% → L3 exception.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {[12, 24, 52].map(w => (
            <button key={w} onClick={() => setWeeks(w)}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition ${weeks===w?'bg-violet-600 text-white':'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}>
              {w}W
            </button>
          ))}
          <button onClick={() => fetch_()} className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 transition">
            <RefreshCw className="w-3.5 h-3.5 text-slate-500"/>
          </button>
        </div>
      </div>

      <SectionCard title="LPI Weekly Evolution" icon={Activity} iconColor="text-violet-500">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={lpiHistory} margin={{top:8,right:16,left:0,bottom:4}}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
            <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
            <YAxis yAxisId="lpi" tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false} domain={[0,100]} tickFormatter={v=>`${v}%`}/>
            <YAxis yAxisId="draws" orientation="right" tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false}/>
            <Tooltip content={<ChartTip />}/>
            <Legend wrapperStyle={{fontSize:11}}/>
            {/* LPI zones */}
            <ReferenceLine yAxisId="lpi" y={14} stroke="#10b981" strokeDasharray="4 2" label={{value:'14% Regular',fill:'#10b981',fontSize:10,position:'left'}}/>
            <ReferenceLine yAxisId="lpi" y={25} stroke="#f59e0b" strokeDasharray="4 2" label={{value:'25% SDE',fill:'#f59e0b',fontSize:10,position:'left'}}/>
            <ReferenceLine yAxisId="lpi" y={50} stroke="#ef4444" strokeDasharray="4 2" label={{value:'50% Critical',fill:'#ef4444',fontSize:10,position:'left'}}/>
            <Area yAxisId="lpi" type="monotone" dataKey="lpi" name="LPI %" stroke={C.violet} strokeWidth={2}
              fill={C.violet + '18'} dot={false} activeDot={{r:4}}/>
            <Bar yAxisId="draws" dataKey="draws" name="Draws" fill={C.blue + '40'} radius={[2,2,0,0]}/>
          </ComposedChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* LPI zone summary */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label:'Healthy (< 14%)',  color:'text-emerald-600', bg:'bg-emerald-50 border-emerald-200',  count: lpiHistory.filter(w=>w.lpi<14).length },
          { label:'Caution (14–25%)', color:'text-amber-600',   bg:'bg-amber-50 border-amber-200',     count: lpiHistory.filter(w=>w.lpi>=14&&w.lpi<25).length },
          { label:'Critical (≥ 25%)', color:'text-red-600',     bg:'bg-red-50 border-red-200',         count: lpiHistory.filter(w=>w.lpi>=25).length },
        ].map(z => (
          <div key={z.label} className={`rounded-2xl border p-4 ${z.bg}`}>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{z.label}</p>
            <p className={`text-3xl font-black tabular-nums mt-1 ${z.color}`}>{z.count}<span className="text-sm font-semibold text-slate-400 ml-1">wks</span></p>
          </div>
        ))}
      </div>
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// S-02: Financial Waterfall — cash inflow, outflow, profit waterfall chart
// ═══════════════════════════════════════════════════════════════════════════
function FinWaterfallPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    getFinancials()
      .then(r => setData(r.data))
      .catch(() => toast('Failed to load financial data', 'error'))
      .finally(() => setLoading(false))
  }, [toast])

  if (loading) return <div className="flex justify-center h-48"><Spinner className="w-8 h-8 text-emerald-500 mt-16"/></div>
  if (!data)   return null

  const inflow    = fP(data.total_collected_inr)
  const outflow   = fP(data.total_distributed_inr)
  const refOut    = fP(data.total_referrals_paid_inr)
  const mntFees   = fP(data.maintenance_fees_total_inr)
  const lateFees  = fP(data.total_late_fees_collected_inr)
  const graceFees = fP(data.total_grace_fees_collected_inr)
  const netProfit = fP(data.pure_realized_profit_inr)
  const liability = fP(data.current_active_liability_inr)

  // Build waterfall bars
  const bars = [
    { name: 'Deposits In',    value: inflow,    fill: C.emerald, type: 'income' },
    { name: 'Late Fees',      value: lateFees,  fill: C.amber,   type: 'income' },
    { name: 'Grace Fees',     value: graceFees, fill: C.teal,    type: 'income' },
    { name: 'Payouts Out',    value: outflow,   fill: C.rose,    type: 'expense' },
    { name: 'Referral Out',   value: refOut,    fill: C.violet,  type: 'expense' },
    { name: 'Platform Fees',  value: mntFees,   fill: C.blue,    type: 'fee' },
    { name: 'Active Liability',value: liability, fill: '#f97316', type: 'liability' },
    { name: 'Net Realized',   value: netProfit, fill: netProfit >= 0 ? C.emerald : C.rose, type: 'net' },
  ].map(b => ({ ...b, display: b.type === 'expense' || b.type === 'liability' ? -Math.abs(b.value) : b.value }))

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      <div>
        <h2 className="text-lg font-bold text-slate-800">Financial Cash Waterfall</h2>
        <p className="text-sm text-slate-400 mt-0.5">All-time financial flow — inflows, outflows, and net realized profit.</p>
      </div>

      <SectionCard title="Cash Flow Waterfall" icon={Calculator} iconColor="text-emerald-500">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={bars} margin={{top:8,right:16,left:8,bottom:40}}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
            <XAxis dataKey="name" tick={{fill:'#64748b',fontSize:10}} tickLine={false} angle={-35} textAnchor="end" interval={0}/>
            <YAxis tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false} tickFormatter={v=>INR_COMPACT(Math.abs(v))}/>
            <Tooltip formatter={(v,n)=>[INR(Math.abs(v)), n]} contentStyle={{border:'1px solid #e2e8f0',borderRadius:12,fontSize:12}}/>
            <ReferenceLine y={0} stroke="#94a3b8" />
            <Bar dataKey="display" name="Amount" radius={[4,4,0,0]}>
              {bars.map((b,i) => <Cell key={i} fill={b.fill} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* Summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label:'Total Inflow',      val:INR(inflow),                 color:'text-emerald-600', bg:'bg-emerald-50 border-emerald-200' },
          { label:'Total Outflow',     val:INR(outflow+refOut),         color:'text-red-600',     bg:'bg-red-50 border-red-200' },
          { label:'Compliance Rev',    val:INR(lateFees+graceFees),     color:'text-amber-600',   bg:'bg-amber-50 border-amber-200' },
          { label:'Net Realized',      val:INR(Math.abs(netProfit)),    color:netProfit>=0?'text-emerald-700':'text-red-700', bg:netProfit>=0?'bg-emerald-50 border-emerald-200':'bg-red-50 border-red-200' },
        ].map(c => (
          <div key={c.label} className={`rounded-2xl border p-4 ${c.bg}`}>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{c.label}</p>
            <p className={`text-xl font-black tabular-nums mt-1 ${c.color}`}>{c.val}</p>
          </div>
        ))}
      </div>
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// S-05: Brain 5 Forward Signal Panel — live LPI + L3→L4 projection
// ═══════════════════════════════════════════════════════════════════════════
function Brain5SignalPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)

  const fetch_ = useCallback(async () => {
    setLoading(true)
    try   { const r = await getBrain5Lpi(); setData(r.data) }
    catch { toast('Failed to load Brain 5 signal', 'error') }
    finally { setLoading(false) }
  }, [toast])
  useEffect(() => { fetch_(); const id=setInterval(fetch_,30_000); return()=>clearInterval(id) }, [fetch_])

  if (loading) return <div className="flex justify-center h-48"><Spinner className="w-8 h-8 text-violet-500 mt-16"/></div>
  if (!data)   return null

  const lpi       = fP(data.lpi)
  const fwd       = fP(data.forward_signal_l3)
  const dist      = data.level_distribution ?? {}
  const demand    = data.sde_demand ?? {}
  const decision  = data.pool_type_decision ?? {}

  const lpiColor  = lpi>=50?'text-red-600':lpi>=25?'text-orange-600':lpi>=14?'text-amber-600':'text-emerald-600'

  const distData = [1,2,3,4,5,6].map(l => ({
    level: `L${l}`,
    count: fI(dist[`l${l}`]??dist[`L${l}`]??0),
    fill:  ['#94a3b8','#3b82f6','#8b5cf6','#f59e0b','#f97316','#ef4444'][l-1],
  }))

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-800">Brain 5 — LPI &amp; Forward Signal</h2>
          <p className="text-sm text-slate-400 mt-0.5">Level Pressure Index with L3→L4 forward projection. Auto-refreshes every 30 s.</p>
        </div>
        <button onClick={fetch_} className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 transition">
          <RefreshCw className="w-4 h-4 text-slate-500"/>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* LPI Gauge */}
        <SectionCard title="Live LPI" icon={Cpu} iconColor="text-violet-500">
          <div className="flex flex-col items-center py-2">
            <LpiGauge lpi={lpi}/>
            <div className="mt-3 space-y-1 w-full">
              <ARow label="Decision" value={decision.summary ?? '—'} color={lpiColor}/>
              <ARow label="L4 Flagged" value={demand.l4_count??0} color={demand.l4_count>0?'text-red-600':'text-emerald-600'}/>
              <ARow label="SDE Sessions" value={demand.sessions_needed??0}/>
            </div>
          </div>
        </SectionCard>

        {/* Forward Signal */}
        <SectionCard title="Forward Signal (L3→L4)" icon={TrendingUp} iconColor="text-amber-500">
          <div className="flex flex-col items-center py-4">
            <p className={`text-5xl font-black tabular-nums ${fwd>=3?'text-red-600':fwd>=1?'text-amber-600':'text-emerald-600'}`}>{fwd}</p>
            <p className="text-xs text-slate-400 mt-1">Paid L3 members → next L4 after draw</p>
            <div className="mt-4 w-full space-y-1">
              <ARow label="L3→L4 Threshold" value={demand.l1l2_threshold??0}/>
              <ARow label="L1+L2 Available" value={demand.l1l2_available??0}/>
              <ARow label="Clearable L4s"   value={demand.clearable_count??0}/>
              {demand.overflow_count>0&&(
                <ARow label="SDE Overflow" value={demand.overflow_count} color="text-red-600"/>
              )}
            </div>
          </div>
        </SectionCard>

        {/* Level Distribution mini-chart */}
        <SectionCard title="Active Level Distribution" icon={BarChart3} iconColor="text-blue-500">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={distData} margin={{top:4,right:4,left:-20,bottom:4}}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
              <XAxis dataKey="level" tick={{fill:'#64748b',fontSize:11,fontWeight:700}} tickLine={false} axisLine={false}/>
              <YAxis tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false}/>
              <Tooltip formatter={(v,n)=>[v,n]} contentStyle={{border:'1px solid #e2e8f0',borderRadius:10,fontSize:11}}/>
              <Bar dataKey="count" name="Members" radius={[6,6,0,0]}>
                {distData.map((d,i) => <Cell key={i} fill={d.fill}/>)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </SectionCard>
      </div>

      {/* AI scenario from brain5 */}
      {data.elevated_risk && (
        <div className="flex items-center gap-3 p-4 bg-red-50 border border-red-200 rounded-2xl">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0"/>
          <div>
            <p className="text-sm font-bold text-red-700">Elevated Risk — L5/L6 Members Present</p>
            <p className="text-xs text-red-500 mt-0.5">SDE Extension II/III will trigger automatically at next draw. Admin attention recommended.</p>
          </div>
        </div>
      )}
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// S-06: SDE Event Timeline — history of SDE draws from draw_history
// ═══════════════════════════════════════════════════════════════════════════
function SdeTimelinePanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [weeks,   setWeeks]   = useState(24)

  const fetch_ = useCallback(async () => {
    setLoading(true)
    try   { const r = await getWeeklyPoolReports(weeks); setData(r.data) }
    catch { toast('Failed to load SDE timeline', 'error') }
    finally { setLoading(false) }
  }, [weeks, toast])
  useEffect(() => { fetch_() }, [fetch_])

  if (loading) return <div className="flex justify-center h-48"><Spinner className="w-8 h-8 text-rose-500 mt-16"/></div>
  if (!data?.weeks?.length) return <p className="text-slate-400 text-sm p-4">No draw history yet.</p>

  const timeline = data.weeks.map(w => ({
    week:    w.week_id,
    sde:     fI(w.total_sde_exits),
    regular: fI((w.draw_types?.regular??0)),
    type_a:  fI((w.draw_types?.type_a??0)),
    type_b:  fI((w.draw_types?.type_b??0)),
    winners: fI(w.winner_count),
    payout:  fP(w.total_payout_inr),
  }))

  const totalSde = timeline.reduce((s,w)=>s+w.sde,0)

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-800">SDE Event Timeline</h2>
          <p className="text-sm text-slate-400 mt-0.5">SDE (L4 forced-exit) draws vs normal draws per week.</p>
        </div>
        <div className="flex items-center gap-2">
          {[12, 24, 52].map(w => (
            <button key={w} onClick={() => setWeeks(w)}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition ${weeks===w?'bg-rose-600 text-white':'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}>
              {w}W
            </button>
          ))}
        </div>
      </div>

      {/* SDE vs normal draw chart */}
      <SectionCard title="Draw Type Breakdown Per Week" icon={Zap} iconColor="text-rose-500">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={timeline} margin={{top:4,right:16,left:0,bottom:4}}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
            <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
            <YAxis tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false}/>
            <Tooltip contentStyle={{border:'1px solid #e2e8f0',borderRadius:12,fontSize:11}}/>
            <Legend wrapperStyle={{fontSize:11}}/>
            <Bar dataKey="regular" stackId="a" fill={C.emerald} name="Regular"  radius={[0,0,0,0]}/>
            <Bar dataKey="type_a"  stackId="a" fill={C.blue}    name="Type A"   radius={[0,0,0,0]}/>
            <Bar dataKey="type_b"  stackId="a" fill={C.amber}   name="Type B"   radius={[0,0,0,0]}/>
            <Bar dataKey="sde"     stackId="a" fill={C.rose}    name="SDE Exit" radius={[4,4,0,0]}/>
          </BarChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* SDE summary */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">SDE Exits</p>
          <p className="text-3xl font-black tabular-nums mt-1 text-rose-600">{NUM(totalSde)}</p>
          <p className="text-xs text-rose-400 mt-0.5">L4 forced exits in {weeks}W</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Draws</p>
          <p className="text-3xl font-black tabular-nums mt-1 text-slate-800">{NUM(timeline.reduce((s,w)=>s+w.regular+w.type_a+w.type_b+w.sde,0))}</p>
        </div>
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Winners</p>
          <p className="text-3xl font-black tabular-nums mt-1 text-emerald-600">{NUM(timeline.reduce((s,w)=>s+w.winners,0))}</p>
        </div>
      </div>
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// S-08: Alert Thresholds Panel — live system health + configurable alerts
// ═══════════════════════════════════════════════════════════════════════════
function AlertThreshPanel({ toast }) {
  const [health,   setHealth]   = useState(null)
  const [lpi5,     setLpi5]     = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [lastUp,   setLastUp]   = useState(null)

  const fetch_ = useCallback(async () => {
    try {
      const [hRes, lRes] = await Promise.all([
        devLiveStats().catch(()=>null),
        getBrain5Lpi().catch(()=>null),
      ])
      if (hRes) setHealth(hRes.data)
      if (lRes) setLpi5(lRes.data)
      setLastUp(new Date())
    } catch { toast('Failed to load system health', 'error') }
    finally { setLoading(false) }
  }, [toast])

  useEffect(() => {
    fetch_()
    const id = setInterval(fetch_, 30_000)
    return () => clearInterval(id)
  }, [fetch_])

  if (loading) return <div className="flex justify-center h-48"><Spinner className="w-8 h-8 text-slate-500 mt-16"/></div>

  const lpi         = fP(lpi5?.lpi ?? health?.sde?.lpi ?? 0)
  const l4Flagged   = fI(lpi5?.sde_demand?.l4_count ?? health?.sde?.l4_flagged ?? 0)
  const activeUsers = fI(health?.users?.active ?? 0)
  const waitlist    = fI(health?.users?.waitlist ?? 0)
  const activePools = fI(health?.pools?.active ?? 0)

  // Threshold matrix
  const checks = [
    {
      label:    'LPI Level',
      value:    `${lpi.toFixed(1)}%`,
      status:   lpi>=50?'critical':lpi>=25?'warning':lpi>=14?'caution':'healthy',
      note:     lpi>=50?'CRITICAL — SDE Extended immediately required':lpi>=25?'SDE proactive draw scheduled':lpi>=14?'Type A routing active':'System in healthy zone',
    },
    {
      label:    'L4 Flagged Members',
      value:    l4Flagged,
      status:   l4Flagged>=6?'critical':l4Flagged>=3?'warning':l4Flagged>=1?'caution':'healthy',
      note:     l4Flagged>=6?'High SDE demand — admin override likely required':l4Flagged>=3?'Multiple SDE sessions needed':l4Flagged>=1?'SDE sessions planned':'No L4 pressure',
    },
    {
      label:    'Active Users',
      value:    activeUsers,
      status:   activeUsers<12?'critical':activeUsers<24?'warning':'healthy',
      note:     activeUsers<12?'Below minimum for 1 pool — system at risk':activeUsers<24?'Low active count':'Active count healthy',
    },
    {
      label:    'Waitlist Queue',
      value:    waitlist,
      status:   waitlist<12?'warning':waitlist>=100?'caution':'healthy',
      note:     waitlist<12?'Insufficient waitlist for pool refill':waitlist>=100?'Large waitlist — consider threshold adjustment':'Waitlist depth healthy',
    },
    {
      label:    'Active Pools',
      value:    activePools,
      status:   activePools===0?'critical':activePools===1?'caution':'healthy',
      note:     activePools===0?'NO ACTIVE POOLS — system halted':activePools===1?'Single pool — condensation risk':'Multiple pools operational',
    },
    {
      label:    'AI Scenario',
      value:    health?.ai?.scenario?.replace(/_/g,' ') ?? '—',
      status:   ['DRY_PHASE','VELOCITY_CLIFF'].includes(health?.ai?.scenario)?'warning':'healthy',
      note:     ['DRY_PHASE','VELOCITY_CLIFF'].includes(health?.ai?.scenario)?'Momentum concern — monitor inflow closely':'AI scenario within normal operating range',
    },
  ]

  const STATUS_CFG = {
    critical: { bg:'bg-red-50 border-red-200',    label:'bg-red-600 text-white',    dot:'bg-red-500',    text:'text-red-700'    },
    warning:  { bg:'bg-amber-50 border-amber-200', label:'bg-amber-600 text-white',  dot:'bg-amber-500',  text:'text-amber-700'  },
    caution:  { bg:'bg-yellow-50 border-yellow-200',label:'bg-yellow-500 text-white',dot:'bg-yellow-500', text:'text-yellow-700' },
    healthy:  { bg:'bg-emerald-50 border-emerald-200',label:'bg-emerald-600 text-white',dot:'bg-emerald-500',text:'text-emerald-700'},
  }

  const criticals = checks.filter(c=>c.status==='critical').length
  const warnings  = checks.filter(c=>c.status==='warning').length

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-800">System Alert Thresholds</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Live health checks against all critical system boundaries.
            {lastUp && ` · Updated ${lastUp.toLocaleTimeString()}`}
          </p>
        </div>
        <button onClick={fetch_} className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 transition">
          <RefreshCw className="w-4 h-4 text-slate-500"/>
        </button>
      </div>

      {/* Overall status banner */}
      {criticals > 0 && (
        <div className="flex items-center gap-3 p-4 bg-red-50 border border-red-200 rounded-2xl">
          <XCircle className="w-5 h-5 text-red-500 flex-shrink-0"/>
          <p className="text-sm font-bold text-red-700">
            {criticals} critical alert{criticals!==1?'s':''} — immediate action required.
          </p>
        </div>
      )}
      {criticals === 0 && warnings > 0 && (
        <div className="flex items-center gap-3 p-4 bg-amber-50 border border-amber-200 rounded-2xl">
          <AlertTriangle className="w-5 h-5 text-amber-500 flex-shrink-0"/>
          <p className="text-sm font-semibold text-amber-700">
            {warnings} warning{warnings!==1?'s':''} — monitor closely.
          </p>
        </div>
      )}
      {criticals === 0 && warnings === 0 && (
        <div className="flex items-center gap-3 p-4 bg-emerald-50 border border-emerald-200 rounded-2xl">
          <CheckCircle2 className="w-5 h-5 text-emerald-500 flex-shrink-0"/>
          <p className="text-sm font-semibold text-emerald-700">All systems healthy — no alerts active.</p>
        </div>
      )}

      {/* Alert cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {checks.map(c => {
          const cfg = STATUS_CFG[c.status]
          return (
            <div key={c.label} className={`rounded-2xl border p-4 ${cfg.bg}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold text-slate-600 uppercase tracking-wider">{c.label}</span>
                <span className={`text-[10px] font-black px-2 py-0.5 rounded-full uppercase tracking-wider ${cfg.label}`}>
                  {c.status}
                </span>
              </div>
              <p className={`text-2xl font-black tabular-nums ${cfg.text}`}>{c.value}</p>
              <p className="text-xs text-slate-500 mt-1">{c.note}</p>
            </div>
          )
        })}
      </div>
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// S-03: Winner Level Distribution Trend — per-week winner level stacked chart
// ═══════════════════════════════════════════════════════════════════════════
function WinnerTrendPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [window_, setWindow_] = useState(24)   // 12W / 24W / 52W

  const fetch_ = useCallback(async (w) => {
    setLoading(true)
    try {
      const r = await getWinnerLevelTrend(w)
      setData(r.data)
    } catch { toast('Failed to load winner trend', 'error') }
    finally { setLoading(false) }
  }, [toast])

  useEffect(() => { fetch_(window_) }, [fetch_, window_])

  // Level colour map — matches production Brain 5 visual language
  const LEVEL_COLORS = {
    L1: C.emerald, L2: C.teal, L3: C.blue,
    L4: C.amber,   L5: '#f97316', L6: C.rose,
  }

  if (loading) return (
    <div className="flex justify-center h-48">
      <Spinner className="w-8 h-8 text-slate-500 mt-16" />
    </div>
  )
  if (!data) return null

  const rows      = data.weeks ?? []
  const summary   = data.summary ?? {}
  const chartData = rows.map(r => ({
    week: r.week_id.slice(-3),
    ...r.levels,
    total: r.total_winners,
  }))

  const domLvl   = summary.dominant_level ?? 'L1'
  const domColor = LEVEL_COLORS[domLvl] ?? C.slate

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-800">Winner Level Distribution Trend</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Which levels are winning most often over time — a leading indicator of SDE pressure.
          </p>
        </div>
        <div className="flex gap-2">
          {[12, 24, 52].map(w => (
            <button key={w} onClick={() => setWindow_(w)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition border ${
                window_===w
                  ? 'bg-slate-800 border-slate-700 text-white'
                  : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
              }`}>
              {w}W
            </button>
          ))}
          <button onClick={() => fetch_(window_)} className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 transition">
            <RefreshCw className="w-4 h-4 text-slate-500" />
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          {
            label: 'Dominant Level',
            value: domLvl,
            color: `text-[${domColor}]`,
            note: `${summary.level_totals?.[domLvl] ?? 0} wins`,
          },
          { label: 'Total Winners',  value: NUM(summary.total_winners ?? 0), color: 'text-slate-800', note: `${window_}W window` },
          { label: 'Total Draws',    value: NUM(summary.total_draws   ?? 0), color: 'text-blue-700',  note: '2 winners/draw'   },
          {
            label: 'Weeks with Data',
            value: rows.filter(r => r.total_winners > 0).length,
            color: 'text-slate-600',
            note: `of ${rows.length} weeks`,
          },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100">
            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1.5">{c.label}</p>
            <p className={`text-2xl font-black tabular-nums ${c.color}`} style={
              c.label === 'Dominant Level' ? { color: domColor } : {}
            }>{c.value}</p>
            <p className="text-xs text-slate-400 mt-1">{c.note}</p>
          </div>
        ))}
      </div>

      {/* Level pct of total breakdown */}
      {summary.level_totals && summary.total_winners > 0 && (
        <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">Level Share of All Wins</p>
          <div className="space-y-2">
            {Object.entries(summary.level_totals).map(([lvl, cnt]) => {
              const pct = summary.total_winners ? (cnt / summary.total_winners * 100) : 0
              return (
                <div key={lvl} className="flex items-center gap-3">
                  <span className="text-xs font-bold text-slate-500 w-5">{lvl}</span>
                  <div className="flex-1 bg-slate-100 rounded-full h-2.5 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{ width: `${pct}%`, backgroundColor: LEVEL_COLORS[lvl] }}
                    />
                  </div>
                  <span className="text-xs text-slate-600 tabular-nums w-14 text-right">
                    {NUM(cnt)} ({pct.toFixed(1)}%)
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Stacked bar chart */}
      {chartData.length > 0 ? (
        <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">
            Winners per Level per Week
          </p>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="week" tick={{ fontSize: 10, fill: '#94a3b8' }} interval="preserveStartEnd" />
              <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: '#94a3b8' }} />
              <Tooltip
                contentStyle={{ borderRadius: '12px', border: '1px solid #e2e8f0', fontSize: 12 }}
                cursor={{ fill: '#f8fafc' }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {['L1','L2','L3','L4','L5','L6'].map(lvl => (
                <Bar key={lvl} dataKey={lvl} stackId="a" fill={LEVEL_COLORS[lvl]} name={lvl} />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <p className="text-[10px] text-slate-400 text-center mt-2">
            Week labels = ISO week number. L4+ wins in the stack indicate growing SDE pressure.
          </p>
        </div>
      ) : (
        <div className="bg-slate-50 rounded-2xl border border-slate-200 p-12 text-center">
          <Award className="w-8 h-8 text-slate-300 mx-auto mb-3" />
          <p className="text-sm text-slate-400">No draw history found in the selected window.</p>
        </div>
      )}
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// S-04: Referral Quality Heatmap — weekly RDR% GitHub-style calendar
// ═══════════════════════════════════════════════════════════════════════════
function ReferralHeatmapPanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [window_, setWindow_] = useState(52)
  const [hovered, setHovered] = useState(null)   // hovered week cell

  const fetch_ = useCallback(async (w) => {
    setLoading(true)
    try {
      const r = await getReferralTrend(w)
      setData(r.data)
    } catch { toast('Failed to load referral trend', 'error') }
    finally { setLoading(false) }
  }, [toast])

  useEffect(() => { fetch_(window_) }, [fetch_, window_])

  /** Map RDR% → heatmap cell background colour (teal scale) */
  const rdrToColor = (rdr) => {
    if (rdr === 0)   return '#f1f5f9'   // slate-100 — no data or organic-only
    if (rdr < 20)    return '#ccfbf1'   // teal-100
    if (rdr < 40)    return '#5eead4'   // teal-300
    if (rdr < 60)    return '#0d9488'   // teal-600
    if (rdr < 80)    return '#0f766e'   // teal-700
    return           '#134e4a'          // teal-900 — very high referral
  }

  if (loading) return (
    <div className="flex justify-center h-48">
      <Spinner className="w-8 h-8 text-teal-500 mt-16" />
    </div>
  )
  if (!data) return null

  const weeks   = data.weeks   ?? []
  const summary = data.summary ?? {}

  // Split weeks into rows of 13 (quarterly display)
  const COLS = 13
  const rows  = []
  for (let i = 0; i < weeks.length; i += COLS) {
    rows.push(weeks.slice(i, i + COLS))
  }

  // Trend line for LineChart
  const chartData = weeks.map(w => ({
    week:     w.week_id.slice(-3),
    rdr_pct:  w.rdr_pct,
    total:    w.total_joins,
    referral: w.referral_joins,
  }))

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-800">Referral Quality Heatmap</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Weekly Referral Density Ratio (RDR%) — darker teal = higher referral share that week.
          </p>
        </div>
        <div className="flex gap-2">
          {[26, 52, 104].map(w => (
            <button key={w} onClick={() => setWindow_(w)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition border ${
                window_===w
                  ? 'bg-teal-700 border-teal-600 text-white'
                  : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
              }`}>
              {w <= 52 ? `${w}W` : `${w/52}Y`}
            </button>
          ))}
          <button onClick={() => fetch_(window_)} className="p-2 rounded-xl bg-slate-100 hover:bg-slate-200 transition">
            <RefreshCw className="w-4 h-4 text-slate-500" />
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Avg RDR%',        value: `${(summary.avg_rdr_pct ?? 0).toFixed(1)}%`,
            color: 'text-teal-700', note: 'across window' },
          { label: 'Peak RDR%',       value: `${(summary.peak_rdr_pct ?? 0).toFixed(1)}%`,
            color: 'text-teal-900', note: summary.peak_rdr_week ?? '—' },
          { label: 'Total Joins',     value: NUM(summary.total_joins_in_window ?? 0),
            color: 'text-slate-800', note: 'all users' },
          { label: 'Referral Joins',  value: NUM(summary.referral_joins_in_window ?? 0),
            color: 'text-blue-700',  note: `${(summary.avg_rdr_pct ?? 0).toFixed(1)}% of total` },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100">
            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1.5">{c.label}</p>
            <p className={`text-2xl font-black tabular-nums ${c.color}`}>{c.value}</p>
            <p className="text-xs text-slate-400 mt-1">{c.note}</p>
          </div>
        ))}
      </div>

      {/* Heatmap calendar */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Weekly RDR% Heatmap
          </p>
          {/* Legend */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-slate-400 mr-1">Organic</span>
            {['#f1f5f9','#ccfbf1','#5eead4','#0d9488','#0f766e','#134e4a'].map(c => (
              <div key={c} className="w-4 h-4 rounded-sm" style={{ backgroundColor: c }} />
            ))}
            <span className="text-[10px] text-slate-400 ml-1">Referral</span>
          </div>
        </div>

        {weeks.length === 0 ? (
          <div className="text-center py-8">
            <GitFork className="w-8 h-8 text-slate-300 mx-auto mb-3" />
            <p className="text-sm text-slate-400">No join data found in the selected window.</p>
          </div>
        ) : (
          <div className="space-y-1.5 overflow-x-auto">
            {rows.map((row, ri) => (
              <div key={ri} className="flex gap-1.5">
                {row.map(wk => (
                  <div
                    key={wk.week_id}
                    onMouseEnter={() => setHovered(wk)}
                    onMouseLeave={() => setHovered(null)}
                    className="relative flex-shrink-0 w-9 h-9 rounded-lg flex flex-col items-center justify-center cursor-pointer
                               transition-transform hover:scale-110 border border-white/20"
                    style={{ backgroundColor: rdrToColor(wk.rdr_pct) }}
                    title={`${wk.week_id}: ${wk.rdr_pct}% RDR — ${wk.referral_joins}/${wk.total_joins} joins`}
                  >
                    <span className="text-[9px] font-bold leading-none"
                          style={{ color: wk.rdr_pct >= 40 ? '#f0fdfa' : '#475569' }}>
                      {wk.week_id.slice(-2)}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {/* Tooltip detail */}
        {hovered && (
          <div className="mt-4 p-3 bg-teal-50 border border-teal-200 rounded-xl text-xs text-teal-800 flex gap-4">
            <span className="font-bold">{hovered.week_id}</span>
            <span>📅 w/c {hovered.week_start}</span>
            <span>🔗 {hovered.referral_joins} referral joins</span>
            <span>👤 {hovered.total_joins} total</span>
            <span className="font-bold text-teal-900">RDR = {hovered.rdr_pct}%</span>
          </div>
        )}
      </div>

      {/* RDR trend line chart */}
      {chartData.length > 0 && (
        <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">
            RDR% Over Time
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="week" tick={{ fontSize: 10, fill: '#94a3b8' }} interval="preserveStartEnd" />
              <YAxis yAxisId="pct" domain={[0, 100]} tickFormatter={v => `${v}%`}
                     tick={{ fontSize: 10, fill: '#0d9488' }} />
              <YAxis yAxisId="cnt" orientation="right" tick={{ fontSize: 10, fill: '#94a3b8' }} />
              <Tooltip
                contentStyle={{ borderRadius: '12px', border: '1px solid #e2e8f0', fontSize: 12 }}
                formatter={(val, name) =>
                  name === 'rdr_pct' ? [`${Number(val).toFixed(1)}%`, 'RDR%'] :
                  name === 'total'   ? [NUM(val), 'Total Joins'] :
                                      [NUM(val), 'Referral Joins']
                }
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="cnt" dataKey="total"    fill="#f1f5f9"  name="Total Joins"    />
              <Bar yAxisId="cnt" dataKey="referral" fill="#5eead4"  name="Referral Joins" />
              <Line yAxisId="pct" type="monotone" dataKey="rdr_pct"
                    stroke="#0d9488" strokeWidth={2.5} dot={false} name="RDR%" />
              <ReferenceLine yAxisId="pct" y={30} stroke="#f59e0b" strokeDasharray="4 4"
                             label={{ value: '30% healthy', position: 'right', fontSize: 10, fill: '#f59e0b' }} />
              <ReferenceLine yAxisId="pct" y={60} stroke="#ef4444" strokeDasharray="4 4"
                             label={{ value: '60% high', position: 'right', fontSize: 10, fill: '#ef4444' }} />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="text-[10px] text-slate-400 text-center mt-2">
            RDR% between 30–60% indicates healthy organic/referral balance. Above 60% risks FLASH_FLOOD scenario.
          </p>
        </div>
      )}
    </motion.div>
  )
}


// ── System Pauses panel ──────────────────────────────────────────────────────
function PausesPanel({ toast }) {
  const [data,        setData]        = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [selectedDay, setSelectedDay] = useState(null)

  const fetch_ = useCallback(async () => {
    setLoading(true)
    try   { const r = await getPauseCalendar(); setData(r.data) }
    catch { toast('Failed to load pause calendar', 'error') }
    finally { setLoading(false) }
  }, [toast])
  useEffect(() => { fetch_() }, [fetch_])

  if (loading) return (
    <div className="flex items-center justify-center h-48">
      <Spinner className="w-8 h-8 text-amber-500" />
    </div>
  )
  if (!data) return null

  // ── Calendar grid helpers ────────────────────────────────────────────────
  const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun',
                       'Jul','Aug','Sep','Oct','Nov','Dec']

  /** YYYY-MM-DD without timezone drift */
  const toDateStr = d =>
    `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`

  const addDays = (d, n) => { const c = new Date(d); c.setDate(c.getDate() + n); return c }

  const today    = new Date()
  const todayStr = toDateStr(today)
  const cutoff   = toDateStr(addDays(today, -90))   // oldest date to colour

  // Align the calendar start to the Monday of the week containing (today − 90d)
  const rawStart  = addDays(today, -90)
  const dow       = rawStart.getDay()               // 0 = Sun
  const backToMon = dow === 0 ? 6 : dow - 1
  const startDate = addDays(rawStart, -backToMon)

  // Build lookup map from API response
  const pauseMap = {}
  for (const entry of data.calendar) pauseMap[entry.date] = entry

  // Build week rows
  const weeks = []
  let cur = new Date(startDate)
  while (toDateStr(cur) <= todayStr) {
    const week = []
    for (let d = 0; d < 7; d++) {
      const ds = toDateStr(cur)
      week.push({
        date:    ds,
        dayNum:  cur.getDate(),
        month:   cur.getMonth(),
        inRange: ds >= cutoff && ds <= todayStr,
        isToday: ds === todayStr,
        data:    pauseMap[ds] || null,
      })
      cur = addDays(cur, 1)
    }
    weeks.push(week)
  }

  const cellCls = day => {
    if (!day.inRange) return 'bg-transparent border-transparent cursor-default'
    const c = day.data?.paused_count ?? 0
    if (c >= 3) return 'bg-rose-200 border-rose-300 cursor-pointer hover:bg-rose-300'
    if (c >= 1) return 'bg-amber-200 border-amber-300 cursor-pointer hover:bg-amber-300'
    return 'bg-slate-100 border-slate-200 cursor-default'
  }

  const textCls = day => {
    if (!day.inRange) return 'text-transparent'
    const c = day.data?.paused_count ?? 0
    if (c >= 3) return 'text-rose-800 font-semibold'
    if (c >= 1) return 'text-amber-800 font-semibold'
    return 'text-slate-400'
  }

  return (
    <div className="space-y-5">

      {/* ── KPI strip ──────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-4">
        {[
          {
            label: 'Currently Paused',
            value: data.current_paused_count,
            color: data.current_paused_count > 0 ? 'text-amber-600' : 'text-slate-400',
          },
          { label: 'Pause Events (90 d)', value: data.total_pause_events,  color: 'text-slate-700' },
          { label: 'Days with Activity',  value: data.calendar.length,      color: 'text-slate-700' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100 text-center">
            <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-1">{label}</p>
            <p className={`text-2xl font-black tabular-nums ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* ── Heatmap card ───────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
          <Clock className="w-4 h-4 text-amber-500" />
          <h3 className="font-semibold text-slate-800 text-sm">
            Pause Heatmap — Last 90 Days
          </h3>
          <button
            onClick={fetch_}
            className="ml-auto flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 rounded-xl text-xs text-slate-500 hover:bg-slate-50 transition"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>

        <div className="p-6 overflow-x-auto">
          {/* Day-of-week headers */}
          <div className="flex gap-1 mb-2 min-w-[480px]">
            <div className="w-9 flex-shrink-0" /> {/* month-label spacer */}
            {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d => (
              <div key={d}
                className="flex-1 text-center text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
                {d}
              </div>
            ))}
          </div>

          {/* Week rows */}
          <div className="space-y-1 min-w-[480px]">
            {weeks.map((week, wi) => {
              const showMonth = wi === 0 || week[0].month !== weeks[wi - 1][0].month
              return (
                <div key={wi} className="flex gap-1 items-center">
                  {/* Month label */}
                  <div className="w-9 flex-shrink-0 text-right pr-1.5">
                    {showMonth && (
                      <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">
                        {MONTH_NAMES[week[0].month]}
                      </span>
                    )}
                  </div>
                  {/* Day cells */}
                  {week.map(day => (
                    <button
                      key={day.date}
                      onClick={() => {
                        if (!day.data || !day.inRange) return
                        setSelectedDay(p => p?.date === day.date ? null : day)
                      }}
                      title={
                        day.inRange
                          ? day.data
                            ? `${day.data.paused_count} pool(s) — click for details`
                            : 'No pause activity'
                          : undefined
                      }
                      className={`flex-1 h-9 rounded-lg border text-xs transition-all select-none
                        ${cellCls(day)}
                        ${selectedDay?.date === day.date
                          ? 'ring-2 ring-violet-500 ring-offset-1'
                          : ''}
                        ${day.isToday ? 'ring-2 ring-violet-400 ring-offset-0' : ''}
                      `}
                    >
                      <span className={textCls(day)}>{day.inRange ? day.dayNum : ''}</span>
                    </button>
                  ))}
                </div>
              )
            })}
          </div>

          {/* Legend */}
          <div className="mt-5 flex flex-wrap items-center gap-4 text-[11px] text-slate-500">
            <span className="font-semibold text-slate-400">Legend</span>
            {[
              { cls: 'bg-slate-100 border-slate-200',  label: 'No pauses' },
              { cls: 'bg-amber-200 border-amber-300',  label: '1–2 pools' },
              { cls: 'bg-rose-200 border-rose-300',    label: '3+ pools'  },
            ].map(({ cls, label }) => (
              <div key={label} className="flex items-center gap-1.5">
                <span className={`w-5 h-5 rounded border ${cls} inline-block flex-shrink-0`} />
                <span>{label}</span>
              </div>
            ))}
            <span className="ml-auto text-[10px] text-slate-300">
              Click a highlighted cell to see which pools were paused
            </span>
          </div>
        </div>
      </div>

      {/* ── Selected-day detail ─────────────────────────────────────────────── */}
      {selectedDay?.data && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-500" />
            <h3 className="font-semibold text-slate-800 text-sm">
              {new Date(`${selectedDay.date}T12:00:00`).toLocaleDateString('en-IN', {
                weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
              })}
            </h3>
            <button
              onClick={() => setSelectedDay(null)}
              className="ml-auto text-slate-400 hover:text-slate-600 transition"
              title="Close"
            >
              <XCircle className="w-4 h-4" />
            </button>
          </div>
          <div className="p-5 space-y-1.5">
            {selectedDay.data.pools.map(pool => (
              <div key={pool.id}
                className="flex items-center gap-3 py-2.5 border-b border-slate-50 last:border-0">
                <span className="w-8 h-8 rounded-xl bg-amber-50 border border-amber-200 text-amber-700 flex items-center justify-center text-[10px] font-bold flex-shrink-0 tabular-nums">
                  #{pool.id}
                </span>
                <p className="font-semibold text-slate-800 text-sm">{pool.name}</p>
              </div>
            ))}
            <p className="pt-2 text-[11px] text-slate-400 leading-relaxed">
              {selectedDay.data.source === 'current'
                ? 'These pools are currently in Paused_Awaiting_Members status.'
                : 'Inferred from draw records: winners in these pools had experienced pauses during their journey. Exact pause date is not stored — the draw date is used as a proxy.'}
            </p>
          </div>
        </div>
      )}

      {/* ── Empty state ─────────────────────────────────────────────────────── */}
      {data.calendar.length === 0 && (
        <div className="flex items-start gap-3 bg-emerald-50 border border-emerald-200 rounded-xl p-4">
          <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-emerald-700">
            No system pauses detected in the last 90 days — all pools have been
            running without interruption.
          </p>
        </div>
      )}
    </div>
  )
}

// Token row (shared by both WIT and REF action panels)
function PendingTokenRow({ token, children }) {
  return (
    <div className="px-5 py-3.5 flex items-center gap-3 border-b last:border-0 border-slate-50">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono font-semibold text-sm text-slate-700">{token.code}</span>
          <span className="text-xs text-slate-300">·</span>
          <span className="font-bold text-sm text-slate-900 tabular-nums">{INR(token.value_inr)}</span>
        </div>
        <p className="text-[11px] text-slate-400 mt-0.5 truncate">
          @{token.user_username ?? '—'} &nbsp;·&nbsp; {token.user_name ?? 'Unknown user'}
        </p>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">{children}</div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Weekly Pool Reports panel (A-7 Statistics sub-tab)
// ─────────────────────────────────────────────────────────────────────────────

const INR_W = v => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(v??0)

function downloadCSVStats(rows, filename) {
  if (!rows?.length) return
  const headers = Object.keys(rows[0])
  const lines   = [
    headers.join(','),
    ...rows.map(r => headers.map(h => {
      const v = r[h]
      if (v == null) return ''
      const s = typeof v === 'object' ? JSON.stringify(v) : String(v)
      return s.includes(',') ? `"${s.replace(/"/g,'""')}"` : s
    }).join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a'); a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function WeeklyPoolReportsPanel({ toast }) {
  const [data,     setData]     = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [weeks,    setWeeks]    = useState(24)
  const [viewTab,  setViewTab]  = useState('table')  // 'table' | 'draws' | 'payouts' | 'levels'

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getWeeklyPoolReports(weeks)
      setData(res.data)
    } catch {
      toast('Failed to load weekly pool reports', 'error')
    } finally {
      setLoading(false)
    }
  }, [weeks]) // eslint-disable-line

  useEffect(() => { load() }, [load])

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <div className="w-8 h-8 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
    </div>
  )

  const rows = data?.weeks ?? []
  const snap = data?.snapshot ?? {}

  // Flatten rows for CSV (convert nested objects)
  const flatRows = rows.map(r => ({
    week_id:          r.week_id,
    week_start:       r.week_start,
    draw_count:       r.draw_count,
    pool_count:       r.pool_count,
    winner_count:     r.winner_count,
    total_payout_inr: r.total_payout_inr,
    avg_payout_inr:   r.avg_payout_inr,
    total_deposits_inr: r.total_deposits_inr,
    sde_exits:        r.total_sde_exits,
    type_regular:     r.draw_types?.regular ?? 0,
    type_a:           r.draw_types?.type_a  ?? 0,
    type_b:           r.draw_types?.type_b  ?? 0,
    type_sde:         r.draw_types?.sde     ?? 0,
    L1_winners:       r.winner_levels?.L1   ?? 0,
    L2_winners:       r.winner_levels?.L2   ?? 0,
    L3_winners:       r.winner_levels?.L3   ?? 0,
    L4_winners:       r.winner_levels?.L4   ?? 0,
    L5_winners:       r.winner_levels?.L5   ?? 0,
    L6_winners:       r.winner_levels?.L6   ?? 0,
  }))

  // Chart data
  const chartDraws   = rows.map(r => ({ week: r.week_id.slice(-3), ...r.draw_types }))
  const chartPayouts = rows.map(r => ({ week: r.week_id.slice(-3), total_payout: r.total_payout_inr, deposits: r.total_deposits_inr }))
  const chartLevels  = rows.map(r => ({ week: r.week_id.slice(-3), ...Object.fromEntries(Object.entries(r.winner_levels ?? {}).map(([k,v]) => [k,v])) }))

  const VIEW_TABS = [
    { id: 'table',  label: 'Table',       icon: TableProperties },
    { id: 'draws',  label: 'Draw Types',  icon: Gavel           },
    { id: 'payouts',label: 'Payouts',     icon: DollarSign      },
    { id: 'levels', label: 'Win Levels',  icon: Trophy          },
  ]

  const LEVEL_COLORS = { L1:'#64748b', L2:'#3b82f6', L3:'#8b5cf6', L4:'#f59e0b', L5:'#ef4444', L6:'#bf00ff' }

  return (
    <div className="space-y-5">
      {/* Summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label:'Active Users',   value: snap.active_users?.toLocaleString('en-IN') ?? '—',   icon: Users,       cls:'text-emerald-700 bg-emerald-50' },
          { label:'Waitlist',       value: snap.waitlist_count?.toLocaleString('en-IN') ?? '—', icon: Clock,       cls:'text-amber-700 bg-amber-50'     },
          { label:'Active Pools',   value: snap.active_pools?.toLocaleString('en-IN') ?? '—',   icon: Layers,      cls:'text-violet-700 bg-violet-50'   },
          { label:'Total Draws',    value: snap.total_draws?.toLocaleString('en-IN') ?? '—',    icon: Gavel,       cls:'text-blue-700 bg-blue-50'       },
        ].map(({ label, value, icon: Icon, cls }) => (
          <div key={label} className="bg-white border border-slate-100 rounded-xl px-4 py-3 flex items-center gap-3 shadow-sm">
            <div className={`p-2 rounded-lg ${cls.split(' ')[1]}`}><Icon className={`w-4 h-4 ${cls.split(' ')[0]}`} /></div>
            <div>
              <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">{label}</p>
              <p className="text-lg font-black text-slate-800 tabular-nums">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Controls row */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <label className="text-sm text-slate-600 font-medium">Show last</label>
          <select value={weeks} onChange={e => setWeeks(+e.target.value)}
            className="border border-slate-200 rounded-xl px-3 py-1.5 text-sm text-slate-700 bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-violet-400">
            {[8,12,24,36,52,104].map(w => <option key={w} value={w}>{w} weeks{w===52?' (1 yr)':w===104?' (2 yr)':''}</option>)}
          </select>
          <button onClick={load} className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm transition">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>
        <button onClick={() => downloadCSVStats(flatRows, `weekly_pool_reports_${Date.now()}.csv`)}
          className="flex items-center gap-1.5 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold shadow-sm transition">
          <Download className="w-3.5 h-3.5" /> Export CSV
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="bg-white border border-slate-100 rounded-2xl py-16 text-center">
          <CalendarRange className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <p className="text-slate-500 font-medium">No draw data yet</p>
          <p className="text-xs text-slate-400 mt-1">Run your first draw to see weekly reports here</p>
        </div>
      ) : (
        <div className="bg-white border border-slate-100 rounded-2xl shadow-sm overflow-hidden">
          {/* View tabs */}
          <div className="flex border-b border-slate-100 overflow-x-auto">
            {VIEW_TABS.map(t => (
              <button key={t.id} onClick={() => setViewTab(t.id)}
                className={`flex items-center gap-1.5 px-5 py-3.5 text-sm font-semibold border-b-2 transition whitespace-nowrap ${
                  viewTab === t.id
                    ? 'border-violet-600 text-violet-700 bg-violet-50/40 -mb-px'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}>
                <t.icon className="w-3.5 h-3.5" />
                {t.label}
              </button>
            ))}
            <div className="ml-auto px-4 py-3 text-xs text-slate-400 self-center whitespace-nowrap">
              {rows.length} weeks
            </div>
          </div>

          {/* ── TABLE view ── */}
          {viewTab === 'table' && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[900px]">
                <thead className="bg-slate-50 border-b border-slate-100">
                  <tr>
                    {['Week', 'Start Date', 'Draws', 'Pools', 'Winners', 'Total Payout', 'Avg Payout', 'SDE Exits', 'Types (R/A/B/S)'].map(h => (
                      <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {[...rows].reverse().map((r, i) => (
                    <tr key={r.week_id} className={`hover:bg-violet-50/30 transition-colors ${i === 0 ? 'bg-violet-50/20' : ''}`}>
                      <td className="px-4 py-3 font-mono font-bold text-violet-700 text-xs">{r.week_id}</td>
                      <td className="px-4 py-3 text-xs text-slate-500">{r.week_start}</td>
                      <td className="px-4 py-3 font-semibold text-slate-800">{r.draw_count}</td>
                      <td className="px-4 py-3 text-slate-600">{r.pool_count}</td>
                      <td className="px-4 py-3 font-semibold text-slate-800">{r.winner_count}</td>
                      <td className="px-4 py-3 font-mono font-bold text-emerald-700">{INR_W(r.total_payout_inr)}</td>
                      <td className="px-4 py-3 text-slate-500">{INR_W(r.avg_payout_inr)}</td>
                      <td className="px-4 py-3">
                        {r.total_sde_exits > 0
                          ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-100 text-red-700 border border-red-200">{r.total_sde_exits} SDE</span>
                          : <span className="text-slate-300 text-xs">—</span>}
                      </td>
                      <td className="px-4 py-3 font-mono text-[11px] text-slate-500">
                        <span className="text-emerald-600">{r.draw_types?.regular ?? 0}</span>
                        <span className="text-slate-300 mx-0.5">/</span>
                        <span className="text-blue-600">{r.draw_types?.type_a ?? 0}</span>
                        <span className="text-slate-300 mx-0.5">/</span>
                        <span className="text-amber-600">{r.draw_types?.type_b ?? 0}</span>
                        <span className="text-slate-300 mx-0.5">/</span>
                        <span className="text-red-600">{r.draw_types?.sde ?? 0}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* ── DRAW TYPES chart ── */}
          {viewTab === 'draws' && (
            <div className="p-6 space-y-4">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Draw Type Breakdown Per Week</p>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartDraws} margin={{top:4,right:8,left:-10,bottom:0}}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
                    <XAxis dataKey="week" tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
                    <YAxis tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} axisLine={false}/>
                    <Tooltip contentStyle={{background:'#fff',border:'1px solid #e2e8f0',borderRadius:12,fontSize:11}} formatter={(v,n)=>[v,n]}/>
                    <Legend wrapperStyle={{fontSize:11,color:'#64748b'}}/>
                    <Bar dataKey="regular" stackId="a" fill="#10b981" name="Regular"  radius={[0,0,0,0]}/>
                    <Bar dataKey="type_a"  stackId="a" fill="#3b82f6" name="Type A"   radius={[0,0,0,0]}/>
                    <Bar dataKey="type_b"  stackId="a" fill="#f59e0b" name="Type B"   radius={[0,0,0,0]}/>
                    <Bar dataKey="sde"     stackId="a" fill="#ef4444" name="SDE Exit" radius={[4,4,0,0]}/>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="grid grid-cols-4 gap-3 text-center">
                {['regular','type_a','type_b','sde'].map((t,i) => {
                  const total = rows.reduce((s,r) => s + (r.draw_types?.[t] ?? 0), 0)
                  const color = ['text-emerald-700','text-blue-700','text-amber-700','text-red-700'][i]
                  const bg    = ['bg-emerald-50','bg-blue-50','bg-amber-50','bg-red-50'][i]
                  return (
                    <div key={t} className={`${bg} rounded-xl py-3`}>
                      <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">{t.replace('_',' ')}</p>
                      <p className={`text-2xl font-black ${color} tabular-nums`}>{total}</p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ── PAYOUTS chart ── */}
          {viewTab === 'payouts' && (
            <div className="p-6 space-y-4">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Weekly Payout vs Deposits</p>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartPayouts} margin={{top:4,right:8,left:0,bottom:0}}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
                    <XAxis dataKey="week" tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
                    <YAxis tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} axisLine={false} tickFormatter={v=>v>=1000?`₹${(v/1000).toFixed(0)}k`:`₹${v}`}/>
                    <Tooltip contentStyle={{background:'#fff',border:'1px solid #e2e8f0',borderRadius:12,fontSize:11}} formatter={v=>INR_W(v)}/>
                    <Legend wrapperStyle={{fontSize:11,color:'#64748b'}}/>
                    <Bar dataKey="deposits"    fill="#e0f2fe" stroke="#0284c7" strokeWidth={1} name="Total Deposits" radius={[3,3,0,0]}/>
                    <Line dataKey="total_payout" stroke="#10b981" strokeWidth={2.5} dot={false} name="Total Payout" type="monotone"/>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                {[
                  { label:'Total Paid Out', val: rows.reduce((s,r)=>s+r.total_payout_inr,0), color:'text-emerald-700', bg:'bg-emerald-50' },
                  { label:'Total Deposits', val: rows.reduce((s,r)=>s+r.total_deposits_inr,0), color:'text-blue-700', bg:'bg-blue-50' },
                  { label:'Avg Weekly Payout', val: rows.length ? rows.reduce((s,r)=>s+r.total_payout_inr,0)/rows.length : 0, color:'text-violet-700', bg:'bg-violet-50' },
                ].map(({label,val,color,bg}) => (
                  <div key={label} className={`${bg} rounded-xl py-3`}>
                    <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">{label}</p>
                    <p className={`text-xl font-black ${color} tabular-nums`}>{INR_W(val)}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── WIN LEVELS chart ── */}
          {viewTab === 'levels' && (
            <div className="p-6 space-y-4">
              <p className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Winner Level Distribution Per Week</p>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartLevels} margin={{top:4,right:8,left:-10,bottom:0}}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
                    <XAxis dataKey="week" tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
                    <YAxis tick={{fill:'#94a3b8',fontSize:10}} tickLine={false} axisLine={false}/>
                    <Tooltip contentStyle={{background:'#fff',border:'1px solid #e2e8f0',borderRadius:12,fontSize:11}}/>
                    <Legend wrapperStyle={{fontSize:11,color:'#64748b'}}/>
                    {['L1','L2','L3','L4','L5','L6'].map(lv => (
                      <Bar key={lv} dataKey={lv} stackId="a" fill={LEVEL_COLORS[lv]}
                        radius={lv==='L6'?[4,4,0,0]:[0,0,0,0]} name={lv}/>
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="grid grid-cols-6 gap-2 text-center">
                {['L1','L2','L3','L4','L5','L6'].map(lv => {
                  const total = rows.reduce((s,r) => s + (r.winner_levels?.[lv] ?? 0), 0)
                  return (
                    <div key={lv} className="rounded-xl py-3" style={{ background: LEVEL_COLORS[lv] + '15', border: `1px solid ${LEVEL_COLORS[lv]}30` }}>
                      <p className="text-[10px] font-bold text-slate-500 uppercase">{lv}</p>
                      <p className="text-xl font-black tabular-nums" style={{ color: LEVEL_COLORS[lv] }}>{total}</p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// Main page
// ─────────────────────────────────────────────────────────────────────────────

// ═══════════════════════════════════════════════════════════════════════════
// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Weekly Timeline — system-birth-anchored cumulative summary (directive Point 2).
// Week 1 begins the moment the first user joins; every metric (users in/out, cash
// in/out, pools created, draws, winners) is bucketed into contiguous 7-day windows
// with running cumulative totals.  Source: GET /admin/stats/weekly-timeline — now
// meaningful because the Chronos virtual-clock fix stamps audit rows with the
// simulated instant instead of the real PostgreSQL clock.
// ═══════════════════════════════════════════════════════════════════════════
function WeeklyTimelinePanel({ toast }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [view,    setView]    = useState('weekly')   // 'weekly' | 'cumulative'

  const fetch_ = useCallback(async () => {
    setLoading(true)
    try   { const r = await getWeeklyTimeline(); setData(r.data) }
    catch { toast('Failed to load weekly timeline', 'error') }
    finally { setLoading(false) }
  }, [toast])
  useEffect(() => { fetch_() }, [fetch_])

  if (loading) return <div className="flex justify-center h-48"><Spinner className="w-8 h-8 text-violet-500 mt-16"/></div>
  if (!data?.weeks?.length)
    return (
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-xl p-4">
        <AlertCircle className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5"/>
        <p className="text-sm text-blue-700">No activity yet — the timeline begins the moment the first user joins the system.</p>
      </div>
    )

  const t     = data.totals
  const weeks = data.weeks

  const chartData = weeks.map(w => ({
    week:      `W${w.week}`,
    users_in:  w.users_in,
    users_out: w.users_out,
    net_users: w.net_users,
    cash_in:   w.cash_in_inr,
    cash_out:  w.cash_out_inr,
    net_cash:  w.net_cash_inr,
    draws:     w.draws,
    pools:     w.pools_created,
    cum_users: w.cumulative_net_users,
    cum_cash:  w.cumulative_net_cash_inr,
  }))

  // Client-side CSV export — no backend round-trip needed
  const exportCsv = () => {
    const cols = [
      'week','week_start','week_end','users_in','exits_nonpay','exits_won','users_out',
      'net_users','pools_created','draws','winners','sde_exits','deposits_in_inr',
      'grace_in_inr','late_fee_in_inr','cash_in_inr','payouts_out_inr','referral_out_inr',
      'cash_out_inr','net_cash_inr','app_fees_retained_inr','late_fees_accrued_inr',
      'cumulative_users_in','cumulative_users_out','cumulative_net_users','cumulative_draws',
      'cumulative_winners','cumulative_pools_created','cumulative_cash_in_inr',
      'cumulative_cash_out_inr','cumulative_net_cash_inr',
    ]
    const csv = [cols.join(','), ...weeks.map(w => cols.map(c => w[c] ?? 0).join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url
    a.download = `weekly-timeline-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const netCashPos = fP(t.net_cash_inr) >= 0
  const KPIS = [
    { label:'Total Weeks',   value: NUM(data.total_weeks), color:'text-slate-800',   bg:'bg-slate-50 border-slate-200' },
    { label:'Users In',      value: NUM(t.users_in),       color:'text-emerald-600', bg:'bg-emerald-50 border-emerald-200' },
    { label:'Users Out',     value: NUM(t.users_out),      color:'text-rose-600',    bg:'bg-rose-50 border-rose-200' },
    { label:'Net Members',   value: NUM(t.net_users),      color:'text-blue-600',    bg:'bg-blue-50 border-blue-200' },
    { label:'Pools Created', value: NUM(t.pools_created),  color:'text-teal-600',    bg:'bg-teal-50 border-teal-200' },
    { label:'Total Draws',   value: NUM(t.draws),          color:'text-violet-700',  bg:'bg-violet-50 border-violet-200' },
    { label:'Total Winners', value: NUM(t.winners),        color:'text-amber-600',   bg:'bg-amber-50 border-amber-200' },
    { label:'Cash In',       value: INR(t.cash_in_inr),    color:'text-emerald-600', bg:'bg-emerald-50 border-emerald-200' },
    { label:'Cash Out',      value: INR(t.cash_out_inr),   color:'text-rose-600',    bg:'bg-rose-50 border-rose-200' },
    { label:'Net Cash',      value: INR(t.net_cash_inr),   color: netCashPos?'text-emerald-700':'text-red-700', bg: netCashPos?'bg-emerald-50 border-emerald-200':'bg-red-50 border-red-200' },
  ]

  return (
    <motion.div {..._fadeUp} className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-800">Weekly Timeline — Cumulative System Summary</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Week 1 begins when the first user joined{data.anchor_date ? ` · anchor ${data.anchor_date}` : ''}. Every metric is bucketed into 7-day windows with running totals.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-slate-200 overflow-hidden">
            {['weekly','cumulative'].map(v => (
              <button key={v} onClick={() => setView(v)}
                className={`px-3 py-1.5 text-xs font-bold transition ${view===v?'bg-violet-600 text-white':'bg-white text-slate-500 hover:bg-slate-50'}`}>
                {v==='weekly'?'Per-Week':'Cumulative'}
              </button>
            ))}
          </div>
          <button onClick={exportCsv} className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-500 hover:bg-slate-50 transition">
            <Download className="w-3.5 h-3.5"/>CSV
          </button>
          <button onClick={fetch_} className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 transition">
            <RefreshCw className="w-3.5 h-3.5 text-slate-500"/>
          </button>
        </div>
      </div>

      {/* Totals strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {KPIS.map(k => (
          <div key={k.label} className={`rounded-2xl border p-4 ${k.bg}`}>
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">{k.label}</p>
            <p className={`text-lg font-black tabular-nums mt-1 ${k.color}`}>{k.value}</p>
          </div>
        ))}
      </div>

      {/* Cumulative growth */}
      <SectionCard title="Cumulative Growth — Net Members & Net Cash" icon={TrendingUp} iconColor="text-violet-500">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={chartData} margin={{top:8,right:16,left:0,bottom:4}}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
            <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
            <YAxis yAxisId="u" tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false}/>
            <YAxis yAxisId="c" orientation="right" tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false} tickFormatter={v=>INR_COMPACT(v)}/>
            <Tooltip formatter={(v,n)=> n==='Cumulative Net Cash' ? INR(v) : NUM(v)} contentStyle={{border:'1px solid #e2e8f0',borderRadius:12,fontSize:11}}/>
            <Legend wrapperStyle={{fontSize:11}}/>
            <Area yAxisId="u" type="monotone" dataKey="cum_users" name="Cumulative Net Members" stroke={C.blue} strokeWidth={2} fill={C.blue+'18'} dot={false}/>
            <Line yAxisId="c" type="monotone" dataKey="cum_cash" name="Cumulative Net Cash" stroke={C.violet} strokeWidth={2} dot={false}/>
          </ComposedChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* Weekly cash flow */}
      <SectionCard title="Weekly Cash Flow — In vs Out" icon={IndianRupee} iconColor="text-emerald-500">
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={chartData} margin={{top:8,right:16,left:0,bottom:4}}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
            <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
            <YAxis tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false} tickFormatter={v=>INR_COMPACT(v)}/>
            <Tooltip formatter={(v,n)=>[INR(v),n]} contentStyle={{border:'1px solid #e2e8f0',borderRadius:12,fontSize:11}}/>
            <Legend wrapperStyle={{fontSize:11}}/>
            <ReferenceLine y={0} stroke="#94a3b8"/>
            <Bar dataKey="cash_in"  name="Cash In"  fill={C.emerald} radius={[3,3,0,0]} maxBarSize={28}/>
            <Bar dataKey="cash_out" name="Cash Out" fill={C.rose}    radius={[3,3,0,0]} maxBarSize={28}/>
            <Line type="monotone" dataKey="net_cash" name="Net Cash" stroke={C.violet} strokeWidth={2} dot={false}/>
          </ComposedChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* Weekly member flow */}
      <SectionCard title="Weekly Member Flow — In vs Out · Draws · Pools" icon={Users} iconColor="text-blue-500">
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={chartData} margin={{top:8,right:16,left:0,bottom:4}}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false}/>
            <XAxis dataKey="week" tick={{fill:'#64748b',fontSize:10}} tickLine={false} interval="preserveStartEnd"/>
            <YAxis yAxisId="u" tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false}/>
            <YAxis yAxisId="d" orientation="right" tick={{fill:'#64748b',fontSize:10}} tickLine={false} axisLine={false}/>
            <Tooltip contentStyle={{border:'1px solid #e2e8f0',borderRadius:12,fontSize:11}}/>
            <Legend wrapperStyle={{fontSize:11}}/>
            <Bar yAxisId="u" dataKey="users_in"  name="Users In"  fill={C.emerald} radius={[3,3,0,0]} maxBarSize={28}/>
            <Bar yAxisId="u" dataKey="users_out" name="Users Out" fill={C.rose}    radius={[3,3,0,0]} maxBarSize={28}/>
            <Line yAxisId="d" type="monotone" dataKey="draws" name="Draws" stroke={C.blue} strokeWidth={2} dot={false}/>
            <Line yAxisId="d" type="monotone" dataKey="pools" name="Pools Created" stroke={C.teal} strokeWidth={2} strokeDasharray="4 2" dot={false}/>
          </ComposedChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* Detailed table */}
      <SectionCard
        title={view==='weekly' ? 'Per-Week Breakdown' : 'Cumulative Running Totals'}
        icon={TableProperties} iconColor="text-slate-500"
      >
        <div className="overflow-x-auto">
          {view==='weekly' ? (
            <table className="w-full text-sm min-w-[1000px]">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/50">
                  {['Week','Period','In','Out (NP+Won)','Net','Pools','Draws','Win','SDE','Cash In','Cash Out','Net Cash'].map(h=>(
                    <th key={h} className="text-left px-3 py-2.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {weeks.map((w,i)=>(
                  <tr key={w.week} className={`border-b border-slate-50 hover:bg-slate-50 transition-colors ${i%2?'bg-slate-50/30':''}`}>
                    <td className="px-3 py-2 font-bold text-slate-700">W{w.week}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-400 whitespace-nowrap">{w.week_start} → {w.week_end}</td>
                    <td className="px-3 py-2 text-emerald-600 font-semibold tabular-nums">{NUM(w.users_in)}</td>
                    <td className="px-3 py-2 text-rose-600 tabular-nums">{NUM(w.users_out)} <span className="text-[10px] text-slate-400">({NUM(w.exits_nonpay)}+{NUM(w.exits_won)})</span></td>
                    <td className={`px-3 py-2 font-semibold tabular-nums ${w.net_users>=0?'text-blue-600':'text-red-600'}`}>{w.net_users>=0?'+':''}{NUM(w.net_users)}</td>
                    <td className="px-3 py-2 text-teal-600 tabular-nums">{NUM(w.pools_created)}</td>
                    <td className="px-3 py-2 text-slate-700 tabular-nums">{NUM(w.draws)}</td>
                    <td className="px-3 py-2 text-amber-600 tabular-nums">{NUM(w.winners)}</td>
                    <td className="px-3 py-2 text-cyan-600 tabular-nums">{w.sde_exits>0?NUM(w.sde_exits):'—'}</td>
                    <td className="px-3 py-2 text-emerald-600 tabular-nums">{INR(w.cash_in_inr)}</td>
                    <td className="px-3 py-2 text-rose-600 tabular-nums">{INR(w.cash_out_inr)}</td>
                    <td className={`px-3 py-2 font-bold tabular-nums ${fP(w.net_cash_inr)>=0?'text-emerald-700':'text-red-700'}`}>{INR(w.net_cash_inr)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-200 bg-slate-50 font-bold">
                  <td className="px-3 py-2.5 text-slate-700" colSpan={2}>TOTAL</td>
                  <td className="px-3 py-2.5 text-emerald-600 tabular-nums">{NUM(t.users_in)}</td>
                  <td className="px-3 py-2.5 text-rose-600 tabular-nums">{NUM(t.users_out)}</td>
                  <td className={`px-3 py-2.5 tabular-nums ${t.net_users>=0?'text-blue-700':'text-red-700'}`}>{NUM(t.net_users)}</td>
                  <td className="px-3 py-2.5 text-teal-600 tabular-nums">{NUM(t.pools_created)}</td>
                  <td className="px-3 py-2.5 text-slate-700 tabular-nums">{NUM(t.draws)}</td>
                  <td className="px-3 py-2.5 text-amber-600 tabular-nums">{NUM(t.winners)}</td>
                  <td className="px-3 py-2.5 text-slate-300">—</td>
                  <td className="px-3 py-2.5 text-emerald-600 tabular-nums">{INR(t.cash_in_inr)}</td>
                  <td className="px-3 py-2.5 text-rose-600 tabular-nums">{INR(t.cash_out_inr)}</td>
                  <td className={`px-3 py-2.5 tabular-nums ${fP(t.net_cash_inr)>=0?'text-emerald-700':'text-red-700'}`}>{INR(t.net_cash_inr)}</td>
                </tr>
              </tfoot>
            </table>
          ) : (
            <table className="w-full text-sm min-w-[900px]">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/50">
                  {['Week','Period','Σ Users In','Σ Users Out','Σ Net Members','Σ Pools','Σ Draws','Σ Winners','Σ Cash In','Σ Cash Out','Σ Net Cash'].map(h=>(
                    <th key={h} className="text-left px-3 py-2.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {weeks.map((w,i)=>(
                  <tr key={w.week} className={`border-b border-slate-50 hover:bg-slate-50 transition-colors ${i%2?'bg-slate-50/30':''}`}>
                    <td className="px-3 py-2 font-bold text-slate-700">W{w.week}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-400 whitespace-nowrap">{w.week_start} → {w.week_end}</td>
                    <td className="px-3 py-2 text-emerald-600 tabular-nums">{NUM(w.cumulative_users_in)}</td>
                    <td className="px-3 py-2 text-rose-600 tabular-nums">{NUM(w.cumulative_users_out)}</td>
                    <td className={`px-3 py-2 font-semibold tabular-nums ${w.cumulative_net_users>=0?'text-blue-600':'text-red-600'}`}>{NUM(w.cumulative_net_users)}</td>
                    <td className="px-3 py-2 text-teal-600 tabular-nums">{NUM(w.cumulative_pools_created)}</td>
                    <td className="px-3 py-2 text-slate-700 tabular-nums">{NUM(w.cumulative_draws)}</td>
                    <td className="px-3 py-2 text-amber-600 tabular-nums">{NUM(w.cumulative_winners)}</td>
                    <td className="px-3 py-2 text-emerald-600 tabular-nums">{INR(w.cumulative_cash_in_inr)}</td>
                    <td className="px-3 py-2 text-rose-600 tabular-nums">{INR(w.cumulative_cash_out_inr)}</td>
                    <td className={`px-3 py-2 font-bold tabular-nums ${fP(w.cumulative_net_cash_inr)>=0?'text-emerald-700':'text-red-700'}`}>{INR(w.cumulative_net_cash_inr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </SectionCard>

      {/* Cash composition note */}
      <div className="flex items-start gap-3 bg-slate-50 border border-slate-200 rounded-xl p-4">
        <Info className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5"/>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          <span className="font-semibold text-slate-600">Cash In</span> = deposits (join + weekly) + grace fees + late-fee settlements.{' '}
          <span className="font-semibold text-slate-600">Cash Out</span> = winner net payouts + referral withdrawals.{' '}
          Late-fee <em>accruals</em> (unsettled liabilities) and the per-winner platform fee retained from gross payouts are tracked separately and excluded from net cash to prevent double-counting.
        </p>
      </div>
    </motion.div>
  )
}


export default function Statistics() {
  const toast = useToast()

  // ── Data ──────────────────────────────────────────────────────────────────
  const [financials,      setFinancials]      = useState(null)
  const [poolStats,       setPoolStats]       = useState(null)
  const [forecast,        setForecast]        = useState(null)
  const [chartData,       setChartData]       = useState(null)
  const [levelBreakdown,  setLevelBreakdown]  = useState(null)
  const [lpiData,         setLpiData]         = useState(null)
  const [witTokens,       setWitTokens]       = useState([])
  const [refTokens,       setRefTokens]       = useState([])

  // ── Loading / error ───────────────────────────────────────────────────────
  const [loading, setLoading] = useState({ main: true, charts: true, actions: true })
  const [errors,  setErrors]  = useState({})
  const [refreshing,  setRefreshing]  = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)

  // ── UI state ──────────────────────────────────────────────────────────────
  const [chartDays,     setChartDays]     = useState(30)
  const [expandedPools, setExpandedPools] = useState(new Set())
  const [actioning,     setActioning]     = useState(new Set())  // token IDs in-flight
  const [subTab,        setSubTab]        = useState('overview') // sub-tab navigation

  // ─────────────────────────────────────────────────────────────────────────
  // Fetch helpers
  // ─────────────────────────────────────────────────────────────────────────

  const fetchCore = useCallback(async (silent = false) => {
    silent ? setRefreshing(true) : setLoading(l => ({ ...l, main: true }))
    setErrors(e => ({ ...e, financials: null, pools: null, forecast: null }))

    const [finR, poolR, foreR, lvlR, lpiR] = await Promise.allSettled([
      getFinancials(),
      getPoolStats(),
      getAiForecast(),
      getLevelBreakdown(),
      getBrain5Lpi(),
    ])

    if (finR.status  === 'fulfilled') setFinancials(finR.value.data)
    else setErrors(e => ({ ...e, financials: finR.reason?.response?.data?.detail ?? 'Load failed' }))

    if (poolR.status === 'fulfilled') setPoolStats(poolR.value.data)
    else setErrors(e => ({ ...e, pools: poolR.reason?.response?.data?.detail ?? 'Load failed' }))

    if (foreR.status === 'fulfilled') setForecast(foreR.value.data)
    else setErrors(e => ({ ...e, forecast: foreR.reason?.response?.data?.detail ?? 'Load failed' }))

    if (lvlR.status  === 'fulfilled') setLevelBreakdown(lvlR.value.data)
    // level breakdown + lpi failures are non-fatal — sections show empty state
    if (lpiR.status  === 'fulfilled') setLpiData(lpiR.value.data)

    setLoading(l => ({ ...l, main: false }))
    setRefreshing(false)
    setLastUpdated(new Date())
  }, [])

  const fetchCharts = useCallback(async (days) => {
    setLoading(l => ({ ...l, charts: true }))
    setErrors(e => ({ ...e, charts: null }))
    try {
      const res = await getChartData(days)
      setChartData(res.data)
    } catch (err) {
      setErrors(e => ({ ...e, charts: err.response?.data?.detail ?? 'Chart data unavailable' }))
    } finally {
      setLoading(l => ({ ...l, charts: false }))
    }
  }, [])

  const fetchPending = useCallback(async () => {
    setLoading(l => ({ ...l, actions: true }))
    setErrors(e => ({ ...e, actions: null }))
    try {
      const [wR, rR] = await Promise.all([
        getAdminTokens({ type: 'Withdraw', status: 'Active', limit: 500 }),
        getAdminTokens({ type: 'Referral', status: 'Active', limit: 500 }),
      ])
      setWitTokens(wR.data)
      setRefTokens(rR.data)
    } catch (err) {
      setErrors(e => ({ ...e, actions: err.response?.data?.detail ?? 'Failed to load pending tokens' }))
    } finally {
      setLoading(l => ({ ...l, actions: false }))
    }
  }, [])

  useEffect(() => { fetchCore() }, [fetchCore])
  useEffect(() => { fetchPending() }, [fetchPending])
  useEffect(() => { fetchCharts(chartDays) }, [fetchCharts, chartDays])

  // ─────────────────────────────────────────────────────────────────────────
  // Token actions
  // ─────────────────────────────────────────────────────────────────────────

  const handleWit = async (tokenId, action) => {
    setActioning(s => new Set([...s, tokenId]))
    try {
      await updateTokenStatus(tokenId, action)
      toast(
        action === 'approve' ? '✅ Payment confirmed — token burned' : '🚫 Token rejected',
        action === 'approve' ? 'success' : 'info',
      )
      setWitTokens(t => t.filter(tk => tk.id !== tokenId))
      fetchCore(true)   // refresh KPI cards silently
    } catch (err) {
      toast(err.response?.data?.detail ?? `Failed to ${action}`, 'error')
    } finally {
      setActioning(s => { const n = new Set(s); n.delete(tokenId); return n })
    }
  }

  const handleRef = async (code, tokenId) => {
    setActioning(s => new Set([...s, tokenId]))
    try {
      await burnToken(code)
      toast('✅ Referral reward paid out', 'success')
      setRefTokens(t => t.filter(tk => tk.id !== tokenId))
      fetchCore(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to pay referral', 'error')
    } finally {
      setActioning(s => { const n = new Set(s); n.delete(tokenId); return n })
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Derived values
  // ─────────────────────────────────────────────────────────────────────────

  const togglePool = id => setExpandedPools(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const totalRegistered = financials
    ? fI(financials.active_user_count) + fI(financials.waitlist_count) + fI(financials.eliminated_count)
    : 0

  // New liability-adjusted metrics
  const pureProfit     = fP(financials?.pure_realized_profit_inr    ?? 0)
  const cashInflow     = fP(financials?.total_cash_inflow_inr        ?? 0)
  const cashOutflow    = fP(financials?.total_cash_outflow_inr       ?? 0)
  const activeLiab     = fP(financials?.current_active_liability_inr ?? 0)
  const weeklySurplus  = fP(financials?.weekly_rolling_surplus_inr   ?? 0)
  const weeklyCol      = fP(financials?.weekly_collections_inr       ?? 0)
  const weeklyPay      = fP(financials?.weekly_payouts_inr           ?? 0)

  // Prep chart points — convert all number strings to floats + add computed fields
  const chartPts = (chartData?.data ?? []).map(pt => ({
    label:            pt.period.length >= 10 ? pt.period.slice(5) : pt.period,
    registrations:    fI(pt.registrations),
    dep:              fP(pt.dep_collected_inr),
    payout:           fP(pt.wit_paid_inr) + fP(pt.ref_paid_inr),
    net:              fP(pt.net_profit_inr),
  }))

  const mainLoading = loading.main

  // ── Sub-tab navigation ────────────────────────────────────────────────────
  // S-01 to S-08: Added new enhanced analytics sub-tabs
  const SUB_TABS = [
    { id: 'overview',       label: 'Overview',              icon: BarChart3    },
    // SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
    { id: 'weekly_timeline',label: 'Weekly Timeline',       icon: TableProperties },
    { id: 'weekly_pools',   label: 'Weekly Pool Reports',   icon: CalendarRange },
    { id: 'live_stats',     label: 'Live Stats',            icon: Activity     },
    { id: 'level_map',      label: 'Level Map',             icon: Layers       },
    { id: 'winners',        label: 'Winners Analytics',     icon: Target       },
    { id: 'projections',    label: 'Projections',           icon: TrendingUp   },
    { id: 'pauses',         label: 'System Pauses',         icon: Clock        },
    // S-01: LPI History
    { id: 'lpi_history',    label: 'LPI History',           icon: Activity     },
    // S-02: Financial Waterfall
    { id: 'fin_waterfall',  label: 'Cash Waterfall',        icon: Calculator   },
    // S-03: Winner Level Trend
    { id: 'winner_trend',   label: 'Winner Trend',          icon: Award        },
    // S-04: Referral Heatmap
    { id: 'ref_heatmap',    label: 'Referral Heatmap',      icon: GitFork      },
    // S-05: Brain 5 Forward Signal
    { id: 'brain5_signal',  label: 'Brain 5 Signal',        icon: Cpu          },
    // S-06: SDE Event Timeline
    { id: 'sde_timeline',   label: 'SDE Timeline',          icon: Zap          },
    // S-08: Alert Thresholds
    { id: 'alert_thresh',   label: 'Alert Thresholds',      icon: AlertTriangle},
  ]

  // ── Early-return for analytics sub-tabs ───────────────────────────────────
  if (subTab !== 'overview') {
    return (
      <div className="p-8 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
              <BarChart3 className="w-6 h-6 text-violet-600" />
              Statistics &amp; Analytics
            </h1>
          </div>
        </div>
        {/* Sub-tab nav */}
        <div className="flex gap-0.5 border-b border-slate-200 overflow-x-auto pb-px">
          {SUB_TABS.map(t => (
            <button key={t.id} onClick={() => setSubTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition whitespace-nowrap ${
                subTab === t.id
                  ? 'border-violet-600 text-violet-700 -mb-px'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
              }`}>
              <t.icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          ))}
        </div>
        {/* Panel content */}
        {/* SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
        {subTab === 'weekly_timeline' && <WeeklyTimelinePanel  toast={toast} />}
        {subTab === 'weekly_pools'   && <WeeklyPoolReportsPanel toast={toast} />}
        {subTab === 'live_stats'     && <LiveStatsPanel   toast={toast} />}
        {subTab === 'level_map'      && <LevelMapPanel    toast={toast} />}
        {subTab === 'winners'        && <WinnersPanel     toast={toast} />}
        {subTab === 'projections'    && <ProjectionsPanel toast={toast} />}
        {subTab === 'pauses'         && <PausesPanel      toast={toast} />}
        {/* S-01: LPI History Chart */}
        {subTab === 'lpi_history'    && <LpiHistoryPanel      toast={toast} />}
        {/* S-02: Financial Waterfall */}
        {subTab === 'fin_waterfall'  && <FinWaterfallPanel    toast={toast} />}
        {/* S-03: Winner Level Trend */}
        {subTab === 'winner_trend'   && <WinnerTrendPanel     toast={toast} />}
        {/* S-04: Referral Heatmap */}
        {subTab === 'ref_heatmap'    && <ReferralHeatmapPanel toast={toast} />}
        {/* S-05: Brain 5 Forward Signal */}
        {subTab === 'brain5_signal'  && <Brain5SignalPanel    toast={toast} />}
        {/* S-06: SDE Event Timeline */}
        {subTab === 'sde_timeline'   && <SdeTimelinePanel     toast={toast} />}
        {/* S-08: Alert Thresholds */}
        {subTab === 'alert_thresh'   && <AlertThreshPanel     toast={toast} />}
      </div>
    )
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Overview tab (original Statistics content)
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <motion.div {..._stagger} className="p-8 space-y-8">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <motion.div {..._fadeUp} className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-violet-600" />
            Statistics &amp; Analytics
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {lastUpdated ? `Last updated ${lastUpdated.toLocaleTimeString()}` : 'Loading data…'}
          </p>
        </div>
        <button
          onClick={() => { fetchCore(true); fetchPending(); fetchCharts(chartDays) }}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh All
        </button>
      </motion.div>

      {/* Sub-tab nav (Overview tab active) */}
      <motion.div {..._fadeUp} className="flex gap-0.5 border-b border-slate-200 overflow-x-auto pb-px">
        {SUB_TABS.map(t => (
          <button key={t.id} onClick={() => setSubTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition whitespace-nowrap ${
              subTab === t.id
                ? 'border-violet-600 text-violet-700 -mb-px'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            }`}>
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </motion.div>

      {/* ══ 1. SYSTEM LIQUIDITY  ·  ORGANIZER REVENUE ═══════════════════════ */}
      <motion.div {..._fadeUp} className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* ── A. System Liquidity (takes 2 of 3 columns on xl) ───────────── */}
        <div className="xl:col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div
            className="px-6 py-4 border-b border-slate-100 flex items-center gap-3"
            style={{ background: 'linear-gradient(90deg, #eff6ff 0%, #ffffff 65%)' }}
          >
            <div className="w-7 h-7 rounded-xl bg-blue-100 flex items-center justify-center flex-shrink-0">
              <IndianRupee className="w-3.5 h-3.5 text-blue-600" />
            </div>
            <div className="min-w-0">
              <p className="text-[9px] font-semibold text-blue-500 uppercase tracking-widest leading-none">System Float</p>
              <h2 className="text-sm font-bold text-slate-800 leading-none mt-0.5">System Liquidity</h2>
            </div>
            <span className="ml-auto text-[10px] font-mono text-slate-400 flex-shrink-0">All-Time</span>
          </div>

          <div className="p-6 space-y-4">
            {mainLoading ? (
              <>
                <div className="grid grid-cols-3 gap-4">
                  <Skeleton className="h-24" />
                  <Skeleton className="h-24" />
                  <Skeleton className="h-24" />
                </div>
                <Skeleton className="h-10" />
              </>
            ) : (
              <>
                <div className="grid grid-cols-3 gap-4">

                  {/* Total Cash Inflow */}
                  <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-4">
                    <div className="flex items-center gap-1.5 mb-2.5">
                      <TrendingUp className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                      <p className="text-[10px] font-semibold text-emerald-600 uppercase tracking-wider leading-none">
                        Total Cash Inflow
                      </p>
                    </div>
                    <p className="text-2xl font-black text-emerald-700 tabular-nums leading-none">
                      {INR(financials?.total_cash_inflow_inr)}
                    </p>
                    <p className="text-[10px] text-emerald-500 mt-2 leading-snug">
                      All DEP tokens redeemed
                    </p>
                  </div>

                  {/* Total Cash Outflow */}
                  <div className="bg-red-50 border border-red-200 rounded-2xl p-4">
                    <div className="flex items-center gap-1.5 mb-2.5">
                      <TrendingDown className="w-3.5 h-3.5 text-red-600 flex-shrink-0" />
                      <p className="text-[10px] font-semibold text-red-600 uppercase tracking-wider leading-none">
                        Total Cash Outflow
                      </p>
                    </div>
                    <p className="text-2xl font-black text-red-700 tabular-nums leading-none">
                      {INR(financials?.total_cash_outflow_inr)}
                    </p>
                    <p className="text-[10px] text-red-400 mt-2 leading-snug">
                      WIT &amp; Referral_Withdraw paid
                    </p>
                  </div>

                  {/* Active Liability — colour-coded by severity vs. liquidity */}
                  {(() => {
                    const liq    = fP(financials?.in_hand_liquidity_inr ?? 0)
                    const ratio  = liq > 0 ? activeLiab / liq : (activeLiab > 0 ? 9 : 0)
                    const danger = ratio > 1
                    const warn   = !danger && ratio > 0.5
                    return (
                      <div className={`rounded-2xl p-4 border ${
                        danger ? 'bg-red-50 border-red-400' :
                        warn   ? 'bg-amber-50 border-amber-300' :
                                 'bg-amber-50/60 border-amber-200'
                      }`}>
                        <div className="flex items-center gap-1.5 mb-2.5">
                          {(danger || warn)
                            ? <AlertTriangle className={`w-3.5 h-3.5 flex-shrink-0 ${danger ? 'text-red-600' : 'text-amber-600'}`} />
                            : <Shield className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
                          }
                          <p className={`text-[10px] font-semibold uppercase tracking-wider leading-none ${
                            danger ? 'text-red-600' : 'text-amber-600'
                          }`}>
                            Active Liability
                          </p>
                          {(danger || warn) && (
                            <span className={`ml-auto text-[8px] font-black px-1.5 py-0.5 rounded-full uppercase tracking-wide flex-shrink-0 ${
                              danger
                                ? 'bg-red-100 text-red-700 border border-red-200'
                                : 'bg-amber-100 text-amber-700 border border-amber-200'
                            }`}>
                              {danger ? 'HIGH ⚠' : 'MONITOR'}
                            </span>
                          )}
                        </div>
                        <p className={`text-2xl font-black tabular-nums leading-none ${
                          danger ? 'text-red-700' : 'text-amber-700'
                        }`}>
                          {INR(financials?.current_active_liability_inr)}
                        </p>
                        <p className={`text-[10px] mt-2 leading-snug ${danger ? 'text-red-400' : 'text-amber-500'}`}>
                          Principal owed · Active &amp; Waitlist
                        </p>
                      </div>
                    )
                  })()}
                </div>

                {/* Net Float summary bar */}
                <div className="flex items-center justify-between bg-slate-50 rounded-xl px-5 py-3 border border-slate-100">
                  <p className="text-[11px] text-slate-500">
                    Net Float
                    <span className="text-slate-300 mx-1.5">·</span>
                    Inflow − Outflow
                    <span className="text-slate-300 mx-1.5">·</span>
                    Available cash in hand
                  </p>
                  <span className={`text-base font-black tabular-nums ${
                    fP(financials?.in_hand_liquidity_inr) >= 0 ? 'text-emerald-600' : 'text-red-600'
                  }`}>
                    {INR(financials?.in_hand_liquidity_inr)}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>

        {/* ── B. Organizer Revenue (1 of 3 columns on xl) ──────────────────── */}
        <div className="flex flex-col gap-4">

          {/* Maintenance Fees — fixed income */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden flex-1">
            <div
              className="px-5 py-3.5 border-b border-slate-100 flex items-center gap-2.5"
              style={{ background: 'linear-gradient(90deg, #f5f3ff 0%, #ffffff 60%)' }}
            >
              <div className="w-6 h-6 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
                <Zap className="w-3 h-3 text-violet-600" />
              </div>
              <div className="min-w-0">
                <p className="text-[9px] font-semibold text-violet-500 uppercase tracking-widest leading-none">Fixed Income</p>
                <h3 className="text-xs font-bold text-slate-800 leading-none mt-0.5">Maintenance Fees</h3>
              </div>
            </div>
            <div className="p-5">
              {mainLoading ? (
                <div className="space-y-2.5">
                  <Skeleton className="h-9 w-36" />
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-4 w-40" />
                </div>
              ) : (
                <>
                  <p className="text-3xl font-black text-violet-700 tabular-nums leading-none">
                    {INR(financials?.maintenance_fees_total_inr)}
                  </p>
                  <p className="text-[11px] text-slate-400 mt-2">
                    {NUM(financials?.maintenance_fees_count)} draws × ₹500 per winner
                  </p>
                  <div className="mt-3 flex items-center gap-1.5 text-[11px] font-semibold text-violet-600">
                    <TrendingUp className="w-3.5 h-3.5" />
                    Always positive · Earned at draw time
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Pure Realized Profit — hero card with tooltip */}
          <div
            className="rounded-2xl overflow-hidden flex-1"
            style={mainLoading ? {
              background: '#f8fafc',
              border: '2px solid #e2e8f0',
              boxShadow: 'none',
            } : pureProfit >= 0 ? {
              background: 'linear-gradient(145deg, #065f46 0%, #059669 100%)',
              border: '2px solid #10b981',
              boxShadow: '0 8px 32px rgba(5,150,105,0.22)',
            } : {
              background: 'linear-gradient(145deg, #7f1d1d 0%, #dc2626 100%)',
              border: '2px solid #ef4444',
              boxShadow: '0 8px 32px rgba(220,38,38,0.22)',
            }}
          >
            {/* Card header */}
            <div className={`px-5 py-3.5 flex items-center gap-2 ${
              mainLoading ? 'border-b border-slate-100' : 'border-b border-white/15'
            }`}>
              <Calculator className={`w-4 h-4 flex-shrink-0 ${mainLoading ? 'text-slate-400' : 'text-white/80'}`} />
              <span className={`text-xs font-bold leading-none ${mainLoading ? 'text-slate-600' : 'text-white/90'}`}>
                Pure Realized Profit
              </span>
              {/* Info tooltip — only shown once the card is coloured */}
              {!mainLoading && (
                <InfoTooltip text="Total Cash Inflow minus Total Cash Outflow minus Active Member Principal Liability. This is safe, withdrawable profit — the exact net yield the organiser has captured after all known obligations are fully accounted for." />
              )}
            </div>

            {/* Card body */}
            <div className="p-5">
              {mainLoading ? (
                <div className="space-y-2.5">
                  <Skeleton className="h-10 w-36" />
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-7 w-32" />
                </div>
              ) : (
                <>
                  <p className="text-4xl font-black text-white tabular-nums leading-none">
                    {INR(financials?.pure_realized_profit_inr)}
                  </p>
                  <p className="text-[11px] text-white/55 mt-2">
                    Inflow − Outflow − Active Liability
                  </p>
                  <div className={`mt-4 inline-flex items-center gap-1.5 text-[11px] font-bold px-3 py-1.5 rounded-full ${
                    pureProfit >= 0 ? 'bg-white/15 text-white' : 'bg-white/10 text-white/80'
                  }`}>
                    {pureProfit >= 0
                      ? <><CheckCircle2 className="w-3.5 h-3.5" />Safe to withdraw</>
                      : <><AlertTriangle className="w-3.5 h-3.5" />Deficit — monitor closely</>
                    }
                  </div>
                </>
              )}
            </div>
          </div>

        </div>
      </motion.div>

      {/* ══ 2. WEEKLY CASH FLOW HEALTH ════════════════════════════════════════ */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        <div
          className="px-6 py-4 border-b border-slate-100 flex items-center gap-3"
          style={{ background: 'linear-gradient(90deg, #f5f3ff 0%, #ffffff 65%)' }}
        >
          <div className="w-7 h-7 rounded-xl bg-violet-100 flex items-center justify-center flex-shrink-0">
            <Clock className="w-3.5 h-3.5 text-violet-600" />
          </div>
          <div className="min-w-0">
            <p className="text-[9px] font-semibold text-violet-500 uppercase tracking-widest leading-none">Real-Time</p>
            <h2 className="text-sm font-bold text-slate-800 leading-none mt-0.5">Weekly Cash Flow Health</h2>
          </div>
          {!mainLoading && financials?.week_start_date && (
            <span className="ml-auto text-[10px] font-mono text-slate-400 bg-slate-50 border border-slate-100 px-2.5 py-1 rounded-lg flex-shrink-0">
              Week since {financials.week_start_date}
            </span>
          )}
        </div>

        <div className="p-6">
          {mainLoading ? (
            <div className="flex gap-6">
              <div className="flex-1 space-y-4">
                <Skeleton className="h-5 w-full" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-3 w-3/4" />
              </div>
              <div className="w-52 space-y-3 flex-shrink-0">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            </div>
          ) : (
            <div className="flex flex-col sm:flex-row items-start gap-6">

              {/* Left: proportional bar chart */}
              <div className="flex-1 min-w-0 space-y-4">

                {/* Collections bar */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-600 flex items-center gap-1.5">
                      <TrendingUp className="w-3.5 h-3.5 text-blue-500" />
                      Collections this week
                    </span>
                    <span className="text-sm font-black text-blue-700 tabular-nums">
                      {INR(financials?.weekly_collections_inr)}
                    </span>
                  </div>
                  <div className="w-full h-3 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        background: 'linear-gradient(90deg, #3b82f6, #60a5fa)',
                        width: weeklyCol + weeklyPay > 0
                          ? `${Math.max(2, Math.min(100, weeklyCol / (weeklyCol + weeklyPay) * 100))}%`
                          : '0%',
                        transition: 'width 0.7s ease-out',
                      }}
                    />
                  </div>
                </div>

                {/* Payouts bar */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-600 flex items-center gap-1.5">
                      <TrendingDown className="w-3.5 h-3.5 text-rose-500" />
                      Payouts this week
                    </span>
                    <span className="text-sm font-black text-rose-700 tabular-nums">
                      {INR(financials?.weekly_payouts_inr)}
                    </span>
                  </div>
                  <div className="w-full h-3 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        background: 'linear-gradient(90deg, #f43f5e, #fb7185)',
                        width: weeklyCol + weeklyPay > 0
                          ? `${Math.max(2, Math.min(100, weeklyPay / (weeklyCol + weeklyPay) * 100))}%`
                          : '0%',
                        transition: 'width 0.7s ease-out',
                      }}
                    />
                  </div>
                </div>

                <p className="text-[10px] text-slate-400 leading-relaxed pt-1">
                  Bars show proportional share of weekly activity.
                  Collections = DEP tokens redeemed &nbsp;·&nbsp; Payouts = WIT tokens burned (admin-approved).
                </p>
              </div>

              {/* Vertical divider */}
              <div className="hidden sm:block w-px self-stretch bg-slate-100 flex-shrink-0" />

              {/* Right: surplus hero */}
              <div className="flex-shrink-0 sm:text-right min-w-[200px]">
                <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
                  Net Weekly Surplus
                </p>
                <p className={`text-4xl font-black tabular-nums leading-none ${
                  weeklySurplus >= 0 ? 'text-violet-700' : 'text-red-600'
                }`}>
                  {weeklySurplus >= 0 ? '+' : ''}{INR(financials?.weekly_rolling_surplus_inr)}
                </p>
                <p className="text-[11px] text-slate-400 mt-1.5">
                  Collections − Payouts
                </p>
                <div className={`mt-3 inline-flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-full border ${
                  weeklyCol === 0 && weeklyPay === 0
                    ? 'bg-slate-50 text-slate-500 border-slate-200'
                    : weeklySurplus >= 0
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : 'bg-red-50 text-red-700 border-red-200'
                }`}>
                  {weeklyCol === 0 && weeklyPay === 0 ? (
                    'No activity yet this week'
                  ) : weeklySurplus >= 0 ? (
                    <><CheckCircle2 className="w-3.5 h-3.5" />Healthy cash flow</>
                  ) : (
                    <><AlertTriangle className="w-3.5 h-3.5" />Payout-heavy week — monitor</>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ══ Financial Waterfall ══════════════════════════════════════════════ */}
      {!mainLoading && financials && (() => {
        const inflow     = fP(financials.total_cash_inflow_inr ?? 0)
        const outflow    = fP(financials.total_cash_outflow_inr ?? 0)
        const maintFees  = fP(financials.maintenance_fees_total_inr ?? 0)
        const netFloat   = fP(financials.in_hand_liquidity_inr ?? 0)
        const total      = Math.max(inflow + maintFees, 0.01)   // denominator guard

        const segments = [
          { label: 'Gross Collected', value: inflow,    pct: inflow / total * 100,        bg: 'bg-emerald-500', text: 'text-emerald-700' },
          { label: 'Maint. Fees',     value: maintFees, pct: maintFees / total * 100,     bg: 'bg-violet-500',  text: 'text-violet-700'  },
          { label: 'Paid Out',        value: outflow,   pct: outflow / total * 100,        bg: 'bg-rose-400',    text: 'text-rose-700'    },
          { label: 'Net Float',       value: netFloat,  pct: Math.max(0, netFloat / total * 100), bg: netFloat >= 0 ? 'bg-blue-500' : 'bg-red-400', text: netFloat >= 0 ? 'text-blue-700' : 'text-red-600' },
        ]
        return (
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-3"
                 style={{ background: 'linear-gradient(90deg, #f5f3ff 0%, #fff 65%)' }}>
              <div className="w-7 h-7 rounded-xl bg-violet-100 flex items-center justify-center flex-shrink-0">
                <IndianRupee className="w-3.5 h-3.5 text-violet-600" />
              </div>
              <div className="min-w-0">
                <p className="text-[9px] font-semibold text-violet-500 uppercase tracking-widest leading-none">All-Time</p>
                <h2 className="text-sm font-bold text-slate-800 leading-none mt-0.5">Financial Waterfall</h2>
              </div>
              <span className="ml-auto text-[10px] font-mono text-slate-400 flex-shrink-0">Gross → Fees → Payouts → Float</span>
            </div>
            <div className="p-6 space-y-5">
              {/* Stacked flow bar */}
              <div className="flex h-7 rounded-full overflow-hidden gap-0.5">
                {segments.filter(s => s.pct > 0).map((s, i) => (
                  <div key={i} className={`${s.bg} flex items-center justify-center`}
                       style={{ width: `${Math.max(s.pct, 1)}%`, minWidth: 2, transition: 'width 0.9s ease' }}
                       title={`${s.label}: ${INR(s.value)}`} />
                ))}
              </div>
              {/* Legend + amounts */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {segments.map((s, i) => (
                  <div key={i} className="bg-slate-50 rounded-xl p-3.5 border border-slate-100">
                    <div className={`w-3 h-3 rounded-full ${s.bg} mb-2`} />
                    <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-0.5">{s.label}</p>
                    <p className={`text-base font-black tabular-nums ${s.text}`}>{INR(s.value)}</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">{s.pct.toFixed(1)}% of total</p>
                  </div>
                ))}
              </div>
              {/* Arrow flow annotation */}
              <div className="flex items-center gap-2 flex-wrap text-[10px] text-slate-400 font-mono">
                <span className="bg-emerald-50 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded font-semibold">{INR(inflow)} In</span>
                <span>+</span>
                <span className="bg-violet-50 text-violet-700 border border-violet-200 px-2 py-0.5 rounded font-semibold">{INR(maintFees)} Fees</span>
                <span>−</span>
                <span className="bg-rose-50 text-rose-700 border border-rose-200 px-2 py-0.5 rounded font-semibold">{INR(outflow)} Out</span>
                <span>=</span>
                <span className={`border px-2 py-0.5 rounded font-bold ${netFloat >= 0 ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-red-50 text-red-700 border-red-200'}`}>
                  {INR(netFloat)} Float
                </span>
              </div>
            </div>
          </div>
        )
      })()}

      {/* ══ 3. QUICK REFERENCE METRICS ════════════════════════════════════════ */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <KPICard
          loading={mainLoading}
          label="In-Hand Liquidity"
          value={INR(financials?.in_hand_liquidity_inr)}
          sub="DEP received minus all payouts made"
          icon={IndianRupee}
          iconBg="bg-emerald-50" iconColor="text-emerald-600"
          trend={!mainLoading ? (fP(financials?.in_hand_liquidity_inr) >= 0 ? 'positive' : 'negative') : null}
        />
        <KPICard
          loading={mainLoading}
          label="Outstanding WIT + REF"
          value={INR(financials?.total_liability_inr)}
          sub={!mainLoading
            ? `${INR(financials?.wit_liability_inr)} WIT · ${INR(financials?.ref_liability_inr)} REF`
            : ''}
          icon={Clock}
          iconBg="bg-amber-50" iconColor="text-amber-600"
          trend={!mainLoading && fP(financials?.total_liability_inr) > 0 ? 'warn' : null}
        />
        <KPICard
          loading={mainLoading}
          label="Doomsday Liability"
          value={INR(financials?.doomsday_liability_inr)}
          sub="Max refund if all active users exit today"
          icon={AlertTriangle}
          iconBg="bg-red-50" iconColor="text-red-500"
          trend="negative"
        />
        <KPICard
          loading={mainLoading}
          label="Total Registered"
          value={NUM(totalRegistered)}
          sub={!mainLoading
            ? `${NUM(financials?.active_user_count)} active · ${NUM(financials?.waitlist_count)} waitlist · ${NUM(financials?.eliminated_count)} eliminated`
            : ''}
          icon={Users}
          iconBg="bg-slate-50" iconColor="text-slate-600"
        />
      </div>

      {/* ── 3. AI Forecast Panel ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-5">

        {/* Waitlist Velocity */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <div className="flex items-center gap-2 mb-5">
            <Target className="w-4 h-4 text-blue-500" />
            <h2 className="font-semibold text-slate-800">Waitlist Velocity</h2>
            <span className="ml-auto text-[10px] uppercase tracking-widest text-slate-400 font-semibold">
              AI Prediction
            </span>
          </div>

          {mainLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-11" />
              <Skeleton className="h-20" />
              <Skeleton className="h-8 w-4/5" />
            </div>
          ) : errors.forecast ? (
            <InlineError message={errors.forecast} />
          ) : forecast?.waitlist_velocity ? (() => {
            const wv = forecast.waitlist_velocity
            return (
              <>
                <div className="flex items-end gap-3 mb-5">
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">Next Pool Trigger</p>
                    <p className="text-3xl font-black text-slate-900 leading-none tabular-nums">
                      {wv.estimated_trigger_date ?? '—'}
                    </p>
                  </div>
                  <ConfidenceBadge confidence={wv.confidence} />
                </div>
                <div className="grid grid-cols-3 gap-2 mb-4">
                  {[
                    { label: 'Paid Waitlist', value: wv.current_paid_waitlist, accent: 'text-slate-800' },
                    { label: 'Slots Needed',  value: wv.needed_to_trigger,     accent: 'text-amber-600' },
                    { label: 'Daily Rate',    value: `${fP(wv.avg_daily_new_members).toFixed(1)}/d`, accent: 'text-blue-600' },
                  ].map(({ label, value, accent }) => (
                    <div key={label} className="bg-slate-50 rounded-xl p-3 text-center">
                      <p className="text-[10px] text-slate-400 mb-1">{label}</p>
                      <p className={`text-lg font-bold ${accent}`}>{value}</p>
                    </div>
                  ))}
                </div>
                {/* Waitlist progress bar */}
                <div className="mb-3">
                  <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                    <span>Progress to trigger</span>
                    <span>{wv.current_paid_waitlist} / 24</span>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-1.5">
                    <div
                      className="bg-blue-500 h-1.5 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (wv.current_paid_waitlist / 24) * 100)}%` }}
                    />
                  </div>
                </div>
                <p className="text-[11px] text-slate-400 leading-relaxed border-t border-slate-100 pt-3">
                  {wv.note}
                </p>
              </>
            )
          })() : (
            <p className="text-sm text-slate-400 text-center py-8">Forecast unavailable</p>
          )}
        </div>

        {/* Liquidity Runway */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <div className="flex items-center gap-2 mb-5">
            <Activity className="w-4 h-4 text-violet-500" />
            <h2 className="font-semibold text-slate-800">Liquidity Runway</h2>
            <span className="ml-auto text-[10px] uppercase tracking-widest text-slate-400 font-semibold">
              AI Prediction
            </span>
          </div>

          {mainLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-11" />
              <Skeleton className="h-20" />
              <Skeleton className="h-8 w-4/5" />
            </div>
          ) : errors.forecast ? (
            <InlineError message={errors.forecast} />
          ) : forecast?.liquidity_runway ? (() => {
            const lr = forecast.liquidity_runway
            const positive = fP(lr.net_weekly_flow_inr) >= 0
            return (
              <>
                <div className="flex items-end gap-3 mb-5">
                  {lr.is_self_sustaining ? (
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-7 h-7 text-emerald-500 flex-shrink-0" />
                      <div>
                        <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-0.5">Status</p>
                        <p className="text-2xl font-black text-emerald-600 leading-none">Self-Sustaining</p>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
                        Estimated Deficit Date
                      </p>
                      <p className="text-3xl font-black text-red-600 leading-none tabular-nums">
                        {lr.estimated_deficit_date ?? 'Calculating…'}
                      </p>
                      {lr.runway_weeks != null && (
                        <p className="text-sm text-red-500 mt-1">
                          {lr.runway_weeks.toFixed(1)} weeks remaining
                        </p>
                      )}
                    </div>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2 mb-4">
                  {[
                    { label: 'Weekly In',   value: INR_COMPACT(lr.avg_weekly_inflow_inr),  bg: 'bg-emerald-50', text: 'text-emerald-700' },
                    { label: 'Weekly Out',  value: INR_COMPACT(lr.avg_weekly_outflow_inr), bg: 'bg-rose-50',    text: 'text-rose-700'    },
                    {
                      label: 'Net/Week',
                      value: (positive ? '+' : '') + INR_COMPACT(lr.net_weekly_flow_inr),
                      bg:    positive ? 'bg-emerald-50' : 'bg-red-50',
                      text:  positive ? 'text-emerald-700' : 'text-red-700',
                    },
                  ].map(({ label, value, bg, text }) => (
                    <div key={label} className={`${bg} rounded-xl p-3 text-center`}>
                      <p className="text-[10px] text-slate-500 mb-1">{label}</p>
                      <p className={`text-sm font-bold ${text}`}>{value}</p>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] text-slate-400 leading-relaxed border-t border-slate-100 pt-3">
                  {lr.note}
                </p>
              </>
            )
          })() : (
            <p className="text-sm text-slate-400 text-center py-8">Forecast unavailable</p>
          )}
        </div>
      </div>

      {/* ══ 4. SDE / BRAIN 5 ENGINE STATUS ══════════════════════════════════ */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* ── A. LPI Gauge panel ────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <div className="flex items-center gap-2 mb-4">
            <Cpu className="w-4 h-4 text-violet-500" />
            <h2 className="font-semibold text-slate-800">Brain 5 — LPI Engine</h2>
            <span className="ml-auto text-[10px] text-emerald-600 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full font-bold uppercase tracking-widest">
              Live
            </span>
          </div>

          {mainLoading || !lpiData ? (
            <div className="space-y-4">
              <Skeleton className="h-28 w-40 mx-auto rounded-xl" />
              <div className="grid grid-cols-2 gap-2">
                <Skeleton className="h-14" /><Skeleton className="h-14" />
                <Skeleton className="h-14 col-span-2" />
              </div>
            </div>
          ) : (
            <>
              <LpiGauge lpi={fP(lpiData.lpi)} />

              <div className="mt-4 grid grid-cols-2 gap-2.5">
                <div className="bg-violet-50 rounded-xl p-3 text-center border border-violet-100">
                  <p className="text-[10px] text-violet-400 uppercase tracking-wide mb-1">L4 Flagged</p>
                  <p className="text-xl font-black text-violet-700 tabular-nums">
                    {fI(lpiData.l4_flagged_count)}
                  </p>
                </div>
                <div className="bg-slate-50 rounded-xl p-3 text-center border border-slate-100">
                  <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">Total Active</p>
                  <p className="text-xl font-black text-slate-700 tabular-nums">
                    {fI(lpiData.total_active)}
                  </p>
                </div>
                <div className="col-span-2 rounded-xl p-3 text-center border border-slate-100 bg-slate-50">
                  <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">SDE Demand</p>
                  <p className={`text-xl font-black tabular-nums ${
                    fP(lpiData.sde_demand_pct) > 50 ? 'text-red-600'
                  : fP(lpiData.sde_demand_pct) > 20 ? 'text-amber-600'
                  :                                    'text-emerald-600'
                  }`}>
                    {fP(lpiData.sde_demand_pct).toFixed(1)}%
                  </p>
                  <p className="text-[9px] text-slate-400 mt-0.5">
                    {fI(lpiData.l3_count ?? 0)} L3 members pushing toward L4
                  </p>
                </div>
              </div>
            </>
          )}
        </div>

        {/* ── B. Pool Type Routing ──────────────────────────────────────────── */}
        <div className="xl:col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <div className="flex items-center gap-2 mb-5">
            <Layers className="w-4 h-4 text-blue-500" />
            <h2 className="font-semibold text-slate-800">Pool Type Routing</h2>
            <span className="ml-auto text-[10px] text-slate-400 font-semibold uppercase tracking-widest">
              Anti-Maturity Protocol
            </span>
          </div>

          {mainLoading || !lpiData ? (
            <div className="grid grid-cols-2 gap-3">
              {[1,2,3,4].map(i => <Skeleton key={i} className="h-24" />)}
            </div>
          ) : (() => {
            const dec = lpiData.pool_type_decision ?? {}
            const TYPES = [
              { key: 'p1', label: 'P1 — Standard',   desc: 'Regular L1 → L6 dual-winner draw',    active: dec.p1?.active ?? false },
              { key: 'p2', label: 'P2 — Balanced',   desc: 'Constrained payout-range draw',         active: dec.p2?.active ?? false },
              { key: 'p3', label: 'P3 — SDE Active', desc: 'Sequential Dynamic Eviction engaged',   active: dec.p3?.active ?? false },
              { key: 'p4', label: 'P4 — Emergency',  desc: 'Emergency pool condensation mode',      active: dec.p4?.active ?? false },
            ]
            const sdeOn = dec.sde_active ?? TYPES[2].active
            return (
              <>
                {sdeOn && (
                  <div className="mb-4 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-semibold">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    SDE Protocol Active — pools with L4-flagged members will route to P3/P4
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3">
                  {TYPES.map(({ key, label, desc, active }) => (
                    <div key={key} className={`rounded-xl p-4 border-2 transition-all ${
                      active
                        ? 'bg-blue-50 border-blue-300 shadow-sm shadow-blue-100'
                        : 'bg-slate-50/50 border-slate-100'
                    }`}>
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${active ? 'bg-blue-500 animate-pulse' : 'bg-slate-200'}`} />
                        <p className={`text-sm font-bold leading-none ${active ? 'text-blue-800' : 'text-slate-400'}`}>
                          {label}
                        </p>
                        {active && (
                          <span className="ml-auto text-[8px] font-black bg-blue-600 text-white px-1.5 py-0.5 rounded-full uppercase tracking-widest flex-shrink-0">
                            ON
                          </span>
                        )}
                      </div>
                      <p className={`text-xs leading-snug ${active ? 'text-blue-600' : 'text-slate-400'}`}>
                        {desc}
                      </p>
                    </div>
                  ))}
                </div>
                {dec.recommended_types?.length > 0 && (
                  <p className="mt-3 text-[11px] text-slate-400 text-right">
                    Recommended: {dec.recommended_types.join(', ')}
                  </p>
                )}
              </>
            )
          })()}
        </div>
      </div>

      {/* ── 5. Charts ─────────────────────────────────────────────────────── */}

      {/* Period picker */}
      <div className="flex items-center justify-end gap-2">
        <span className="text-xs text-slate-400 mr-1">Chart period:</span>
        {[
          { label: '30D', value: 30  },
          { label: '90D', value: 90  },
          { label: '1Y',  value: 365 },
        ].map(({ label, value }) => (
          <button
            key={value}
            onClick={() => setChartDays(value)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
              chartDays === value
                ? 'bg-violet-600 text-white shadow-sm'
                : 'bg-white text-slate-500 border border-slate-200 hover:bg-slate-50'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-5">

        {/* Line/Area — System Growth */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-blue-500" />
            <h2 className="font-semibold text-slate-800">System Growth</h2>
            <span className="ml-auto text-xs text-slate-400">New registrations</span>
          </div>
          {loading.charts ? (
            <div className="p-6"><Skeleton className="h-56" /></div>
          ) : errors.charts ? (
            <div className="p-6"><InlineError message={errors.charts} /></div>
          ) : chartPts.length === 0 ? (
            <p className="px-6 py-16 text-center text-sm text-slate-400">No data for this period</p>
          ) : (
            <div className="px-4 pt-4 pb-6">
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={chartPts} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
                  <defs>
                    <linearGradient id="gReg" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={C.blue} stopOpacity={0.18} />
                      <stop offset="95%" stopColor={C.blue} stopOpacity={0.01} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false} axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false} axisLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip content={<ChartTip />} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                  <Area
                    type="monotone"
                    dataKey="registrations"
                    name="New Members"
                    stroke={C.blue}
                    strokeWidth={2.5}
                    fill="url(#gReg)"
                    dot={false}
                    activeDot={{ r: 5, strokeWidth: 0 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Composed — Financial Flow (bars + net-profit line) */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
            <IndianRupee className="w-4 h-4 text-emerald-500" />
            <h2 className="font-semibold text-slate-800">Financial Flow</h2>
            <span className="ml-auto text-xs text-slate-400">DEP collected vs Payouts</span>
          </div>
          {loading.charts ? (
            <div className="p-6"><Skeleton className="h-56" /></div>
          ) : errors.charts ? (
            <div className="p-6"><InlineError message={errors.charts} /></div>
          ) : chartPts.length === 0 ? (
            <p className="px-6 py-16 text-center text-sm text-slate-400">No data for this period</p>
          ) : (
            <div className="px-4 pt-4 pb-6">
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={chartPts} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false} axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    tickLine={false} axisLine={false}
                    tickFormatter={v => v >= 1000 ? `₹${(v / 1000).toFixed(0)}K` : `₹${v}`}
                  />
                  <Tooltip content={<ChartTip currency />} />
                  <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                  <ReferenceLine y={0} stroke={C.slate} strokeDasharray="4 2" />
                  <Bar dataKey="dep"    name="DEP Collected"  fill={C.emerald} radius={[3, 3, 0, 0]} maxBarSize={20} />
                  <Bar dataKey="payout" name="Total Payout"   fill={C.rose}    radius={[3, 3, 0, 0]} maxBarSize={20} />
                  <Line
                    type="monotone"
                    dataKey="net"
                    name="Net Profit"
                    stroke={C.violet}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 5, strokeWidth: 0 }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* ── 5. Level-Wise Financial Distribution ────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-violet-500" />
          <h2 className="font-semibold text-slate-800">Level-Wise Financial Distribution</h2>
          <span className="ml-auto text-xs text-slate-400">Total Collected vs Distributed (₹)</span>
        </div>
        {mainLoading ? (
          <div className="p-6"><Skeleton className="h-56" /></div>
        ) : !levelBreakdown?.levels?.length ? (
          <p className="px-6 py-16 text-center text-sm text-slate-400">
            No draw history yet — run draws to populate level-wise data
          </p>
        ) : (
          <div className="px-4 pt-4 pb-6">
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart
                data={levelBreakdown.levels.map(l => ({
                  name:        `L${l.level}`,
                  collected:   l.total_collected_inr,
                  distributed: l.total_distributed_inr,
                  winners:     l.winners_count,
                  avg:         l.avg_payout_inr,
                }))}
                margin={{ top: 4, right: 4, bottom: 0, left: -8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 11, fill: '#64748b', fontWeight: 600 }}
                  tickLine={false} axisLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  tickLine={false} axisLine={false}
                  tickFormatter={v => v >= 1000 ? `₹${(v / 1000).toFixed(0)}K` : `₹${v}`}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null
                    return (
                      <div className="bg-white border border-slate-200 rounded-lg shadow-lg px-3 py-2 text-xs">
                        <p className="font-bold text-slate-700 mb-1">{label}</p>
                        {payload.map(p => (
                          <p key={p.dataKey} style={{ color: p.fill || p.stroke }}>
                            {p.name}: ₹{Number(p.value).toLocaleString('en-IN')}
                          </p>
                        ))}
                        {payload[0]?.payload?.winners > 0 && (
                          <p className="text-slate-400 mt-1 pt-1 border-t border-slate-100">
                            {payload[0].payload.winners} winner{payload[0].payload.winners !== 1 ? 's' : ''}
                            {' · '}avg ₹{Number(payload[0].payload.avg).toLocaleString('en-IN')}
                          </p>
                        )}
                      </div>
                    )
                  }}
                />
                <Legend iconType="square" iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 10 }} />
                <Bar dataKey="collected"   name="Collected From"   fill={C.blue}    radius={[3, 3, 0, 0]} maxBarSize={28} />
                <Bar dataKey="distributed" name="Distributed To"   fill={C.rose}    radius={[3, 3, 0, 0]} maxBarSize={28} />
              </ComposedChart>
            </ResponsiveContainer>

            {/* Dense summary table below chart */}
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left py-2 px-3 font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Level</th>
                    <th className="text-right py-2 px-3 font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Winners</th>
                    <th className="text-right py-2 px-3 font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Collected</th>
                    <th className="text-right py-2 px-3 font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Distributed</th>
                    <th className="text-right py-2 px-3 font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Avg Payout</th>
                    <th className="text-right py-2 px-3 font-semibold text-slate-500 uppercase tracking-wide text-[10px]">Net Margin</th>
                  </tr>
                </thead>
                <tbody>
                  {levelBreakdown.levels.map(l => {
                    const margin = l.total_collected_inr > 0
                      ? ((l.total_collected_inr - l.total_distributed_inr) / l.total_collected_inr * 100)
                      : 0
                    return (
                      <tr key={l.level} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
                        <td className="py-2 px-3">
                          <LevelBadge level={l.level} />
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-slate-700 font-medium">
                          {l.winners_count.toLocaleString()}
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-blue-600">
                          {INR(l.total_collected_inr)}
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-rose-500">
                          {INR(l.total_distributed_inr)}
                        </td>
                        <td className="py-2 px-3 text-right tabular-nums text-slate-500">
                          {INR(l.avg_payout_inr)}
                        </td>
                        <td className={`py-2 px-3 text-right tabular-nums font-semibold ${margin >= 0 ? 'text-emerald-600' : 'text-rose-500'}`}>
                          {margin >= 0 ? '+' : ''}{margin.toFixed(1)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* ── 6. Pool Analytics Table ───────────────────────────────────────── */}
      <SectionCard
        title="Pool Analytics"
        icon={Layers}
        iconColor="text-blue-500"
        action={
          poolStats && (
            <span className="text-xs text-slate-400">
              {NUM(poolStats.total_pools)} pools · {NUM(poolStats.active_pools_count)} active
            </span>
          )
        }
      >
        {mainLoading ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3].map(i => <Skeleton key={i} className="h-12" />)}
          </div>
        ) : errors.pools ? (
          <div className="p-6"><InlineError message={errors.pools} /></div>
        ) : !poolStats?.pools?.length ? (
          <p className="px-6 py-12 text-center text-sm text-slate-400">No pools found</p>
        ) : (
          <>
            {/* Global summary strip */}
            <div className="grid grid-cols-4 divide-x divide-slate-100 border-b border-slate-100 bg-slate-50/50">
              {[
                { label: 'Total Pools',     value: NUM(poolStats.total_pools)            },
                { label: 'Total Collected', value: INR(poolStats.global_collection_inr)  },
                { label: 'Total Distributed', value: INR(poolStats.global_distribution_inr) },
                { label: 'Net Profit',      value: INR(poolStats.global_profit_inr)      },
              ].map(({ label, value }) => (
                <div key={label} className="px-6 py-3 text-center">
                  <p className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</p>
                  <p className="text-sm font-bold text-slate-800 tabular-nums mt-0.5">{value}</p>
                </div>
              ))}
            </div>

            {/* Per-pool rows */}
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="w-8 px-4 py-3" />
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Pool</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                  <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Members</th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Deposited</th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">This Week</th>
                  <th className="text-right pr-6 px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Max Liability</th>
                  <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Draw Type</th>
                  <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">L4 Flag</th>
                  <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Week Done</th>
                </tr>
              </thead>
              <tbody>
                {poolStats.pools.map((pool, i) => (
                  <Fragment key={pool.pool_id}>
                    {/* Pool summary row */}
                    <tr
                      onClick={() => togglePool(pool.pool_id)}
                      className={`cursor-pointer transition-colors border-b border-slate-50 ${
                        i % 2 === 0 ? 'bg-white' : 'bg-slate-50/30'
                      } hover:bg-blue-50/40`}
                    >
                      <td className="px-4 py-3.5 text-slate-400">
                        {expandedPools.has(pool.pool_id)
                          ? <ChevronDown  className="w-4 h-4" />
                          : <ChevronRight className="w-4 h-4" />
                        }
                      </td>
                      <td className="px-4 py-3.5">
                        <p className="font-semibold text-slate-800">{pool.pool_name}</p>
                        <p className="text-[11px] text-slate-400 mt-0.5">ID #{pool.pool_id}</p>
                      </td>
                      <td className="px-4 py-3.5">
                        <StatusBadge status={pool.pool_status} />
                      </td>
                      <td className="px-4 py-3.5 text-center">
                        <span className={`inline-flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold ${
                          pool.current_member_count === 12
                            ? 'bg-blue-100 text-blue-700'
                            : 'bg-slate-100 text-slate-600'
                        }`}>
                          {pool.current_member_count}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono text-slate-700 tabular-nums">
                        {INR(pool.total_deposited_by_members_inr)}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                        <span className={
                          fP(pool.weekly_deposits_inr) > 0
                            ? 'text-emerald-600 font-semibold'
                            : 'text-slate-400'
                        }>
                          {INR(pool.weekly_deposits_inr)}
                        </span>
                      </td>
                      <td className="px-4 pr-6 py-3.5 text-right font-mono text-amber-600 tabular-nums">
                        {INR(pool.potential_payout_liability_inr)}
                      </td>

                      {/* Draw Type */}
                      <td className="px-4 py-3.5 text-center">
                        {pool.pool_draw_type ? (
                          <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-violet-50 text-violet-700 border border-violet-200">
                            {pool.pool_draw_type}
                          </span>
                        ) : <span className="text-slate-300 text-xs">—</span>}
                      </td>

                      {/* L4 Flagged */}
                      <td className="px-4 py-3.5 text-center">
                        {pool.contains_flagged_l4 ? (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-700 border border-red-200">
                            <AlertTriangle className="w-3 h-3" />L4
                          </span>
                        ) : <span className="text-slate-300 text-xs">—</span>}
                      </td>

                      {/* Draw completed this week */}
                      <td className="px-4 py-3.5 text-center">
                        {pool.draw_completed_this_week
                          ? <CheckCircle2 className="w-4 h-4 text-emerald-500 mx-auto" />
                          : <span className="text-slate-300 text-xs">—</span>
                        }
                      </td>
                    </tr>

                    {/* Expanded member sub-table */}
                    {expandedPools.has(pool.pool_id) && (
                      <tr className="bg-blue-50/10">
                        <td colSpan={10} className="px-6 py-4">
                          {pool.members?.length > 0 ? (
                            <div className="rounded-xl border border-blue-100 bg-white overflow-hidden shadow-sm">
                              <div className="px-4 py-2.5 bg-blue-50/70 border-b border-blue-100 flex items-center justify-between">
                                <p className="text-xs font-semibold text-blue-700">
                                  {pool.pool_name} · {pool.members.length} members
                                </p>
                                <p className="text-[10px] text-blue-500">
                                  {pool.members.filter(m => m.weekly_payment_status === 'Paid').length}/{pool.members.length} paid this week
                                </p>
                              </div>
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="border-b border-slate-100 bg-slate-50/60">
                                    <th className="text-left px-4 py-2 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Username</th>
                                    <th className="text-left px-4 py-2 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Name</th>
                                    <th className="text-center px-4 py-2 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Level</th>
                                    <th className="text-center px-4 py-2 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Payment</th>
                                    <th className="text-right px-4 py-2 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Win Value</th>
                                    <th className="text-right px-4 py-2 font-semibold text-slate-400 uppercase tracking-wide text-[10px]">Joined</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {pool.members.map((m, mi) => (
                                    <tr
                                      key={m.user_id}
                                      className={`border-b last:border-0 border-slate-50 ${
                                        mi % 2 === 0 ? 'bg-white' : 'bg-slate-50/30'
                                      }`}
                                    >
                                      <td className="px-4 py-2.5 font-semibold text-slate-800">
                                        @{m.username}
                                      </td>
                                      <td className="px-4 py-2.5 text-slate-600">{m.name}</td>
                                      <td className="px-4 py-2.5 text-center">
                                        <LevelBadge level={m.current_level} />
                                      </td>
                                      <td className="px-4 py-2.5 text-center">
                                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${
                                          m.weekly_payment_status === 'Paid'
                                            ? 'bg-emerald-50 text-emerald-700'
                                            : 'bg-red-50 text-red-700'
                                        }`}>
                                          {m.weekly_payment_status}
                                        </span>
                                      </td>
                                      <td className="px-4 py-2.5 text-right font-mono font-semibold text-violet-700">
                                        {INR(LEVEL_PAYOUT[m.current_level] ?? 0)}
                                      </td>
                                      <td className="px-4 py-2.5 text-right text-slate-400">
                                        {new Date(m.join_date).toLocaleDateString('en-IN', {
                                          day: '2-digit', month: 'short',
                                        })}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <p className="text-xs text-slate-400 text-center py-4">
                              No active members in this pool
                            </p>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </>
        )}
      </SectionCard>

      {/* ── 6. Pending Actions ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-5">

        {/* WIT — Approve / Reject queue */}
        <SectionCard
          title="Pending Payouts (WIT)"
          icon={IndianRupee}
          iconColor="text-rose-500"
          action={
            <span className={`text-xs px-2 py-0.5 rounded-full font-semibold border ${
              witTokens.length > 0
                ? 'bg-rose-50 text-rose-700 border-rose-200'
                : 'bg-slate-50 text-slate-500 border-slate-200'
            }`}>
              {witTokens.length} pending
            </span>
          }
        >
          {loading.actions ? (
            <div className="p-4 space-y-2">
              {[1, 2, 3].map(i => <Skeleton key={i} className="h-14" />)}
            </div>
          ) : errors.actions ? (
            <div className="p-6"><InlineError message={errors.actions} /></div>
          ) : witTokens.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <CheckCheck className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
              <p className="text-sm text-slate-400">All payouts settled — nothing pending</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-50 max-h-80 overflow-y-auto">
              {witTokens.map(token => (
                <PendingTokenRow key={token.id} token={token}>
                  <button
                    onClick={() => handleWit(token.id, 'approve')}
                    disabled={actioning.has(token.id)}
                    title="Mark cash as paid — burns this token"
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg text-xs font-semibold transition disabled:opacity-50 shadow-sm"
                  >
                    {actioning.has(token.id)
                      ? <Spinner className="w-3 h-3" />
                      : <CheckCircle2 className="w-3 h-3" />
                    }
                    Approve
                  </button>
                  <button
                    onClick={() => handleWit(token.id, 'reject')}
                    disabled={actioning.has(token.id)}
                    title="Void this payout — fraud / admin override"
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white hover:bg-red-50 text-red-600 border border-red-200 rounded-lg text-xs font-semibold transition disabled:opacity-50"
                  >
                    <XCircle className="w-3 h-3" />
                    Reject
                  </button>
                </PendingTokenRow>
              ))}
            </div>
          )}
        </SectionCard>

        {/* REF — Pay Out queue */}
        <SectionCard
          title="Referral Rewards (REF)"
          icon={Shield}
          iconColor="text-violet-500"
          action={
            <span className={`text-xs px-2 py-0.5 rounded-full font-semibold border ${
              refTokens.length > 0
                ? 'bg-violet-50 text-violet-700 border-violet-200'
                : 'bg-slate-50 text-slate-500 border-slate-200'
            }`}>
              {refTokens.length} pending
            </span>
          }
        >
          {loading.actions ? (
            <div className="p-4 space-y-2">
              {[1, 2].map(i => <Skeleton key={i} className="h-14" />)}
            </div>
          ) : errors.actions ? (
            <div className="p-6"><InlineError message={errors.actions} /></div>
          ) : refTokens.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <CheckCheck className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
              <p className="text-sm text-slate-400">No referral rewards outstanding</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-50 max-h-80 overflow-y-auto">
              {refTokens.map(token => (
                <PendingTokenRow key={token.id} token={token}>
                  <button
                    onClick={() => handleRef(token.code, token.id)}
                    disabled={actioning.has(token.id)}
                    title="Confirm referral cash has been paid"
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-500 hover:bg-violet-600 text-white rounded-lg text-xs font-semibold transition disabled:opacity-50 shadow-sm"
                  >
                    {actioning.has(token.id)
                      ? <Spinner className="w-3 h-3" />
                      : <CheckCircle2 className="w-3 h-3" />
                    }
                    Pay Out
                  </button>
                </PendingTokenRow>
              ))}
            </div>
          )}
        </SectionCard>
      </div>

    </motion.div>
  )
}
