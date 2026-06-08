import { useState, useEffect, useCallback } from 'react'
import { IndianRupee, Users, LayoutGrid, Clock, RefreshCw, Zap, AlertCircle } from 'lucide-react'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import Spinner from '../components/Spinner'
import { getStats, getPools, checkWaitlist, BASE_URL } from '../api/client'
import { useToast } from '../context/ToastContext'

const INR = v =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)

export default function Dashboard() {
  const toast = useToast()
  const [stats, setStats] = useState(null)
  const [pools, setPools] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [waitlistLoading, setWaitlistLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError] = useState(null)

  const fetchAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    setError(null)
    try {
      const [statsRes, poolsRes] = await Promise.all([getStats(), getPools()])
      setStats(statsRes.data)
      setPools(poolsRes.data)
      setLastUpdated(new Date())
    } catch (err) {
      const msg = err.code === 'ERR_NETWORK'
        ? `Cannot reach API at ${BASE_URL} — is the backend running?`
        : err.response?.data?.detail ?? 'Failed to load dashboard data'
      setError(msg)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const handleWaitlistCheck = async () => {
    setWaitlistLoading(true)
    try {
      const res = await checkWaitlist()
      toast(res.data.message, res.data.pool_created ? 'success' : 'info')
      fetchAll(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Waitlist check failed', 'error')
    } finally {
      setWaitlistLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner className="w-8 h-8" />
      </div>
    )
  }

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {lastUpdated ? `Last updated ${lastUpdated.toLocaleTimeString()}` : 'Loading…'}
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

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Metric cards */}
      {stats && (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-5">
          <MetricCard
            icon={IndianRupee}
            label="Total Capital Collected"
            value={INR(stats.total_capital_inr)}
            sub="Burned Deposit tokens"
            iconBg="bg-emerald-50"
            iconColor="text-emerald-600"
          />
          <MetricCard
            icon={Users}
            label="Active Users"
            value={stats.active_users}
            sub={`${stats.eliminated_count} eliminated`}
            iconBg="bg-blue-50"
            iconColor="text-blue-600"
          />
          <MetricCard
            icon={LayoutGrid}
            label="Pools Running"
            value={stats.active_pools}
            sub="Active pools"
            iconBg="bg-violet-50"
            iconColor="text-violet-600"
          />
          <MetricCard
            icon={Clock}
            label="Waitlist Queue"
            value={stats.waitlist_count}
            sub="Paid members waiting"
            iconBg="bg-amber-50"
            iconColor="text-amber-600"
          />
        </div>
      )}

      <div className="grid grid-cols-3 gap-5">
        {/* Pool Status */}
        <div className="col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="font-semibold text-slate-800">Active Pools</h2>
            <span className="text-xs text-slate-400">{pools.filter(p => p.status === 'Active').length} pools</span>
          </div>
          {pools.length === 0 ? (
            <div className="px-6 py-12 text-center text-slate-400 text-sm">No pools yet</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Pool</th>
                  <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                  <th className="text-center px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Members</th>
                </tr>
              </thead>
              <tbody>
                {pools.map((pool, i) => (
                  <tr key={pool.id} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}>
                    <td className="px-6 py-3 font-semibold text-slate-800">{pool.name}</td>
                    <td className="px-6 py-3"><StatusBadge status={pool.status} /></td>
                    <td className="px-6 py-3 text-center font-mono text-slate-700">{pool.total_members}/12</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Quick Actions */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100">
            <h2 className="font-semibold text-slate-800">Quick Actions</h2>
          </div>
          <div className="p-6 space-y-3">
            <button
              onClick={handleWaitlistCheck}
              disabled={waitlistLoading}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-semibold shadow-sm shadow-blue-200 disabled:opacity-60 transition"
            >
              {waitlistLoading ? <Spinner className="w-4 h-4" /> : <Zap className="w-4 h-4" />}
              Check Waitlist Threshold
            </button>

            {stats && (
              <div className="mt-4 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Tokens Issued</span>
                  <span className="font-semibold text-slate-800">{stats.total_tokens_issued}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Active Tokens</span>
                  <span className="font-semibold text-slate-800">{stats.active_tokens}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Waitlist Progress</span>
                  <span className="font-semibold text-slate-800">{stats.waitlist_count}/24</span>
                </div>
                <div className="w-full bg-slate-100 rounded-full h-2 mt-1">
                  <div
                    className="bg-amber-400 h-2 rounded-full transition-all"
                    style={{ width: `${Math.min(100, (stats.waitlist_count / 24) * 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
