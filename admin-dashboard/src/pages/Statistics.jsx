import { useState, useEffect, useCallback, Fragment } from 'react'
import {
  BarChart3, TrendingUp, TrendingDown, RefreshCw,
  IndianRupee, Users, Layers, Clock, Zap, AlertTriangle,
  CheckCircle2, XCircle, Shield, Target, Activity,
  ChevronDown, ChevronRight, CheckCheck, AlertCircle,
  Calculator,
} from 'lucide-react'
import {
  ResponsiveContainer,
  AreaChart, Area,
  ComposedChart, Bar, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
} from 'recharts'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import {
  getFinancials, getPoolStats, getTokenStats,
  getAiForecast, getChartData,
  getAdminTokens, updateTokenStatus, burnToken,
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
// Main page
// ─────────────────────────────────────────────────────────────────────────────

export default function Statistics() {
  const toast = useToast()

  // ── Data ──────────────────────────────────────────────────────────────────
  const [financials, setFinancials] = useState(null)
  const [poolStats,  setPoolStats]  = useState(null)
  const [forecast,   setForecast]   = useState(null)
  const [chartData,  setChartData]  = useState(null)
  const [witTokens,  setWitTokens]  = useState([])
  const [refTokens,  setRefTokens]  = useState([])

  // ── Loading / error ───────────────────────────────────────────────────────
  const [loading, setLoading] = useState({ main: true, charts: true, actions: true })
  const [errors,  setErrors]  = useState({})
  const [refreshing,  setRefreshing]  = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)

  // ── UI state ──────────────────────────────────────────────────────────────
  const [chartDays,     setChartDays]     = useState(30)
  const [expandedPools, setExpandedPools] = useState(new Set())
  const [actioning,     setActioning]     = useState(new Set())  // token IDs in-flight

  // ─────────────────────────────────────────────────────────────────────────
  // Fetch helpers
  // ─────────────────────────────────────────────────────────────────────────

  const fetchCore = useCallback(async (silent = false) => {
    silent ? setRefreshing(true) : setLoading(l => ({ ...l, main: true }))
    setErrors(e => ({ ...e, financials: null, pools: null, forecast: null }))

    const [finR, poolR, foreR] = await Promise.allSettled([
      getFinancials(),
      getPoolStats(),
      getAiForecast(),
    ])

    if (finR.status  === 'fulfilled') setFinancials(finR.value.data)
    else setErrors(e => ({ ...e, financials: finR.reason?.response?.data?.detail ?? 'Load failed' }))

    if (poolR.status === 'fulfilled') setPoolStats(poolR.value.data)
    else setErrors(e => ({ ...e, pools: poolR.reason?.response?.data?.detail ?? 'Load failed' }))

    if (foreR.status === 'fulfilled') setForecast(foreR.value.data)
    else setErrors(e => ({ ...e, forecast: foreR.reason?.response?.data?.detail ?? 'Load failed' }))

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

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="p-8 space-y-8">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
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
      </div>

      {/* ── 1. KPI Card Grid ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-5">
        <KPICard
          loading={mainLoading}
          label="In-Hand Liquidity"
          value={INR(financials?.in_hand_liquidity_inr)}
          sub="DEP received minus all payouts made"
          icon={IndianRupee}
          iconBg="bg-emerald-50" iconColor="text-emerald-600"
          trend={!mainLoading
            ? (fP(financials?.in_hand_liquidity_inr) >= 0 ? 'positive' : 'negative')
            : null}
        />
        <KPICard
          loading={mainLoading}
          label="Total Collected"
          value={INR(financials?.total_collected_inr)}
          sub="Sum of all burned Deposit tokens"
          icon={TrendingUp}
          iconBg="bg-blue-50" iconColor="text-blue-600"
        />
        <KPICard
          loading={mainLoading}
          label="Organiser Revenue"
          value={INR(financials?.maintenance_fees_total_inr)}
          sub={`${NUM(financials?.maintenance_fees_count)} draw fees × ₹500`}
          icon={Zap}
          iconBg="bg-violet-50" iconColor="text-violet-600"
          trend="positive"
        />
        <KPICard
          loading={mainLoading}
          label="Doomsday Liability"
          value={INR(financials?.doomsday_liability_inr)}
          sub="Max refund if all active members exit today"
          icon={AlertTriangle}
          iconBg="bg-red-50" iconColor="text-red-500"
          trend="negative"
        />
        <KPICard
          loading={mainLoading}
          label="Outstanding Liability"
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
          label="Total Registered"
          value={NUM(totalRegistered)}
          sub={!mainLoading
            ? `${NUM(financials?.active_user_count)} active · ${NUM(financials?.waitlist_count)} waitlist · ${NUM(financials?.eliminated_count)} eliminated`
            : ''}
          icon={Users}
          iconBg="bg-slate-50" iconColor="text-slate-600"
        />
      </div>

      {/* ── 2. Liability-Adjusted Profit Calculator ──────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">

        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2"
          style={{ background: 'linear-gradient(90deg, #f0fdf4 0%, #ffffff 60%)' }}>
          <Calculator className="w-4 h-4 text-emerald-600 flex-shrink-0" />
          <h2 className="font-semibold text-slate-800">Liability-Adjusted Profit Calculator</h2>
          <span className="ml-auto text-[10px] uppercase tracking-widest text-slate-400 font-semibold">
            Pure Net Yield
          </span>
        </div>

        <div className="p-6 space-y-5">

          {mainLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-24" />
              <Skeleton className="h-16" />
              <Skeleton className="h-20" />
            </div>
          ) : (
            <>
              {/* ── Equation row: Inflow − Outflow − Liability = Profit ─────── */}
              <div className="flex items-stretch gap-2">

                {/* Cash Inflow */}
                <div className="flex-1 bg-emerald-50 border border-emerald-200 rounded-2xl p-4 text-center">
                  <p className="text-[10px] font-semibold text-emerald-600 uppercase tracking-wider mb-1.5">
                    Total Cash Inflow
                  </p>
                  <p className="text-xl font-black text-emerald-700 tabular-nums leading-none">
                    {INR(financials?.total_cash_inflow_inr)}
                  </p>
                  <p className="text-[10px] text-emerald-500 mt-1.5">
                    All DEP tokens redeemed
                  </p>
                </div>

                <div className="flex items-center text-slate-300 font-bold text-xl px-1 flex-shrink-0">−</div>

                {/* Cash Outflow */}
                <div className="flex-1 bg-red-50 border border-red-200 rounded-2xl p-4 text-center">
                  <p className="text-[10px] font-semibold text-red-600 uppercase tracking-wider mb-1.5">
                    Total Cash Outflow
                  </p>
                  <p className="text-xl font-black text-red-700 tabular-nums leading-none">
                    {INR(financials?.total_cash_outflow_inr)}
                  </p>
                  <p className="text-[10px] text-red-400 mt-1.5">
                    WIT + Referral_Withdraw paid
                  </p>
                </div>

                <div className="flex items-center text-slate-300 font-bold text-xl px-1 flex-shrink-0">−</div>

                {/* Active Liability */}
                <div className="flex-1 bg-amber-50 border border-amber-200 rounded-2xl p-4 text-center">
                  <p className="text-[10px] font-semibold text-amber-600 uppercase tracking-wider mb-1.5">
                    Active Liability
                  </p>
                  <p className="text-xl font-black text-amber-700 tabular-nums leading-none">
                    {INR(financials?.current_active_liability_inr)}
                  </p>
                  <p className="text-[10px] text-amber-500 mt-1.5">
                    Principal owed · Active + Waitlist
                  </p>
                </div>

                <div className="flex items-center text-slate-300 font-bold text-xl px-1 flex-shrink-0">=</div>

                {/* Pure Realized Profit — hero tile */}
                <div
                  className="flex-1 rounded-2xl p-4 text-center border-2"
                  style={pureProfit >= 0 ? {
                    background: '#059669',
                    borderColor: '#047857',
                  } : {
                    background: '#dc2626',
                    borderColor: '#b91c1c',
                  }}
                >
                  <p className="text-[10px] font-semibold text-white/70 uppercase tracking-wider mb-1.5">
                    Pure Realized Profit
                  </p>
                  <p className="text-xl font-black text-white tabular-nums leading-none">
                    {INR(financials?.pure_realized_profit_inr)}
                  </p>
                  <p className="text-[10px] text-white/60 mt-1.5">
                    {pureProfit >= 0 ? 'Net yield captured ✓' : 'Deficit — monitor closely ⚠'}
                  </p>
                </div>
              </div>

              {/* ── Formula explanation ─────────────────────────────────────── */}
              <div className="bg-slate-50 rounded-xl px-4 py-3 border border-slate-100">
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  <span className="font-semibold text-slate-700">Active Liability</span> = exact principal
                  the organiser owes if every current participant claims a refund today.
                  Active <span className="font-mono text-amber-600">Paid</span> Level L →{' '}
                  <span className="font-mono text-amber-600">L × ₹1,000</span>. &nbsp;
                  Active <span className="font-mono text-red-500">Unpaid</span> Level L →{' '}
                  <span className="font-mono text-amber-600">(L−1) × ₹1,000</span>. &nbsp;
                  Waitlist → <span className="font-mono text-amber-600">₹1,000</span>.
                  &nbsp;·&nbsp; Cash Outflow counts only{' '}
                  <span className="font-mono text-slate-600">Withdraw</span> (WIT) and{' '}
                  <span className="font-mono text-slate-600">Referral_Withdraw</span> tokens with
                  status <span className="font-mono text-slate-600">Burned</span>.
                </p>
              </div>

              {/* ── Weekly Rolling Surplus ──────────────────────────────────── */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <Clock className="w-3.5 h-3.5 text-violet-500 flex-shrink-0" />
                  <p className="text-xs font-semibold text-slate-600 uppercase tracking-wider">
                    Weekly Rolling Surplus
                  </p>
                  <span className="text-[10px] text-slate-400 font-mono">
                    Since {financials?.week_start_date ?? '—'} (Mon 00:00 UTC)
                  </span>
                </div>

                <div className="flex items-stretch gap-2">
                  {/* This week collections */}
                  <div className="flex-1 bg-blue-50 border border-blue-100 rounded-xl p-3 text-center">
                    <p className="text-[10px] font-semibold text-blue-600 uppercase tracking-wider mb-1">
                      This Week Collections
                    </p>
                    <p className="text-lg font-black text-blue-700 tabular-nums leading-none">
                      {INR(financials?.weekly_collections_inr)}
                    </p>
                    <p className="text-[10px] text-blue-400 mt-1">DEP tokens redeemed</p>
                  </div>

                  <div className="flex items-center text-slate-300 font-bold text-lg px-1 flex-shrink-0">−</div>

                  {/* This week payouts */}
                  <div className="flex-1 bg-rose-50 border border-rose-100 rounded-xl p-3 text-center">
                    <p className="text-[10px] font-semibold text-rose-600 uppercase tracking-wider mb-1">
                      This Week Payouts
                    </p>
                    <p className="text-lg font-black text-rose-700 tabular-nums leading-none">
                      {INR(financials?.weekly_payouts_inr)}
                    </p>
                    <p className="text-[10px] text-rose-400 mt-1">WIT tokens burned</p>
                  </div>

                  <div className="flex items-center text-slate-300 font-bold text-lg px-1 flex-shrink-0">=</div>

                  {/* Weekly surplus */}
                  <div
                    className={`flex-1 rounded-xl p-3 text-center border ${
                      weeklySurplus >= 0
                        ? 'bg-violet-50 border-violet-200'
                        : 'bg-red-50 border-red-200'
                    }`}
                  >
                    <p className={`text-[10px] font-semibold uppercase tracking-wider mb-1 ${
                      weeklySurplus >= 0 ? 'text-violet-600' : 'text-red-600'
                    }`}>
                      Rolling Surplus
                    </p>
                    <p className={`text-lg font-black tabular-nums leading-none ${
                      weeklySurplus >= 0 ? 'text-violet-700' : 'text-red-700'
                    }`}>
                      {INR(financials?.weekly_rolling_surplus_inr)}
                    </p>
                    <p className={`text-[10px] mt-1 ${
                      weeklySurplus >= 0 ? 'text-violet-400' : 'text-red-400'
                    }`}>
                      {weeklySurplus >= 0
                        ? `+${INR_COMPACT(weeklySurplus)} surplus`
                        : `${INR_COMPACT(weeklySurplus)} deficit`}
                    </p>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
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

      {/* ── 4. Charts ─────────────────────────────────────────────────────── */}

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

      {/* ── 5. Pool Analytics Table ───────────────────────────────────────── */}
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
                    </tr>

                    {/* Expanded member sub-table */}
                    {expandedPools.has(pool.pool_id) && (
                      <tr className="bg-blue-50/10">
                        <td colSpan={7} className="px-6 py-4">
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

    </div>
  )
}
