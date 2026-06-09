import { useState, useEffect, useCallback } from 'react'
import {
  Gift, RefreshCw, CheckCircle2, XCircle,
  AlertTriangle, Users, IndianRupee, Clock,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import { getPendingReferrals, updateReferralStatus } from '../api/client'
import { useToast } from '../context/ToastContext'

const INR = v =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(Number(v))

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

// ─── Summary stat tile ────────────────────────────────────────────────────────
function StatTile({ icon: Icon, label, value, iconBg, iconColor }) {
  return (
    <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5 flex items-center gap-4">
      <div className={`${iconBg} p-3 rounded-xl flex-shrink-0`}>
        <Icon className={`w-5 h-5 ${iconColor}`} />
      </div>
      <div>
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{label}</p>
        <p className="text-2xl font-bold text-slate-900 tabular-nums mt-0.5">{value}</p>
      </div>
    </div>
  )
}

// ─── Empty state ──────────────────────────────────────────────────────────────
function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="bg-emerald-50 p-5 rounded-full mb-4">
        <CheckCircle2 className="w-8 h-8 text-emerald-500" />
      </div>
      <h3 className="text-base font-bold text-slate-700">All caught up!</h3>
      <p className="text-sm text-slate-400 mt-1 max-w-xs">
        No referral payouts are awaiting approval right now.
        New requests appear here when users submit via the app.
      </p>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
export default function ReferralQueue() {
  const toast = useToast()

  const [items,      setItems]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // Per-token processing state: { token_id: 'approve' | 'reject' }
  const [processing, setProcessing] = useState({})

  // ── Load ─────────────────────────────────────────────────────────────────
  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    try {
      const res = await getPendingReferrals()
      setItems(res.data)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to load referral queue', 'error')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // ── Action ────────────────────────────────────────────────────────────────
  const handleAction = async (tokenId, action) => {
    setProcessing(p => ({ ...p, [tokenId]: action }))
    try {
      const res = await updateReferralStatus(tokenId, action)
      toast(
        res.data.message ?? `Request ${action}d`,
        action === 'approve' ? 'success' : 'warning',
      )
      // Optimistic removal — request no longer pending
      setItems(prev => prev.filter(i => i.token_id !== tokenId))
    } catch (err) {
      toast(err.response?.data?.detail ?? `${action} failed`, 'error')
    } finally {
      setProcessing(p => { const n = { ...p }; delete n[tokenId]; return n })
    }
  }

  // ── Derived stats ─────────────────────────────────────────────────────────
  const totalPending = items.length
  const totalValue   = items.reduce((s, i) => s + Number(i.token_value_inr || 0), 0)
  const uniqueUsers  = new Set(items.map(i => i.user_id).filter(Boolean)).size

  // ════════════════════════════════════════════════════════════════════════════
  return (
    <div className="p-8 space-y-6">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Gift className="w-6 h-6 text-violet-600" />
            Referral Payout Queue
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Review and approve or reject pending referral withdrawal requests
          </p>
        </div>
        <button
          onClick={() => load(true)}
          disabled={refreshing || loading}
          className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* ── Summary tiles ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-4">
        <StatTile
          icon={Clock}
          label="Pending Requests"
          value={loading ? '…' : totalPending}
          iconBg="bg-amber-50"
          iconColor="text-amber-500"
        />
        <StatTile
          icon={IndianRupee}
          label="Total Value Pending"
          value={loading ? '…' : INR(totalValue)}
          iconBg="bg-violet-50"
          iconColor="text-violet-600"
        />
        <StatTile
          icon={Users}
          label="Unique Requesters"
          value={loading ? '…' : uniqueUsers}
          iconBg="bg-blue-50"
          iconColor="text-blue-600"
        />
      </div>

      {/* ── How it works banner ───────────────────────────────────────────── */}
      <div className="flex items-start gap-3 bg-blue-50 border border-blue-200 rounded-xl px-4 py-3">
        <AlertTriangle className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-blue-700 leading-relaxed">
          <strong>Approve</strong> — marks the token Active so the user can present it for physical cash collection.
          &nbsp;|&nbsp;
          <strong>Reject</strong> — burns the token and credits the full amount back to the user's accumulated referral balance.
          Users need a minimum balance of ₹1,000 to submit a payout request.
        </p>
      </div>

      {/* ── Queue Table ───────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-16">
            <Spinner className="w-8 h-8" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[860px]">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  {[
                    'Token Code', 'User', 'Requested Amount',
                    'Referral Stats', 'Remaining Balance', 'Submitted', 'Actions',
                  ].map(h => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {items.map(item => {
                  const isProcessing = !!processing[item.token_id]
                  const processingAction = processing[item.token_id]

                  return (
                    <tr
                      key={item.token_id}
                      className={`transition-all ${isProcessing ? 'opacity-60 bg-slate-50/80' : 'hover:bg-slate-50/40'}`}
                    >
                      {/* Token code */}
                      <td className="px-4 py-4">
                        <div className="flex flex-col gap-0.5">
                          <span className="font-mono font-bold text-slate-800 tracking-widest text-xs">
                            {item.token_code}
                          </span>
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 w-fit">
                            Pending Approval
                          </span>
                        </div>
                      </td>

                      {/* User */}
                      <td className="px-4 py-4">
                        {item.username ? (
                          <div>
                            <p className="font-semibold text-slate-800 text-sm">{item.user_name}</p>
                            <p className="text-xs text-slate-400 font-mono">@{item.username}</p>
                            <p className="text-[10px] text-slate-400">ID #{item.user_id}</p>
                          </div>
                        ) : (
                          <span className="text-slate-300 text-xs">Unknown user</span>
                        )}
                      </td>

                      {/* Requested amount */}
                      <td className="px-4 py-4">
                        <p className="text-lg font-bold text-violet-700 tabular-nums">
                          {INR(item.token_value_inr)}
                        </p>
                        <p className="text-[10px] text-slate-400 mt-0.5">Referral_Withdraw</p>
                      </td>

                      {/* Referral stats */}
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          <div className="bg-slate-100 rounded-lg px-2.5 py-1.5 text-center">
                            <p className="text-sm font-bold text-slate-800 tabular-nums">{item.total_referrals_count}</p>
                            <p className="text-[10px] text-slate-500">total refs</p>
                          </div>
                        </div>
                      </td>

                      {/* Balance remaining after this payout */}
                      <td className="px-4 py-4">
                        <p className={`text-sm font-bold tabular-nums ${
                          parseFloat(item.accumulated_bonus_inr) > 0
                            ? 'text-emerald-600'
                            : 'text-slate-400'
                        }`}>
                          {INR(item.accumulated_bonus_inr)}
                        </p>
                        <p className="text-[10px] text-slate-400 mt-0.5">current balance</p>
                      </td>

                      {/* Submitted at */}
                      <td className="px-4 py-4 text-xs text-slate-500 whitespace-nowrap">
                        {fmtDate(item.created_at)}
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2">
                          {/* Approve */}
                          <button
                            onClick={() => handleAction(item.token_id, 'approve')}
                            disabled={isProcessing}
                            className="flex items-center gap-1.5 px-3 py-2 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 text-emerald-700 rounded-xl text-xs font-bold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                          >
                            {processingAction === 'approve'
                              ? <Spinner className="w-3.5 h-3.5 text-emerald-600" />
                              : <CheckCircle2 className="w-3.5 h-3.5" />}
                            Approve
                          </button>

                          {/* Reject */}
                          <button
                            onClick={() => handleAction(item.token_id, 'reject')}
                            disabled={isProcessing}
                            className="flex items-center gap-1.5 px-3 py-2 bg-red-50 hover:bg-red-100 border border-red-200 text-red-700 rounded-xl text-xs font-bold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                          >
                            {processingAction === 'reject'
                              ? <Spinner className="w-3.5 h-3.5 text-red-600" />
                              : <XCircle className="w-3.5 h-3.5" />}
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Footer note */}
      {!loading && items.length > 0 && (
        <p className="text-xs text-slate-400 text-center">
          {items.length} request{items.length !== 1 ? 's' : ''} pending · Actions are immediate and cannot be reversed
        </p>
      )}
    </div>
  )
}
