/**
 * SystemSettings.jsx
 * ==================
 * Admin-only settings panel for runtime-configurable system parameters.
 *
 * Current settings:
 *   ① Pool Creation Threshold — minimum paid Waitlist members that must
 *     accumulate before check_and_scale_waitlist() auto-creates a new pool.
 *     Change requires admin password; confirmed in a dedicated modal.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Settings, RefreshCw, Sliders, AlertTriangle,
  CheckCircle2, Lock, ChevronRight,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import Modal from '../components/Modal'
import { getThreshold, updateThreshold } from '../api/client'
import { useToast } from '../context/ToastContext'

// ─── Shared input class ───────────────────────────────────────────────────────
const inputCls =
  'w-full rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 transition'

// ─── Section card shell ───────────────────────────────────────────────────────
function SettingCard({ icon: Icon, iconBg, iconColor, title, subtitle, badge, children }) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
      <div className="px-6 py-5 border-b border-slate-100 flex items-center gap-3">
        <div className={`${iconBg} p-2.5 rounded-xl flex-shrink-0`}>
          <Icon className={`w-5 h-5 ${iconColor}`} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-semibold text-slate-800">{title}</p>
            {badge}
          </div>
          {subtitle && <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{subtitle}</p>}
        </div>
      </div>
      <div className="p-6">{children}</div>
    </div>
  )
}

// ─── Read-only stat row ───────────────────────────────────────────────────────
function StatRow({ label, value, accent = 'text-slate-800' }) {
  return (
    <div className="flex items-center justify-between py-3 border-b last:border-0 border-slate-100">
      <p className="text-sm text-slate-500">{label}</p>
      <p className={`text-sm font-semibold tabular-nums ${accent}`}>{value}</p>
    </div>
  )
}


// ═════════════════════════════════════════════════════════════════════════════
// Page component
// ═════════════════════════════════════════════════════════════════════════════

export default function SystemSettings() {
  const toast = useToast()

  // ── Threshold data ────────────────────────────────────────────────────────
  const [threshold,  setThreshold]  = useState(null)   // current live value
  const [inputVal,   setInputVal]   = useState('')      // controlled number input
  const [pageLoading, setPageLoading] = useState(true)
  const [refreshing,  setRefreshing]  = useState(false)

  // ── Confirmation modal ────────────────────────────────────────────────────
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingVal,  setPendingVal]  = useState(null)  // value waiting for password
  const [adminPw,     setAdminPw]     = useState('')
  const [saveLoading, setSaveLoading] = useState(false)

  // ── Fetch current threshold ───────────────────────────────────────────────
  const fetchSettings = useCallback(async (silent = false) => {
    if (!silent) setPageLoading(true)
    else setRefreshing(true)
    try {
      const res = await getThreshold()
      const val = res.data.pool_creation_threshold
      setThreshold(val)
      setInputVal(String(val))
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to load settings', 'error')
    } finally {
      setPageLoading(false)
      setRefreshing(false)
    }
  }, []) // eslint-disable-line

  useEffect(() => { fetchSettings() }, [fetchSettings])

  // ── Open confirmation modal ───────────────────────────────────────────────
  const handleSaveClick = () => {
    const val = parseInt(inputVal, 10)
    if (!inputVal.trim() || isNaN(val)) {
      toast('Please enter a valid whole number', 'error')
      return
    }
    if (val < 1 || val > 1000) {
      toast('Threshold must be between 1 and 1000', 'error')
      return
    }
    if (val === threshold) {
      toast('New value matches the current threshold — no change needed', 'info')
      return
    }
    setPendingVal(val)
    setAdminPw('')
    setConfirmOpen(true)
  }

  // ── Cancel / reset modal ──────────────────────────────────────────────────
  const handleCloseConfirm = () => {
    if (saveLoading) return
    setConfirmOpen(false)
    setAdminPw('')
    setPendingVal(null)
  }

  // ── Submit change to backend ──────────────────────────────────────────────
  const handleConfirmSave = async () => {
    if (!adminPw.trim()) {
      toast('Admin password is required to authorise this change', 'error')
      return
    }
    setSaveLoading(true)
    try {
      const res = await updateThreshold(pendingVal, adminPw)
      setThreshold(res.data.pool_creation_threshold)
      setInputVal(String(res.data.pool_creation_threshold))
      toast(res.data.message, 'success')
      handleCloseConfirm()
    } catch (err) {
      // Wrong password or validation error — keep modal open so admin can retry
      toast(err.response?.data?.detail ?? 'Failed to update threshold', 'error')
    } finally {
      setSaveLoading(false)
    }
  }

  // ── Derived display values ────────────────────────────────────────────────
  const parsedInput   = parseInt(inputVal, 10)
  const inputIsValid  = !isNaN(parsedInput) && parsedInput >= 1 && parsedInput <= 1000
  const inputIsDirty  = inputIsValid && parsedInput !== threshold
  const delta         = pendingVal !== null && threshold !== null ? pendingVal - threshold : 0

  // ─────────────────────────────────────────────────────────────────────────
  if (pageLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner className="w-8 h-8 text-slate-400" />
      </div>
    )
  }

  return (
    <div className="p-8 space-y-8 max-w-3xl mx-auto">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">System Settings</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Runtime-configurable parameters — changes take effect immediately, no restart needed
          </p>
        </div>
        <button
          onClick={() => fetchSettings(true)}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* ── Pool Creation Threshold ──────────────────────────────────────── */}
      <SettingCard
        icon={Sliders}
        iconBg="bg-indigo-50"
        iconColor="text-indigo-600"
        title="Pool Creation Threshold"
        subtitle="Minimum number of paid Waitlist members required before the auto-scale algorithm creates a new pool."
        badge={
          threshold !== null && (
            <span className="text-xs font-semibold bg-indigo-100 text-indigo-700 border border-indigo-200 rounded-full px-2.5 py-0.5">
              Currently: {threshold}
            </span>
          )
        }
      >
        {/* Current value summary */}
        <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100 mb-6">
          <StatRow
            label="Current threshold"
            value={threshold !== null ? `${threshold} members` : '—'}
            accent="text-indigo-600"
          />
          <StatRow
            label="Applies to"
            value="Auto pool creation (when toggle is ON)"
          />
          <StatRow
            label="Default value"
            value="24 members"
            accent="text-slate-500"
          />
        </div>

        {/* Explainer */}
        <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-50 border border-amber-100 mb-6">
          <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-amber-800 leading-relaxed space-y-1">
            <p className="font-semibold">How this affects the system</p>
            <ul className="list-disc list-inside space-y-0.5 text-amber-700">
              <li>Lower value → pools form more frequently, smaller waitlist queues</li>
              <li>Higher value → pools form less often, longer waitlist queues</li>
              <li>Manual pool creation (bypasses this threshold) is unaffected</li>
              <li>Changes take effect on the very next auto-scale check</li>
            </ul>
          </div>
        </div>

        {/* Edit control */}
        <div className="space-y-3">
          <label className="block text-sm font-semibold text-slate-700">
            New threshold value
          </label>
          <div className="flex items-center gap-3">
            <input
              type="number"
              min="1"
              max="1000"
              value={inputVal}
              onChange={e => setInputVal(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && inputIsDirty && handleSaveClick()}
              className={`${inputCls} max-w-[160px] font-mono text-base ${
                inputIsDirty
                  ? 'border-indigo-300 ring-1 ring-indigo-200'
                  : !inputIsValid && inputVal !== ''
                    ? 'border-red-300 ring-1 ring-red-200'
                    : ''
              }`}
              placeholder="e.g. 24"
            />
            <span className="text-sm text-slate-400 select-none">members (1 – 1,000)</span>
          </div>

          {/* Validation feedback */}
          {inputVal !== '' && !inputIsValid && (
            <p className="text-xs text-red-500 flex items-center gap-1">
              <AlertTriangle className="w-3.5 h-3.5" />
              Must be a whole number between 1 and 1,000
            </p>
          )}
          {inputIsDirty && (
            <p className="text-xs text-indigo-600 flex items-center gap-1">
              <ChevronRight className="w-3.5 h-3.5" />
              Changing from <strong>{threshold}</strong> → <strong>{parsedInput}</strong>
              &nbsp;({parsedInput > threshold ? `+${parsedInput - threshold}` : parsedInput - threshold})
            </p>
          )}

          <button
            onClick={handleSaveClick}
            disabled={!inputIsDirty || refreshing}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed shadow-sm transition-colors"
          >
            <Lock className="w-4 h-4" />
            Save — Requires Password
          </button>
        </div>
      </SettingCard>

      {/* ── Placeholder for future settings ──────────────────────────────── */}
      <div className="rounded-2xl border border-dashed border-slate-200 p-6 text-center space-y-1">
        <Settings className="w-6 h-6 text-slate-300 mx-auto" />
        <p className="text-sm font-medium text-slate-400">More settings coming soon</p>
        <p className="text-xs text-slate-300">
          Future parameters (payout schedules, late-fee rates, etc.) will appear here
        </p>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════
          Confirmation modal — password-gated, shown when admin clicks Save
          ═══════════════════════════════════════════════════════════════════ */}
      <Modal
        open={confirmOpen}
        onClose={handleCloseConfirm}
        title="Confirm Threshold Change"
        maxWidth="max-w-md"
      >
        <div className="space-y-5">

          {/* Warning block */}
          <div className="bg-amber-50 border border-amber-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-amber-800 text-sm">
                You are about to change a system parameter
              </p>
              <p className="text-xs text-amber-700 mt-1 leading-relaxed">
                This affects how quickly new pools auto-form.
                The change takes effect immediately and cannot be automatically rolled back.
              </p>
            </div>
          </div>

          {/* Change summary */}
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Setting</span>
              <span className="text-sm font-semibold text-slate-800">Pool Creation Threshold</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Current value</span>
              <span className="text-sm font-semibold text-slate-600">{threshold} members</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">New value</span>
              <span className="text-sm font-bold text-indigo-600">{pendingVal} members</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Net change</span>
              <span className={`text-sm font-bold ${delta > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>
                {delta > 0 ? `+${delta}` : delta} members
              </span>
            </div>
          </div>

          {/* Password gate */}
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700">
              <Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />
              Admin Password
            </label>
            <input
              type="password"
              className={`${inputCls} ${adminPw.length > 0 ? 'border-slate-300' : ''}`}
              value={adminPw}
              onChange={e => setAdminPw(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !saveLoading && handleConfirmSave()}
              placeholder="Enter your admin password to authorise this change"
              autoComplete="current-password"
              autoFocus
            />
            <p className="text-xs text-slate-400">
              Your password is verified server-side before the change is written.
            </p>
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-end gap-3 pt-1">
            <button
              onClick={handleCloseConfirm}
              disabled={saveLoading}
              className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirmSave}
              disabled={!adminPw.trim() || saveLoading}
              className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {saveLoading
                ? <><Spinner className="w-4 h-4" />Saving…</>
                : <><CheckCircle2 className="w-4 h-4" />Confirm Change</>
              }
            </button>
          </div>

        </div>
      </Modal>

    </div>
  )
}
