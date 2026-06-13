import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Activity, Database, Wifi, WifiOff, RefreshCw, CheckCircle2,
  XCircle, AlertTriangle, IndianRupee, Layers, Clock, Zap,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import { getStats, getAdminTokens, getPipelineHealth, BASE_URL } from '../api/client'
import api from '../api/client'

const INR = v =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v ?? 0)

const REFRESH_INTERVAL = 30   // seconds

// ─── Status pill ──────────────────────────────────────────────────────────────
function HealthBadge({ status }) {
  if (status === 'checking')
    return <span className="inline-flex items-center gap-1 text-xs text-slate-400"><Spinner className="w-3 h-3" />Checking…</span>
  if (status === 'ok')
    return <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600"><CheckCircle2 className="w-3.5 h-3.5" />Online</span>
  if (status === 'warn')
    return <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber-600"><AlertTriangle className="w-3.5 h-3.5" />Degraded</span>
  return <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600"><XCircle className="w-3.5 h-3.5" />Offline</span>
}

// ─── Metric row ───────────────────────────────────────────────────────────────
function MetricRow({ label, value, sub, accent }) {
  return (
    <div className="flex items-center justify-between py-3 border-b last:border-0 border-slate-100">
      <div>
        <p className="text-sm font-medium text-slate-700">{label}</p>
        {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
      </div>
      <p className={`text-lg font-bold tabular-nums ${accent ?? 'text-slate-800'}`}>{value}</p>
    </div>
  )
}

// ─── Health card ─────────────────────────────────────────────────────────────
function HealthCard({ icon: Icon, iconBg, iconColor, title, sub, status, latency, detail }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className={`${iconBg} p-3 rounded-xl`}>
            <Icon className={`w-5 h-5 ${iconColor}`} />
          </div>
          <div>
            <p className="font-semibold text-slate-800 text-sm">{title}</p>
            <p className="text-xs text-slate-400 mt-0.5">{sub}</p>
          </div>
        </div>
        <div className="text-right flex-shrink-0">
          <HealthBadge status={status} />
          {latency != null && status === 'ok' && (
            <p className="text-[10px] text-slate-400 mt-1">{latency} ms</p>
          )}
        </div>
      </div>
      {detail && (
        <p className="mt-3 text-xs text-red-500 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
          {detail}
        </p>
      )}
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
export default function Diagnostics() {
  // ── Health state ────────────────────────────────────────────────────────
  const [apiStatus,   setApiStatus]   = useState('checking')
  const [apiLatency,  setApiLatency]  = useState(null)
  const [apiDetail,   setApiDetail]   = useState(null)
  const [dbStatus,    setDbStatus]    = useState('checking')
  const [dbLatency,   setDbLatency]   = useState(null)
  const [dbDetail,    setDbDetail]    = useState(null)

  // ── Stats & liability ────────────────────────────────────────────────────
  const [stats,        setStats]        = useState(null)
  const [liability,    setLiability]    = useState(null)   // { witTotal, witCount, refTotal, refCount, depPending }
  const [pipeHealth,   setPipeHealth]   = useState(null)   // pipeline health snapshot
  const [loading,      setLoading]      = useState(true)
  const [lastChecked,  setLastChecked]  = useState(null)
  const [countdown,    setCountdown]    = useState(REFRESH_INTERVAL)
  const countdownRef = useRef(null)

  // ── Run all checks ───────────────────────────────────────────────────────
  const runChecks = useCallback(async () => {
    setLoading(true)
    setApiStatus('checking')
    setDbStatus('checking')

    try {
      // 1. API health — hit the public root
      const apiStart = performance.now()
      try {
        await api.get('/')
        setApiStatus('ok')
        setApiLatency(Math.round(performance.now() - apiStart))
        setApiDetail(null)
      } catch (err) {
        setApiStatus('error')
        setApiLatency(null)
        setApiDetail(err.message ?? 'Cannot reach API')
      }

      // 2. DB health — hit /admin/stats (authenticated, touches DB)
      const dbStart = performance.now()
      try {
        const res = await getStats()
        setDbStatus('ok')
        setDbLatency(Math.round(performance.now() - dbStart))
        setDbDetail(null)
        setStats(res.data)
      } catch (err) {
        setDbStatus('error')
        setDbLatency(null)
        setDbDetail(err.response?.data?.detail ?? err.message ?? 'DB query failed')
        setStats(null)
      }

      // 3. Token liability — active Withdraw + Referral tokens
      try {
        const [witRes, refRes, depRes] = await Promise.all([
          getAdminTokens({ type: 'Withdraw', status: 'Active', limit: 1000 }),
          getAdminTokens({ type: 'Referral', status: 'Active', limit: 1000 }),
          getAdminTokens({ type: 'Deposit',  status: 'Active', limit: 1000 }),
        ])
        const sum = arr => arr.reduce((s, t) => s + parseFloat(t.value_inr ?? 0), 0)
        setLiability({
          witTotal:   sum(witRes.data),
          witCount:   witRes.data.length,
          refTotal:   sum(refRes.data),
          refCount:   refRes.data.length,
          depPending: depRes.data.length,
        })
      } catch {
        setLiability(null)
      }

      // 4. Pipeline health — DB connection pool, injection tasks, data integrity
      try {
        const phRes = await getPipelineHealth()
        setPipeHealth(phRes.data)
      } catch {
        setPipeHealth(null)
      }
    } finally {
      // Guaranteed to run even if an unexpected error escapes the inner try-catch blocks.
      setLoading(false)
      setLastChecked(new Date())
      setCountdown(REFRESH_INTERVAL)
    }
  }, [])

  // Initial + auto-refresh
  useEffect(() => {
    runChecks()
  }, [runChecks])

  // Countdown ticker
  useEffect(() => {
    countdownRef.current = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) { runChecks(); return REFRESH_INTERVAL }
        return c - 1
      })
    }, 1000)
    return () => clearInterval(countdownRef.current)
  }, [runChecks])

  const overallStatus =
    apiStatus === 'error' || dbStatus === 'error' ? 'error' :
    apiStatus === 'warn'  || dbStatus === 'warn'  ? 'warn'  :
    apiStatus === 'ok'    && dbStatus === 'ok'    ? 'ok'    : 'checking'

  const totalLiability = liability ? liability.witTotal + liability.refTotal : 0

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Activity className="w-6 h-6 text-violet-600" />
            System Diagnostics
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {lastChecked ? `Last checked ${lastChecked.toLocaleTimeString()} · refreshing in ${countdown}s` : 'Running checks…'}
          </p>
        </div>
        <button
          onClick={runChecks}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Run Checks
        </button>
      </div>

      {/* Overall status banner */}
      <div className={`flex items-center gap-3 rounded-2xl px-6 py-4 border ${
        overallStatus === 'ok'       ? 'bg-emerald-50  border-emerald-200' :
        overallStatus === 'warn'     ? 'bg-amber-50    border-amber-200'   :
        overallStatus === 'error'    ? 'bg-red-50      border-red-200'     :
                                       'bg-slate-50    border-slate-200'
      }`}>
        {overallStatus === 'ok'    && <CheckCircle2  className="w-5 h-5 text-emerald-600 flex-shrink-0" />}
        {overallStatus === 'warn'  && <AlertTriangle className="w-5 h-5 text-amber-500  flex-shrink-0" />}
        {overallStatus === 'error' && <XCircle       className="w-5 h-5 text-red-500    flex-shrink-0" />}
        {overallStatus === 'checking' && <Spinner    className="w-5 h-5                flex-shrink-0" />}
        <div>
          <p className="font-semibold text-slate-800 text-sm">
            {overallStatus === 'ok'       ? 'All systems operational'   :
             overallStatus === 'warn'     ? 'System degraded'           :
             overallStatus === 'error'    ? 'System fault detected'     :
                                           'Running diagnostics…'      }
          </p>
          <p className="text-xs text-slate-500 mt-0.5">
            {BASE_URL.replace(/^https?:\/\//, '')}
          </p>
        </div>
      </div>

      {/* Health cards */}
      <div className="grid grid-cols-2 gap-5">
        <HealthCard
          icon={Wifi}
          iconBg="bg-blue-50"
          iconColor="text-blue-600"
          title="API Gateway"
          sub={`${BASE_URL.replace(/^https?:\/\//, '')}`}
          status={apiStatus}
          latency={apiLatency}
          detail={apiDetail}
        />
        <HealthCard
          icon={Database}
          iconBg="bg-violet-50"
          iconColor="text-violet-600"
          title="Database (Supabase)"
          sub="PostgreSQL via /admin/stats"
          status={dbStatus}
          latency={dbLatency}
          detail={dbDetail}
        />
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* ── System metrics (from /admin/stats) ── */}
        <div className="col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
            <Layers className="w-4 h-4 text-slate-400" />
            <h2 className="font-semibold text-slate-800">System Metrics</h2>
            {loading && <Spinner className="w-3.5 h-3.5 ml-auto" />}
          </div>
          {stats ? (
            <div className="px-6 divide-y divide-slate-100">
              <MetricRow
                label="Active Pool Members"
                value={stats.active_users}
                sub="Currently competing in pools"
                accent="text-blue-700"
              />
              <MetricRow
                label="Waitlist Queue"
                value={stats.waitlist_count}
                sub={`${Math.max(0, 24 - stats.waitlist_count)} more needed to open a new pool`}
                accent="text-amber-600"
              />
              <MetricRow
                label="Active Pools Running"
                value={stats.active_pools}
                sub="Each pool holds 12 members"
              />
              <MetricRow
                label="Total Capital Collected"
                value={INR(stats.total_capital_inr)}
                sub="Sum of all burned Deposit tokens"
                accent="text-emerald-700"
              />
              <MetricRow
                label="Tokens Issued (all-time)"
                value={stats.total_tokens_issued}
                sub={`${stats.active_tokens} still active (unredeemed)`}
              />
              <MetricRow
                label="Eliminated Members"
                value={stats.eliminated_count}
                sub="Eliminated or Eliminated_Won"
                accent="text-slate-500"
              />
            </div>
          ) : (
            <div className="px-6 py-12 text-center text-slate-400 text-sm">
              {loading ? 'Fetching metrics…' : 'Metrics unavailable — DB unreachable'}
            </div>
          )}
        </div>

        {/* ── Financial Exposure ── */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
            <IndianRupee className="w-4 h-4 text-slate-400" />
            <h2 className="font-semibold text-slate-800">Financial Exposure</h2>
          </div>

          {liability ? (
            <div className="px-6 py-2 space-y-1 divide-y divide-slate-100">
              {/* WIT liability */}
              <div className="py-4">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Pending Payouts</p>
                    <p className="mt-1 text-2xl font-bold text-red-600 tabular-nums">{INR(liability.witTotal)}</p>
                    <p className="text-xs text-slate-400 mt-0.5">{liability.witCount} WIT tokens outstanding</p>
                  </div>
                  <div className="bg-red-50 p-2 rounded-xl">
                    <IndianRupee className="w-5 h-5 text-red-500" />
                  </div>
                </div>
                {liability.witTotal > 0 && (
                  <div className="mt-3 flex items-center gap-1.5 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                    <p className="text-xs text-red-600">
                      {liability.witCount} winner payout{liability.witCount !== 1 ? 's' : ''} awaiting settlement
                    </p>
                  </div>
                )}
              </div>

              {/* REF outstanding */}
              <div className="py-4">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Referral Rewards</p>
                <p className="mt-1 text-xl font-bold text-amber-600 tabular-nums">{INR(liability.refTotal)}</p>
                <p className="text-xs text-slate-400 mt-0.5">{liability.refCount} REF tokens outstanding</p>
              </div>

              {/* Unused DEP */}
              <div className="py-4">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Unused Deposit Tokens</p>
                <p className="mt-1 text-xl font-bold text-slate-700 tabular-nums">{liability.depPending}</p>
                <p className="text-xs text-slate-400 mt-0.5">Generated but not yet redeemed</p>
              </div>

              {/* Total liability */}
              <div className="py-4">
                <div className="flex justify-between items-center">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Total Liability</p>
                  <p className="text-lg font-black text-slate-800 tabular-nums">{INR(totalLiability)}</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="px-6 py-12 text-center text-slate-400 text-sm">
              {loading ? 'Calculating…' : 'Data unavailable'}
            </div>
          )}
        </div>
      </div>

      {/* ── Pipeline Health Card ─────────────────────────────────────────────── */}
      {pipeHealth && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <div className="flex items-center gap-2 mb-5">
            <Activity className="w-4 h-4 text-violet-500" />
            <h2 className="font-semibold text-slate-800">Pipeline Health</h2>
            <span className="ml-auto text-[10px] font-mono text-slate-400">
              {lastChecked?.toLocaleTimeString()}
            </span>
          </div>
          {(() => {
            const pool = pipeHealth.db_pool ?? {}
            const totalCap  = pool.total_capacity ?? pool.pool_size ?? 40
            const checkedOut = pool.checked_out ?? 0
            const available  = Math.max(0, totalCap - checkedOut)
            const injRunning = pipeHealth.injection_tasks_running ?? 0
            const rows = [
              { label: 'DB Connections Free',  value: available,                           accent: available < 4 ? 'text-red-600' : 'text-emerald-600' },
              { label: 'DB Checked Out',        value: checkedOut,                          accent: checkedOut > 30 ? 'text-red-600' : 'text-blue-600' },
              { label: 'Waitlist Queue',         value: pipeHealth.waitlist_count ?? '—',   accent: 'text-amber-600' },
              { label: 'Active Users',           value: pipeHealth.active_users ?? '—',     accent: 'text-slate-700' },
              { label: 'Active Pools',           value: pipeHealth.pools_active ?? '—',     accent: 'text-violet-600' },
              { label: 'Under-Capacity Pools',   value: pipeHealth.pools_under_capacity ?? 0, accent: (pipeHealth.pools_under_capacity ?? 0) > 0 ? 'text-amber-600' : 'text-emerald-600' },
              { label: 'BG Injection Tasks',     value: injRunning,                         accent: injRunning > 0 ? 'text-blue-500' : 'text-slate-400' },
              { label: 'Utilisation',            value: `${pipeHealth.db_pool_utilisation_pct ?? 0}%`, accent: (pipeHealth.db_pool_utilisation_pct ?? 0) >= 80 ? 'text-red-600' : 'text-emerald-600' },
            ]
            return (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {rows.map(({ label, value, accent }) => (
              <div key={label} className="bg-slate-50 rounded-xl p-3 border border-slate-100">
                <p className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider mb-1">{label}</p>
                <p className={`text-lg font-black tabular-nums ${accent}`}>{value}</p>
              </div>
            ))}
          </div>
            )
          })()}
          {pipeHealth.last_draw_at && (
            <p className="mt-3 text-xs text-slate-400">
              Last draw: <span className="font-mono text-slate-600">{new Date(pipeHealth.last_draw_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</span>
              {pipeHealth.last_pool_created_at && (
                <> &nbsp;·&nbsp; Last pool: <span className="font-mono text-slate-600">{new Date(pipeHealth.last_pool_created_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</span></>
              )}
            </p>
          )}
        </div>
      )}

      {/* Response time chart (simple bar) */}
      {(apiLatency || dbLatency) && (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
          <div className="flex items-center gap-2 mb-5">
            <Zap className="w-4 h-4 text-amber-500" />
            <h2 className="font-semibold text-slate-800">Response Times</h2>
            <span className="text-xs text-slate-400 ml-auto">
              <Clock className="w-3 h-3 inline mr-1" />
              {lastChecked?.toLocaleTimeString()}
            </span>
          </div>
          <div className="space-y-4">
            {[
              { label: 'API Gateway  (GET /)',              ms: apiLatency,  color: 'bg-blue-500'   },
              { label: 'Database     (GET /admin/stats)',   ms: dbLatency,   color: 'bg-violet-500' },
            ].map(({ label, ms, color }) => ms != null && (
              <div key={label}>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-slate-500 font-mono">{label}</span>
                  <span className={`font-bold ${ms < 200 ? 'text-emerald-600' : ms < 600 ? 'text-amber-600' : 'text-red-600'}`}>
                    {ms} ms
                  </span>
                </div>
                <div className="w-full bg-slate-100 rounded-full h-2">
                  <div
                    className={`${color} h-2 rounded-full transition-all`}
                    style={{ width: `${Math.min(100, (ms / 1500) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
