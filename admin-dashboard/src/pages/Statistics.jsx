import { useState, useEffect, useCallback, Fragment } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BarChart3, TrendingUp, TrendingDown, RefreshCw,
  IndianRupee, Users, Layers, Clock, Zap, AlertTriangle,
  CheckCircle2, XCircle, Shield, Target, Activity,
  ChevronDown, ChevronRight, CheckCheck, AlertCircle,
  Calculator, Info, Cpu, CalendarRange, Download, TableProperties,
  Gavel, DollarSign, Trophy,
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
  const SUB_TABS = [
    { id: 'overview',      label: 'Overview',            icon: BarChart3    },
    { id: 'weekly_pools',  label: 'Weekly Pool Reports', icon: CalendarRange },
    { id: 'live_stats',    label: 'Live Stats',           icon: Activity     },
    { id: 'level_map',     label: 'Level Map',            icon: Layers       },
    { id: 'winners',       label: 'Winners Analytics',    icon: Target       },
    { id: 'projections',   label: 'Projections',          icon: TrendingUp   },
    { id: 'pauses',        label: 'System Pauses',        icon: Clock        },
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
        {subTab === 'weekly_pools' && <WeeklyPoolReportsPanel toast={toast} />}
        {subTab === 'live_stats'   && <LiveStatsPanel   toast={toast} />}
        {subTab === 'level_map'    && <LevelMapPanel    toast={toast} />}
        {subTab === 'winners'      && <WinnersPanel     toast={toast} />}
        {subTab === 'projections'  && <ProjectionsPanel toast={toast} />}
        {subTab === 'pauses'       && <PausesPanel      toast={toast} />}
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
