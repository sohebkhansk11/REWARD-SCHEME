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
 *   ③ Draw & Financial Strategy — DB-backed financial constants (base installment,
 *     level payouts L1-L6, LPI thresholds, cascade risk threshold, draw chronology).
 *     All values DB-backed via global_config.py; changes take effect within 60s.
 *
 * SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
 * Added Draw Calendar section + DrawCalendarCard component.
 *
 * SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
 * Added Draw & Financial Strategy section — Directive 2 of Phase 2.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Settings, RefreshCw, Sliders, AlertTriangle,
  CheckCircle2, Lock, ChevronRight, Calendar,
  DollarSign, TrendingUp, Activity,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import Modal from '../components/Modal'
import {
  getThreshold, updateThreshold,
  getDrawSchedule, updateDrawSchedule,
  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  getFinancialConfig,
  updateBaseFinancial, updateLateFees,
  updateAllLevelPayouts, updateThresholds,
  updateDrawCalendar,
} from '../api/client'
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

  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Draw & Financial Strategy state
  const [finConfig,       setFinConfig]       = useState(null)
  const [finLoading,      setFinLoading]      = useState(false)

  // Base Financial edit state
  const [baseInstallment, setBaseInstallment] = useState('')
  const [payoutFee,       setPayoutFee]       = useState('')
  const [baseModalOpen,   setBaseModalOpen]   = useState(false)
  const [baseAdminPw,     setBaseAdminPw]     = useState('')
  const [baseSaving,      setBaseSaving]      = useState(false)

  // Late Fees edit state
  const [lateFeeDaily,    setLateFeeDaily]    = useState('')
  const [lateFeeMaxCap,   setLateFeeMaxCap]   = useState('')
  const [lateModalOpen,   setLateModalOpen]   = useState(false)
  const [lateAdminPw,     setLateAdminPw]     = useState('')
  const [lateSaving,      setLateSaving]      = useState(false)

  // Level Payouts edit state (level 1-6: {gross, net})
  const [levelPayouts,    setLevelPayouts]    = useState({})
  const [levelModalOpen,  setLevelModalOpen]  = useState(false)
  const [levelAdminPw,    setLevelAdminPw]    = useState('')
  const [levelSaving,     setLevelSaving]     = useState(false)

  // Thresholds edit state
  const [thresholds,      setThresholds]      = useState({
    lpi_regular_max: '', lpi_type_a_min: '', lpi_sde_proactive: '',
    lpi_l3_win_exception: '', cascade_prevent_l3_thresh: '', accel_diss_trigger_ratio: '',
  })
  const [threshModalOpen, setThreshModalOpen] = useState(false)
  const [threshAdminPw,   setThreshAdminPw]   = useState('')
  const [threshSaving,    setThreshSaving]    = useState(false)

  // Draw Chronology edit state
  const [drawFrequency,   setDrawFrequency]   = useState('weekly')
  const [drawDayOfWeek,   setDrawDayOfWeek]   = useState(6)
  const [gracePeriodHrs,  setGracePeriodHrs]  = useState('')
  const [cleanupMins,     setCleanupMins]     = useState('')
  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  const [paymentDueDays,  setPaymentDueDays]  = useState(4)
  const [chronoModalOpen, setChronoModalOpen] = useState(false)
  const [chronoAdminPw,   setChronoAdminPw]   = useState('')
  const [chronoSaving,    setChronoSaving]    = useState(false)

  // ── Helper: populate financial state from API response ────────────────────
  const _applyFinConfig = (cfg) => {
    setFinConfig(cfg)
    setBaseInstallment(String(cfg.base_installment_inr))
    setPayoutFee(String(cfg.payout_fee_inr))
    setLateFeeDaily(String(cfg.late_fee_daily_inr))
    setLateFeeMaxCap(String(cfg.late_fee_max_cap_inr))
    const lp = {}
    Object.entries(cfg.level_payouts).forEach(([lvl, { gross_inr, net_inr }]) => {
      lp[lvl] = { gross: String(gross_inr), net: String(net_inr) }
    })
    setLevelPayouts(lp)
    setThresholds({
      lpi_regular_max:          String(cfg.lpi_regular_max),
      lpi_type_a_min:           String(cfg.lpi_type_a_min),
      lpi_sde_proactive:        String(cfg.lpi_sde_proactive),
      lpi_l3_win_exception:     String(cfg.lpi_l3_win_exception),
      cascade_prevent_l3_thresh: String(cfg.cascade_prevent_l3_thresh),
      accel_diss_trigger_ratio:  String(cfg.accel_diss_trigger_ratio),
    })
    setDrawFrequency(cfg.draw_frequency)
    setDrawDayOfWeek(cfg.draw_day_of_week)
    setGracePeriodHrs(String(cfg.grace_period_hours))
    setCleanupMins(String(cfg.cleanup_offset_minutes))
    // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    setPaymentDueDays(String(cfg.payment_due_offset_days ?? 4))
  }

  // ── Fetch all settings ────────────────────────────────────────────────────
  const fetchSettings = useCallback(async (silent = false) => {
    if (!silent) setPageLoading(true)
    else setRefreshing(true)
    try {
      const [thrRes, schedRes, finRes] = await Promise.allSettled([
        getThreshold(), getDrawSchedule(), getFinancialConfig(),
      ])
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
      // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
      if (finRes && finRes.status === 'fulfilled') {
        _applyFinConfig(finRes.value.data)
      } else if (finRes) {
        toast(finRes.reason?.response?.data?.detail ?? 'Failed to load financial config', 'error')
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

      {/* ── SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
          Draw & Financial Strategy Card
          ─────────────────────────────────────────────────────────────────── */}
      <SettingCard
        icon={DollarSign}
        iconBg="bg-emerald-50"
        iconColor="text-emerald-600"
        title="Draw & Financial Strategy"
        subtitle="DB-backed financial constants — base installment, level payouts L1-L6, LPI thresholds, cascade risk threshold, draw chronology. All changes active within 60 seconds."
        badge={
          finConfig && (
            <span className="text-xs font-semibold bg-emerald-100 text-emerald-700 border border-emerald-200 rounded-full px-2.5 py-0.5">
              Base: ₹{finConfig.base_installment_inr}
            </span>
          )
        }
      >
        {!finConfig ? (
          <div className="flex items-center justify-center py-8"><Spinner className="w-6 h-6 text-slate-300" /></div>
        ) : (
          <div className="space-y-8">

            {/* ── Section A: Base Financial ──────────────────────────────── */}
            <div>
              <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
                A — Base Financial Amounts
              </p>
              <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100 mb-4">
                <StatRow label="Base Installment"     value={`₹${finConfig.base_installment_inr}`}  accent="text-emerald-600" />
                <StatRow label="Payout Fee (per win)" value={`₹${finConfig.payout_fee_inr}`}        accent="text-slate-600" />
                <StatRow label="Late Fee / Day"       value={`₹${finConfig.late_fee_daily_inr}`}    accent="text-slate-600" />
                <StatRow label="Late Fee Cap"         value={`₹${finConfig.late_fee_max_cap_inr}`}  accent="text-slate-600" />
              </div>
              <div className="grid grid-cols-2 gap-4 mb-4">
                <NumInput label="Base Installment (₹)" value={baseInstallment} onChange={setBaseInstallment} min={100} max={10000} unit="₹" note="₹100–₹10,000" />
                <NumInput label="Payout Fee (₹)"       value={payoutFee}       onChange={setPayoutFee}       min={0}   max={5000}  unit="₹" note="₹0–₹5,000" />
              </div>
              <button onClick={() => { setBaseAdminPw(''); setBaseModalOpen(true) }}
                className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-sm font-semibold shadow-sm transition-colors">
                <Lock className="w-4 h-4" />Save Base — Requires Password
              </button>
            </div>

            {/* ── Late Fees ─────────────────────────────────────────────── */}
            <div>
              <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
                Late Fees
              </p>
              <div className="grid grid-cols-2 gap-4 mb-4">
                <NumInput label="Daily Rate (₹)"     value={lateFeeDaily}  onChange={setLateFeeDaily}  min={0} max={500}  unit="₹" note="₹0–₹500" />
                <NumInput label="Maximum Cap (₹)"    value={lateFeeMaxCap} onChange={setLateFeeMaxCap} min={0} max={5000} unit="₹" note="₹0–₹5,000" />
              </div>
              <button onClick={() => { setLateAdminPw(''); setLateModalOpen(true) }}
                className="inline-flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-800 text-white rounded-xl text-sm font-semibold shadow-sm transition-colors">
                <Lock className="w-4 h-4" />Save Late Fees — Requires Password
              </button>
            </div>

            {/* ── Section B: Level Payout Table ─────────────────────────── */}
            <div>
              <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
                B — Level Payout Table (L1–L6)
              </p>
              <div className="overflow-x-auto rounded-xl border border-slate-100 mb-4">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 border-b border-slate-100">
                    <tr>
                      <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Level</th>
                      <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Gross ₹</th>
                      <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Net ₹</th>
                      <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">New Gross</th>
                      <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">New Net</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {[1,2,3,4,5,6].map(lvl => (
                      <tr key={lvl} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-3 font-bold text-slate-700">L{lvl}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-slate-500">₹{finConfig.level_payouts[String(lvl)]?.gross_inr ?? '—'}</td>
                        <td className="px-4 py-3 text-right tabular-nums text-emerald-600 font-semibold">₹{finConfig.level_payouts[String(lvl)]?.net_inr ?? '—'}</td>
                        <td className="px-4 py-3 text-right">
                          <input type="number" min={1} max={100000}
                            value={levelPayouts[String(lvl)]?.gross ?? ''}
                            onChange={e => setLevelPayouts(p => ({ ...p, [String(lvl)]: { ...p[String(lvl)], gross: e.target.value } }))}
                            className={`${inputCls} w-24 text-right font-mono text-sm`} />
                        </td>
                        <td className="px-4 py-3 text-right">
                          <input type="number" min={1} max={100000}
                            value={levelPayouts[String(lvl)]?.net ?? ''}
                            onChange={e => setLevelPayouts(p => ({ ...p, [String(lvl)]: { ...p[String(lvl)], net: e.target.value } }))}
                            className={`${inputCls} w-24 text-right font-mono text-sm`} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button onClick={() => { setLevelAdminPw(''); setLevelModalOpen(true) }}
                className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold shadow-sm transition-colors">
                <Lock className="w-4 h-4" />Save Level Payouts — Requires Password
              </button>
            </div>

            {/* ── Section C: LPI & Pressure Thresholds ──────────────────── */}
            <div>
              <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
                C — LPI &amp; Pressure Thresholds
              </p>
              <div className="grid grid-cols-2 gap-4 mb-4">
                {[
                  { key: 'lpi_regular_max',          label: 'LPI Regular Max (%)',      min: 1,    max: 100,  note: 'LPI < this → Regular draw' },
                  { key: 'lpi_type_a_min',           label: 'LPI Type A Min (%)',       min: 1,    max: 100,  note: 'LPI ≥ this → Type A draw' },
                  { key: 'lpi_sde_proactive',        label: 'LPI SDE Proactive (%)',    min: 1,    max: 100,  note: 'LPI ≥ this → SDE proactive' },
                  { key: 'lpi_l3_win_exception',     label: 'L3 Win Exception (%)',     min: 1,    max: 100,  note: 'LPI > this → L3 wins SDE' },
                  { key: 'cascade_prevent_l3_thresh',label: 'Cascade Risk Threshold',   min: 0.1,  max: 10,   note: 'cascade_risk > this → Preventive L3' },
                  { key: 'accel_diss_trigger_ratio', label: 'Accel Dissolve Ratio',     min: 0.10, max: 1.00, note: 'L4+ fraction → Accel Dissolution' },
                ].map(({ key, label, min, max, note }) => (
                  <NumInput key={key} label={label}
                    value={thresholds[key]}
                    onChange={v => setThresholds(p => ({ ...p, [key]: v }))}
                    min={min} max={max} note={note}
                  />
                ))}
              </div>
              <button onClick={() => { setThreshAdminPw(''); setThreshModalOpen(true) }}
                className="inline-flex items-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-xl text-sm font-semibold shadow-sm transition-colors">
                <Lock className="w-4 h-4" />Save Thresholds — Requires Password
              </button>
            </div>

            {/* ── Section D: Draw Chronology ─────────────────────────────── */}
            <div>
              <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
                D — Draw Chronology
              </p>
              <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100 mb-4">
                <StatRow label="Draw Frequency"          value={finConfig.draw_frequency}  accent="text-violet-600" />
                <StatRow label="Draw Day"                value={finConfig.draw_day_name}   accent="text-violet-600" />
                <StatRow label="Grace Period"            value={`${finConfig.grace_period_hours}h`} />
                <StatRow label="Cleanup Offset"          value={`T+${finConfig.cleanup_offset_minutes}min`} />
                {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
                <StatRow label="Payment Due Offset"      value={`T+${finConfig.payment_due_offset_days ?? 4}d`} />
              </div>
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div className="space-y-1.5">
                  <label className="block text-sm font-semibold text-slate-700">Draw Frequency</label>
                  <select value={drawFrequency} onChange={e => setDrawFrequency(e.target.value)} className={inputCls}>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="monthly">Monthly</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="block text-sm font-semibold text-slate-700">Draw Day</label>
                  <select value={drawDayOfWeek} onChange={e => setDrawDayOfWeek(parseInt(e.target.value,10))} className={inputCls}>
                    {['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((d,i) => (
                      <option key={i} value={i}>{d}</option>
                    ))}
                  </select>
                </div>
                <NumInput label="Grace Period (hours)" value={gracePeriodHrs} onChange={setGracePeriodHrs} min={1} max={168} unit="hrs" note="1–168 hours (max 7 days)" />
                <NumInput label="Cleanup Offset (min)" value={cleanupMins}    onChange={setCleanupMins}    min={1} max={60}  unit="min" note="Minutes after draw T-0H" />
                {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
                <NumInput label="Payment Due Offset (days)" value={paymentDueDays} onChange={setPaymentDueDays} min={1} max={27} unit="days" note="Days after cycle start before on-time window closes (1–27)" />
              </div>
              <button onClick={() => { setChronoAdminPw(''); setChronoModalOpen(true) }}
                className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold shadow-sm transition-colors">
                <Lock className="w-4 h-4" />Save Draw Chronology — Requires Password
              </button>
            </div>

          </div>
        )}
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

      {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
          ── Financial config confirmation modals (5) ─────────────────────────── */}

      {/* ── Modal 1: Base Financial ───────────────────────────────────────────── */}
      <Modal open={baseModalOpen} onClose={() => !baseSaving && setBaseModalOpen(false)} title="Confirm Base Financial Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-emerald-800">Changing base installment affects all future payment calculations. Level payout amounts are independent — update them in the Level Payouts section if needed.</p>
          </div>
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Base Installment</span>
              <span className="text-sm font-bold text-emerald-600">₹{baseInstallment}</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Payout Fee</span>
              <span className="text-sm font-bold text-emerald-600">₹{payoutFee}</span>
            </div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700">
              <Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password
            </label>
            <input
              type="password"
              className={inputCls}
              value={baseAdminPw}
              onChange={e => setBaseAdminPw(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter' && !baseSaving && baseAdminPw.trim()) {
                  setBaseSaving(true)
                  try {
                    const r = await updateBaseFinancial(parseInt(baseInstallment, 10), parseInt(payoutFee, 10), baseAdminPw)
                    _applyFinConfig({ ...finConfig, ...r.data })
                    toast(r.data.message, 'success')
                    setBaseModalOpen(false)
                    setBaseAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update base financial config', 'error') }
                  finally { setBaseSaving(false) }
                }
              }}
              placeholder="Enter admin password"
              autoFocus
            />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setBaseModalOpen(false); setBaseAdminPw('') }} disabled={baseSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button
              disabled={!baseAdminPw.trim() || baseSaving}
              onClick={async () => {
                setBaseSaving(true)
                try {
                  const r = await updateBaseFinancial(parseInt(baseInstallment, 10), parseInt(payoutFee, 10), baseAdminPw)
                  _applyFinConfig({ ...finConfig, ...r.data })
                  toast(r.data.message, 'success')
                  setBaseModalOpen(false)
                  setBaseAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update base financial config', 'error') }
                finally { setBaseSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {baseSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* ── Modal 2: Late Fees ────────────────────────────────────────────────── */}
      <Modal open={lateModalOpen} onClose={() => !lateSaving && setLateModalOpen(false)} title="Confirm Late Fee Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Daily Rate</span>
              <span className="text-sm font-bold text-slate-700">₹{lateFeeDaily} / day</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Maximum Cap</span>
              <span className="text-sm font-bold text-slate-700">₹{lateFeeMaxCap}</span>
            </div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700">
              <Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password
            </label>
            <input
              type="password"
              className={inputCls}
              value={lateAdminPw}
              onChange={e => setLateAdminPw(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter' && !lateSaving && lateAdminPw.trim()) {
                  setLateSaving(true)
                  try {
                    const r = await updateLateFees(parseInt(lateFeeDaily, 10), parseInt(lateFeeMaxCap, 10), lateAdminPw)
                    _applyFinConfig({ ...finConfig, ...r.data })
                    toast(r.data.message, 'success')
                    setLateModalOpen(false)
                    setLateAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update late fees', 'error') }
                  finally { setLateSaving(false) }
                }
              }}
              placeholder="Enter admin password"
              autoFocus
            />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setLateModalOpen(false); setLateAdminPw('') }} disabled={lateSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button
              disabled={!lateAdminPw.trim() || lateSaving}
              onClick={async () => {
                setLateSaving(true)
                try {
                  const r = await updateLateFees(parseInt(lateFeeDaily, 10), parseInt(lateFeeMaxCap, 10), lateAdminPw)
                  _applyFinConfig({ ...finConfig, ...r.data })
                  toast(r.data.message, 'success')
                  setLateModalOpen(false)
                  setLateAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update late fees', 'error') }
                finally { setLateSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-slate-700 hover:bg-slate-800 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {lateSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* ── Modal 3: Level Payouts ────────────────────────────────────────────── */}
      <Modal open={levelModalOpen} onClose={() => !levelSaving && setLevelModalOpen(false)} title="Confirm Level Payout Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="overflow-x-auto rounded-xl border border-slate-100">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  <th className="text-left px-4 py-2 text-xs font-semibold text-slate-500">Level</th>
                  <th className="text-right px-4 py-2 text-xs font-semibold text-slate-500">Gross (₹)</th>
                  <th className="text-right px-4 py-2 text-xs font-semibold text-slate-500">Net (₹)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {[1, 2, 3, 4, 5, 6].map(l => (
                  <tr key={l}>
                    <td className="px-4 py-2.5 font-bold text-slate-700">L{l}</td>
                    <td className="px-4 py-2.5 text-right text-slate-600">₹{levelPayouts[String(l)]?.gross ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right text-emerald-600 font-semibold">₹{levelPayouts[String(l)]?.net ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700">
              <Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password
            </label>
            <input
              type="password"
              className={inputCls}
              value={levelAdminPw}
              onChange={e => setLevelAdminPw(e.target.value)}
              onKeyDown={async e => {
                // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                if (e.key === 'Enter' && !levelSaving && levelAdminPw.trim()) {
                  setLevelSaving(true)
                  try {
                    const payload = {}
                    Object.entries(levelPayouts).forEach(([lvl, { gross, net }]) => {
                      payload[lvl] = { gross_inr: parseInt(gross, 10), net_inr: parseInt(net, 10) }
                    })
                    const r = await updateAllLevelPayouts(payload, levelAdminPw)
                    const refreshed = {}
                    Object.entries(r.data.all_level_payouts ?? {}).forEach(([l, { gross_inr, net_inr }]) => {
                      refreshed[l] = { gross: String(gross_inr), net: String(net_inr) }
                    })
                    if (Object.keys(refreshed).length) setLevelPayouts(refreshed)
                    setFinConfig(prev => ({ ...prev, level_payouts: r.data.all_level_payouts }))
                    toast(r.data.message, 'success')
                    setLevelModalOpen(false)
                    setLevelAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update level payouts', 'error') }
                  finally { setLevelSaving(false) }
                }
              }}
              placeholder="Enter admin password"
              autoFocus
            />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setLevelModalOpen(false); setLevelAdminPw('') }} disabled={levelSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button
              disabled={!levelAdminPw.trim() || levelSaving}
              onClick={async () => {
                setLevelSaving(true)
                try {
                  const payload = {}
                  Object.entries(levelPayouts).forEach(([lvl, { gross, net }]) => {
                    payload[lvl] = { gross_inr: parseInt(gross, 10), net_inr: parseInt(net, 10) }
                  })
                  const r = await updateAllLevelPayouts(payload, levelAdminPw)
                  const refreshed = {}
                  Object.entries(r.data.all_level_payouts ?? {}).forEach(([l, { gross_inr, net_inr }]) => {
                    refreshed[l] = { gross: String(gross_inr), net: String(net_inr) }
                  })
                  if (Object.keys(refreshed).length) setLevelPayouts(refreshed)
                  setFinConfig(prev => ({ ...prev, level_payouts: r.data.all_level_payouts }))
                  toast(r.data.message, 'success')
                  setLevelModalOpen(false)
                  setLevelAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update level payouts', 'error') }
                finally { setLevelSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {levelSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* ── Modal 4: LPI & Pressure Thresholds ───────────────────────────────── */}
      <Modal open={threshModalOpen} onClose={() => !threshSaving && setThreshModalOpen(false)} title="Confirm Threshold Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-amber-50 border border-amber-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-amber-800">Changing LPI thresholds alters Brain-5 draw-type routing. Incorrect values can force all draws into SDE or prevent SDE from triggering. Verify before saving.</p>
          </div>
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            {Object.entries(thresholds).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between px-4 py-2.5">
                <span className="text-xs text-slate-500 font-mono">{k}</span>
                <span className="text-sm font-bold text-amber-700">{v}</span>
              </div>
            ))}
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700">
              <Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password
            </label>
            <input
              type="password"
              className={inputCls}
              value={threshAdminPw}
              onChange={e => setThreshAdminPw(e.target.value)}
              onKeyDown={async e => {
                // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                if (e.key === 'Enter' && !threshSaving && threshAdminPw.trim()) {
                  setThreshSaving(true)
                  try {
                    const payload = Object.fromEntries(
                      Object.entries(thresholds).map(([k, v]) => [k, parseFloat(v)])
                    )
                    const r = await updateThresholds(payload, threshAdminPw)
                    setFinConfig(prev => ({ ...prev, ...r.data }))
                    toast(r.data.message, 'success')
                    setThreshModalOpen(false)
                    setThreshAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update thresholds', 'error') }
                  finally { setThreshSaving(false) }
                }
              }}
              placeholder="Enter admin password"
              autoFocus
            />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setThreshModalOpen(false); setThreshAdminPw('') }} disabled={threshSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button
              disabled={!threshAdminPw.trim() || threshSaving}
              onClick={async () => {
                setThreshSaving(true)
                try {
                  const payload = Object.fromEntries(
                    Object.entries(thresholds).map(([k, v]) => [k, parseFloat(v)])
                  )
                  const r = await updateThresholds(payload, threshAdminPw)
                  setFinConfig(prev => ({ ...prev, ...r.data }))
                  toast(r.data.message, 'success')
                  setThreshModalOpen(false)
                  setThreshAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update thresholds', 'error') }
                finally { setThreshSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {threshSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* ── Modal 5: Draw Chronology ──────────────────────────────────────────── */}
      <Modal open={chronoModalOpen} onClose={() => !chronoSaving && setChronoModalOpen(false)} title="Confirm Draw Chronology Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Frequency</span>
              <span className="text-sm font-bold text-violet-600 capitalize">{drawFrequency}</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Draw Day</span>
              <span className="text-sm font-bold text-violet-600">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][drawDayOfWeek] ?? drawDayOfWeek}</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Grace Period</span>
              <span className="text-sm font-bold text-violet-600">{gracePeriodHrs}h</span>
            </div>
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Cleanup Offset</span>
              <span className="text-sm font-bold text-violet-600">T+{cleanupMins} min</span>
            </div>
            {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
            <div className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-slate-500">Payment Due Offset</span>
              <span className="text-sm font-bold text-violet-600">T+{paymentDueDays} days</span>
            </div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700">
              <Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password
            </label>
            <input
              type="password"
              className={inputCls}
              value={chronoAdminPw}
              onChange={e => setChronoAdminPw(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter' && !chronoSaving && chronoAdminPw.trim()) {
                  setChronoSaving(true)
                  try {
                    const r = await updateDrawCalendar({
                      draw_frequency: drawFrequency,
                      draw_day_of_week: parseInt(drawDayOfWeek, 10),
                      grace_period_hours: parseInt(gracePeriodHrs, 10),
                      cleanup_offset_minutes: parseInt(cleanupMins, 10),
                      // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                      payment_due_offset_days: parseInt(paymentDueDays, 10),
                    }, chronoAdminPw)
                    setFinConfig(prev => ({ ...prev, ...r.data }))
                    toast(r.data.message, 'success')
                    setChronoModalOpen(false)
                    setChronoAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update draw chronology', 'error') }
                  finally { setChronoSaving(false) }
                }
              }}
              placeholder="Enter admin password"
              autoFocus
            />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setChronoModalOpen(false); setChronoAdminPw('') }} disabled={chronoSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button
              disabled={!chronoAdminPw.trim() || chronoSaving}
              onClick={async () => {
                setChronoSaving(true)
                try {
                  const r = await updateDrawCalendar({
                    draw_frequency: drawFrequency,
                    draw_day_of_week: parseInt(drawDayOfWeek, 10),
                    grace_period_hours: parseInt(gracePeriodHrs, 10),
                    cleanup_offset_minutes: parseInt(cleanupMins, 10),
                    // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                    payment_due_offset_days: parseInt(paymentDueDays, 10),
                  }, chronoAdminPw)
                  setFinConfig(prev => ({ ...prev, ...r.data }))
                  toast(r.data.message, 'success')
                  setChronoModalOpen(false)
                  setChronoAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update draw chronology', 'error') }
                finally { setChronoSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm"
            >
              {chronoSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

    </div>
  )
}
