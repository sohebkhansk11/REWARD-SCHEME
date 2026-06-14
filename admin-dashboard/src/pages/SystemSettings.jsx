/**
 * SystemSettings.jsx
 * ==================
 * Admin-only settings panel for runtime-configurable system parameters.
 *
 * Current settings:
 *   ① Pool Creation Threshold — minimum paid Waitlist members that must
 *     accumulate before check_and_scale_waitlist() auto-creates a new pool.
 *     Change requires admin password; confirmed in a dedicated modal.
 *
 *   ② Draw Calendar — configurable Sunday draw UTC time and T-2H prep window.
 *     Change requires admin password; takes effect on next APScheduler fire.
 *
 * SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
 * Added Draw Calendar section + DrawCalendarCard component.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Settings, RefreshCw, Sliders, AlertTriangle,
  CheckCircle2, Lock, ChevronRight, Calendar,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import Modal from '../components/Modal'
import { getThreshold, updateThreshold, getDrawSchedule, updateDrawSchedule } from '../api/client'
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

// ─── Number input with label ──────────────────────────────────────────────────
function NumInput({ label, value, onChange, min, max, unit, note }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-semibold text-slate-700">{label}</label>
      <div className="flex items-center gap-3">
        <input
          type="number" min={min} max={max}
          value={value}
          onChange={e => onChange(e.target.value)}
          className={`${inputCls} max-w-[130px] font-mono text-base`}
        />
        {unit && <span className="text-sm text-slate-400 select-none">{unit}</span>}
      </div>
      {note && <p className="text-xs text-slate-400">{note}</p>}
    </div>
  )
}


// ═════════════════════════════════════════════════════════════════════════════
// Page component
// ═════════════════════════════════════════════════════════════════════════════

export default function SystemSettings() {
  const toast = useToast()

  // ── Threshold state ───────────────────────────────────────────────────────
  const [threshold,    setThreshold]    = useState(null)
  const [inputVal,     setInputVal]     = useState('')
  const [pageLoading,  setPageLoading]  = useState(true)
  const [refreshing,   setRefreshing]   = useState(false)

  // ── Threshold modal ───────────────────────────────────────────────────────
  const [confirmOpen,  setConfirmOpen]  = useState(false)
  const [pendingVal,   setPendingVal]   = useState(null)
  const [adminPw,      setAdminPw]      = useState('')
  const [saveLoading,  setSaveLoading]  = useState(false)

  // ── Draw Schedule state ───────────────────────────────────────────────────
  const [schedule,     setSchedule]     = useState(null)   // {draw_hour_utc, draw_minute_utc, draw_prep_hours, draw_time_ist}
  const [drawHour,     setDrawHour]     = useState('')
  const [drawMinute,   setDrawMinute]   = useState('')
  const [drawPrep,     setDrawPrep]     = useState('')

  // ── Draw Schedule modal ───────────────────────────────────────────────────
  const [drawModalOpen,  setDrawModalOpen]  = useState(false)
  const [drawAdminPw,    setDrawAdminPw]    = useState('')
  const [drawSaveLoading,setDrawSaveLoading]= useState(false)

  // ── Fetch all settings ────────────────────────────────────────────────────
  const fetchSettings = useCallback(async (silent = false) => {
    if (!silent) setPageLoading(true)
    else setRefreshing(true)
    try {
      const [thrRes, schedRes] = await Promise.allSettled([getThreshold(), getDrawSchedule()])
      if (thrRes.status === 'fulfilled') {
        const val = thrRes.value.data.pool_creation_threshold
        setThreshold(val)
        setInputVal(String(val))
      } else {
        toast(thrRes.reason?.response?.data?.detail ?? 'Failed to load threshold', 'error')
      }
      if (schedRes.status === 'fulfilled') {
        const s = schedRes.value.data
        setSchedule(s)
        setDrawHour(String(s.draw_hour_utc))
        setDrawMinute(String(s.draw_minute_utc))
        setDrawPrep(String(s.draw_prep_hours))
      } else {
        toast(schedRes.reason?.response?.data?.detail ?? 'Failed to load draw schedule', 'error')
      }
    } finally {
      setPageLoading(false)
      setRefreshing(false)
    }
  }, []) // eslint-disable-line

  useEffect(() => { fetchSettings() }, [fetchSettings])

  // ── Threshold handlers ────────────────────────────────────────────────────
  const handleSaveClick = () => {
    const val = parseInt(inputVal, 10)
    if (!inputVal.trim() || isNaN(val)) { toast('Please enter a valid whole number', 'error'); return }
    if (val < 1 || val > 1000)          { toast('Threshold must be between 1 and 1,000', 'error'); return }
    if (val === threshold)              { toast('No change needed — value matches current threshold', 'info'); return }
    setPendingVal(val); setAdminPw(''); setConfirmOpen(true)
  }
  const handleCloseConfirm = () => { if (saveLoading) return; setConfirmOpen(false); setAdminPw(''); setPendingVal(null) }
  const handleConfirmSave  = async () => {
    if (!adminPw.trim()) { toast('Admin password is required', 'error'); return }
    setSaveLoading(true)
    try {
      const res = await updateThreshold(pendingVal, adminPw)
      setThreshold(res.data.pool_creation_threshold)
      setInputVal(String(res.data.pool_creation_threshold))
      toast(res.data.message, 'success')
      handleCloseConfirm()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to update threshold', 'error')
    } finally {
      setSaveLoading(false)
    }
  }

  // ── Draw Schedule handlers ────────────────────────────────────────────────
  const drawHourInt   = parseInt(drawHour,   10)
  const drawMinuteInt = parseInt(drawMinute, 10)
  const drawPrepInt   = parseInt(drawPrep,   10)
  const drawInputValid = (
    !isNaN(drawHourInt)   && drawHourInt   >= 0 && drawHourInt   <= 23 &&
    !isNaN(drawMinuteInt) && drawMinuteInt >= 0 && drawMinuteInt <= 59 &&
    !isNaN(drawPrepInt)   && drawPrepInt   >= 1 && drawPrepInt   <= 6
  )
  const drawIsDirty = drawInputValid && schedule && (
    drawHourInt   !== schedule.draw_hour_utc   ||
    drawMinuteInt !== schedule.draw_minute_utc ||
    drawPrepInt   !== schedule.draw_prep_hours
  )

  // Live IST preview in input area (UTC+5:30)
  const previewIst = (() => {
    if (!drawInputValid) return '—'
    const totalMin = drawHourInt * 60 + drawMinuteInt + 330
    const h24 = (totalMin / 60 | 0) % 24
    const m   = totalMin % 60
    const p   = h24 >= 12 ? 'PM' : 'AM'
    const h12 = h24 % 12 || 12
    return `${h12}:${String(m).padStart(2, '0')} ${p} IST`
  })()

  const handleDrawSaveClick = () => {
    if (!drawInputValid) { toast('Please enter valid values for all draw schedule fields', 'error'); return }
    if (!drawIsDirty)    { toast('No changes to the draw schedule', 'info'); return }
    setDrawAdminPw(''); setDrawModalOpen(true)
  }
  const handleCloseDrawModal = () => { if (drawSaveLoading) return; setDrawModalOpen(false); setDrawAdminPw('') }
  const handleConfirmDrawSave = async () => {
    if (!drawAdminPw.trim()) { toast('Admin password is required', 'error'); return }
    setDrawSaveLoading(true)
    try {
      const res = await updateDrawSchedule(drawHourInt, drawMinuteInt, drawPrepInt, drawAdminPw)
      const s   = res.data
      setSchedule(s)
      setDrawHour(String(s.draw_hour_utc))
      setDrawMinute(String(s.draw_minute_utc))
      setDrawPrep(String(s.draw_prep_hours))
      toast(s.message, 'success')
      handleCloseDrawModal()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to update draw schedule', 'error')
    } finally {
      setDrawSaveLoading(false)
    }
  }

  // ── Derived values ────────────────────────────────────────────────────────
  const parsedInput  = parseInt(inputVal, 10)
  const inputIsValid = !isNaN(parsedInput) && parsedInput >= 1 && parsedInput <= 1000
  const inputIsDirty = inputIsValid && parsedInput !== threshold
  const delta        = pendingVal !== null && threshold !== null ? pendingVal - threshold : 0

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
        <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100 mb-6">
          <StatRow label="Current threshold"  value={threshold !== null ? `${threshold} members` : '—'} accent="text-indigo-600" />
          <StatRow label="Applies to"         value="Auto pool creation (when toggle is ON)" />
          <StatRow label="Default value"      value="24 members" accent="text-slate-500" />
        </div>

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

        <div className="space-y-3">
          <label className="block text-sm font-semibold text-slate-700">New threshold value</label>
          <div className="flex items-center gap-3">
            <input
              type="number" min="1" max="1000"
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

      {/* ── Draw Calendar ────────────────────────────────────────────────── */}
      {/* SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
          Draw Calendar section — replaces the "More settings coming soon" placeholder.
          Three parameters: UTC draw hour, UTC draw minute, T-2H prep window hours. */}
      <SettingCard
        icon={Calendar}
        iconBg="bg-violet-50"
        iconColor="text-violet-600"
        title="Draw Calendar"
        subtitle="Sunday draw time (UTC) and T-2H preparation window. APScheduler picks up changes on the next Sunday fire — no server restart needed."
        badge={
          schedule && (
            <span className="text-xs font-semibold bg-violet-100 text-violet-700 border border-violet-200 rounded-full px-2.5 py-0.5">
              {schedule.draw_time_ist}
            </span>
          )
        }
      >
        <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100 mb-6">
          <StatRow label="Draw day"         value="Every Sunday (fixed)"          accent="text-slate-600" />
          <StatRow label="Draw time (UTC)"  value={schedule ? `${String(schedule.draw_hour_utc).padStart(2,'0')}:${String(schedule.draw_minute_utc).padStart(2,'0')} UTC` : '—'} accent="text-violet-600" />
          <StatRow label="Draw time (IST)"  value={schedule?.draw_time_ist ?? '—'}  accent="text-violet-600" />
          <StatRow label="Prep window"      value={schedule ? `T-${schedule.draw_prep_hours}H (${schedule.draw_prep_hours} hours before draw)` : '—'} />
          <StatRow label="Default schedule" value="13:30 UTC · 7:00 PM IST · T-2H prep" accent="text-slate-500" />
        </div>

        <div className="flex items-start gap-3 p-4 rounded-xl bg-violet-50 border border-violet-100 mb-6">
          <AlertTriangle className="w-4 h-4 text-violet-600 flex-shrink-0 mt-0.5" />
          <div className="text-xs text-violet-800 leading-relaxed space-y-1">
            <p className="font-semibold">How draw timing works</p>
            <ul className="list-disc list-inside space-y-0.5 text-violet-700">
              <li>T-2H: start_draw_preparation() — LPI snapshot, SDE staging (T-2H)</li>
              <li>T-0H: execute_weekly_draw() — full mass draw + SDE execution reveal</li>
              <li>T+5m: post_draw_cleanup() — reset flags, release locks</li>
              <li>Draw day is always Sunday — change requires a code update</li>
              <li>Changes take effect on the NEXT Sunday APScheduler fire</li>
            </ul>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4 mb-6">
          <NumInput
            label="Draw Hour (UTC)"
            value={drawHour}
            onChange={setDrawHour}
            min={0} max={23}
            unit="h"
            note="0–23 UTC"
          />
          <NumInput
            label="Draw Minute (UTC)"
            value={drawMinute}
            onChange={setDrawMinute}
            min={0} max={59}
            unit="m"
            note="0–59"
          />
          <NumInput
            label="Prep Window"
            value={drawPrep}
            onChange={setDrawPrep}
            min={1} max={6}
            unit="hrs"
            note="1–6 hours before draw"
          />
        </div>

        {/* Live IST preview */}
        {drawInputValid && (
          <div className="mb-4 flex items-center gap-2 px-4 py-2.5 bg-violet-50 border border-violet-100 rounded-xl">
            <Calendar className="w-4 h-4 text-violet-500 flex-shrink-0" />
            <p className="text-sm text-violet-700">
              Preview: Sunday{' '}
              <strong>{String(drawHourInt).padStart(2,'0')}:{String(drawMinuteInt).padStart(2,'0')} UTC</strong>
              {' = '}
              <strong>{previewIst}</strong>
              {' · Prep at '}
              <strong>T-{drawPrepInt}H</strong>
            </p>
          </div>
        )}

        {drawIsDirty && (
          <p className="text-xs text-violet-600 flex items-center gap-1 mb-3">
            <ChevronRight className="w-3.5 h-3.5" />
            Changing from{' '}
            <strong>{String(schedule.draw_hour_utc).padStart(2,'0')}:{String(schedule.draw_minute_utc).padStart(2,'0')} UTC / T-{schedule.draw_prep_hours}H</strong>
            {' → '}
            <strong>{String(drawHourInt).padStart(2,'0')}:{String(drawMinuteInt).padStart(2,'0')} UTC / T-{drawPrepInt}H</strong>
          </p>
        )}

        <button
          onClick={handleDrawSaveClick}
          disabled={!drawIsDirty || refreshing}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed shadow-sm transition-colors"
        >
          <Lock className="w-4 h-4" />
          Save — Requires Password
        </button>
      </SettingCard>

      {/* ═══════════════════════════════════════════════════════════════════
          Threshold confirmation modal
          ═══════════════════════════════════════════════════════════════════ */}
      <Modal open={confirmOpen} onClose={handleCloseConfirm} title="Confirm Threshold Change" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-amber-50 border border-amber-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-amber-800 text-sm">You are about to change a system parameter</p>
              <p className="text-xs text-amber-700 mt-1 leading-relaxed">
                This affects how quickly new pools auto-form. The change takes effect immediately and cannot be automatically rolled back.
              </p>
            </div>
          </div>

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
            <p className="text-xs text-slate-400">Your password is verified server-side before the change is written.</p>
          </div>

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

      {/* ═══════════════════════════════════════════════════════════════════
          Draw Schedule confirmation modal
          ═══════════════════════════════════════════════════════════════════ */}
      <Modal open={drawModalOpen} onClose={handleCloseDrawModal} title="Confirm Draw Schedule Change" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-violet-50 border border-violet-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-violet-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-violet-800 text-sm">Changing the weekly draw schedule</p>
              <p className="text-xs text-violet-700 mt-1 leading-relaxed">
                The new time takes effect on the next Sunday APScheduler fire. Ensure the new time is before the current draw if changing this week.
              </p>
            </div>
          </div>

          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Setting</span>
              <span className="text-sm font-semibold text-slate-800">Draw Calendar</span>
            </div>
            {schedule && (
              <div className="flex items-center justify-between px-4 py-3">
                <span className="text-sm text-slate-500">Current</span>
                <span className="text-sm font-semibold text-slate-600">
                  {String(schedule.draw_hour_utc).padStart(2,'0')}:{String(schedule.draw_minute_utc).padStart(2,'0')} UTC · T-{schedule.draw_prep_hours}H
                </span>
              </div>
            )}
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">New value</span>
              <span className="text-sm font-bold text-violet-600">
                {String(drawHourInt).padStart(2,'0')}:{String(drawMinuteInt).padStart(2,'0')} UTC · T-{drawPrepInt}H
              </span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">IST preview</span>
              <span className="text-sm font-bold text-violet-600">{previewIst} (Sunday)</span>
            </div>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700">
              <Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />
              Admin Password
            </label>
            <input
              type="password"
              className={`${inputCls} ${drawAdminPw.length > 0 ? 'border-slate-300' : ''}`}
              value={drawAdminPw}
              onChange={e => setDrawAdminPw(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !drawSaveLoading && handleConfirmDrawSave()}
              placeholder="Enter your admin password to authorise this change"
              autoComplete="current-password"
              autoFocus
            />
            <p className="text-xs text-slate-400">Your password is verified server-side before the change is written.</p>
          </div>

          <div className="flex items-center justify-end gap-3 pt-1">
            <button
              onClick={handleCloseDrawModal}
              disabled={drawSaveLoading}
              className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirmDrawSave}
              disabled={!drawAdminPw.trim() || drawSaveLoading}
              className="flex items-center gap-2 px-5 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {drawSaveLoading
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
