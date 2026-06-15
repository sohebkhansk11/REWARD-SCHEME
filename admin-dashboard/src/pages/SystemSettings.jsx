/**
 * SystemSettings.jsx
 * ==================
 * Admin-only settings panel for ALL runtime-configurable system parameters.
 *
 * SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
 * Full redesign — 4 switchable top-nav tabs replacing long-scroll single page.
 * Absorbed Compliance Config (Elimination & Grace Period) from PaymentCompliance.
 * Added grace_close_offset_minutes (30th key) to Draw Chronology section.
 *
 * Tab layout:
 *   [Pool Creation] [Draw Calendar] [Financial Strategy] [Compliance Config]
 *
 * Design rules applied consistently across all tabs:
 *   • SettingCard shell for every section (icon, title, subtitle, badge)
 *   • StatRow for read-only current-value rows
 *   • NumInput for numeric edits
 *   • SelectRow for dropdown/toggle rows (Compliance tab)
 *   • Amber/violet/red/blue info banners depending on context
 *   • "Save — Requires Password" lock-button pattern
 *   • All modals: confirm table + Lock password input + Confirm/Cancel buttons
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Settings, RefreshCw, Sliders, AlertTriangle,
  CheckCircle2, Lock, ChevronRight, Calendar,
  DollarSign, TrendingUp, Activity, ShieldAlert,
  Timer, Info, Save,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import Modal from '../components/Modal'
import {
  getThreshold, updateThreshold,
  getDrawSchedule, updateDrawSchedule,
  getFinancialConfig,
  updateBaseFinancial, updateLateFees,
  updateAllLevelPayouts, updateThresholds,
  updateDrawCalendar,
  getEliminationSettings, updateEliminationSettings,
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

// ─── Compliance: labelled two-column row ─────────────────────────────────────
function SelectRow({ label, hint, children }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 items-start gap-3 py-4 border-b border-slate-100 last:border-0">
      <div>
        <p className="text-sm font-semibold text-slate-700">{label}</p>
        {hint && <p className="text-xs text-slate-400 mt-0.5">{hint}</p>}
      </div>
      <div className="sm:col-span-2">{children}</div>
    </div>
  )
}

// ─── Compliance: toggle switch ────────────────────────────────────────────────
function Toggle({ checked, onChange }) {
  return (
    <button type="button" role="switch" aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors ${checked ? 'bg-emerald-500' : 'bg-slate-200'}`}>
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  )
}

// ─── Compliance: dropdown options ─────────────────────────────────────────────
const DUE_DAY_OPTIONS = [
  { value: 1, label: 'Monday (Day 1 after draw)'    },
  { value: 2, label: 'Tuesday (Day 2 after draw)'   },
  { value: 3, label: 'Wednesday (Day 3 after draw)' },
  { value: 4, label: 'Thursday (Day 4 after draw)'  },
  { value: 5, label: 'Friday (Day 5 after draw)'    },
  { value: 6, label: 'Saturday (Day 6 after draw)'  },
]
const DUE_HOUR_OPTIONS = [
  { value: 0,  label: '12:00 AM (Midnight)' },
  { value: 6,  label: '6:00 AM'  },
  { value: 8,  label: '8:00 AM'  },
  { value: 10, label: '10:00 AM' },
  { value: 12, label: '12:00 PM (Noon)' },
  { value: 14, label: '2:00 PM'  },
  { value: 16, label: '4:00 PM'  },
  { value: 18, label: '6:00 PM'  },
  { value: 20, label: '8:00 PM'  },
  { value: 22, label: '10:00 PM' },
  { value: 23, label: '11:00 PM' },
]
const LATE_FEE_OPTIONS = [
  { value: 0,   label: '₹0 / day (no late fee)'      },
  { value: 25,  label: '₹25 / day (2.5% of deposit)' },
  { value: 50,  label: '₹50 / day (5% of deposit)'   },
  { value: 75,  label: '₹75 / day (7.5% of deposit)' },
  { value: 100, label: '₹100 / day (10% of deposit)' },
  { value: -1,  label: 'Custom amount per day →'      },
]
const GRACE_HOURS_OPTIONS = [
  { value: 12,  label: '12 hours'           },
  { value: 24,  label: '24 hours (1 day)'   },
  { value: 36,  label: '36 hours'           },
  { value: 48,  label: '48 hours (2 days)'  },
  { value: 72,  label: '72 hours (3 days)'  },
  { value: 96,  label: '96 hours (4 days)'  },
  { value: 120, label: '120 hours (5 days)' },
  { value: 168, label: '168 hours (7 days)' },
]

// ─── Shared save button ───────────────────────────────────────────────────────
function SaveBtn({ onClick, disabled, color = 'indigo', children }) {
  const cls = {
    indigo:  'bg-indigo-600 hover:bg-indigo-700',
    violet:  'bg-violet-600 hover:bg-violet-700',
    emerald: 'bg-emerald-600 hover:bg-emerald-700',
    slate:   'bg-slate-700 hover:bg-slate-800',
    amber:   'bg-amber-600 hover:bg-amber-700',
    rose:    'bg-rose-600 hover:bg-rose-700',
    blue:    'bg-blue-600 hover:bg-blue-700',
  }[color] ?? 'bg-indigo-600 hover:bg-indigo-700'
  return (
    <button onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-2 px-4 py-2 ${cls} text-white rounded-xl text-sm font-semibold shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed`}>
      {children}
    </button>
  )
}

// ─── Tab definitions ──────────────────────────────────────────────────────────
// SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
const TABS = [
  { id: 'pool',       label: 'Pool Creation',      icon: Sliders,     activeColor: 'bg-indigo-600 text-white border-indigo-600',  dotColor: 'bg-indigo-500' },
  { id: 'calendar',   label: 'Draw Calendar',      icon: Calendar,    activeColor: 'bg-violet-600 text-white border-violet-600',  dotColor: 'bg-violet-500' },
  { id: 'financial',  label: 'Financial Strategy', icon: DollarSign,  activeColor: 'bg-emerald-600 text-white border-emerald-600', dotColor: 'bg-emerald-500' },
  { id: 'compliance', label: 'Compliance Config',  icon: ShieldAlert, activeColor: 'bg-rose-600 text-white border-rose-600',      dotColor: 'bg-rose-500' },
]

// ═════════════════════════════════════════════════════════════════════════════
// Page component
// ═════════════════════════════════════════════════════════════════════════════

export default function SystemSettings() {
  const toast = useToast()

  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Active tab
  const [settingsTab, setSettingsTab] = useState('pool')

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
  const [schedule,     setSchedule]     = useState(null)
  const [drawHour,     setDrawHour]     = useState('')
  const [drawMinute,   setDrawMinute]   = useState('')
  const [drawPrep,     setDrawPrep]     = useState('')

  // ── Draw Schedule modal ───────────────────────────────────────────────────
  const [drawModalOpen,   setDrawModalOpen]   = useState(false)
  const [drawAdminPw,     setDrawAdminPw]     = useState('')
  const [drawSaveLoading, setDrawSaveLoading] = useState(false)

  // ── Financial config state ────────────────────────────────────────────────
  const [finConfig,       setFinConfig]       = useState(null)
  const [finLoading,      setFinLoading]      = useState(false) // eslint-disable-line no-unused-vars

  // Base Financial
  const [baseInstallment, setBaseInstallment] = useState('')
  const [payoutFee,       setPayoutFee]       = useState('')
  const [baseModalOpen,   setBaseModalOpen]   = useState(false)
  const [baseAdminPw,     setBaseAdminPw]     = useState('')
  const [baseSaving,      setBaseSaving]      = useState(false)

  // Late Fees
  const [lateFeeDaily,    setLateFeeDaily]    = useState('')
  const [lateFeeMaxCap,   setLateFeeMaxCap]   = useState('')
  const [lateModalOpen,   setLateModalOpen]   = useState(false)
  const [lateAdminPw,     setLateAdminPw]     = useState('')
  const [lateSaving,      setLateSaving]      = useState(false)

  // Level Payouts
  const [levelPayouts,    setLevelPayouts]    = useState({})
  const [levelModalOpen,  setLevelModalOpen]  = useState(false)
  const [levelAdminPw,    setLevelAdminPw]    = useState('')
  const [levelSaving,     setLevelSaving]     = useState(false)

  // LPI Thresholds
  const [thresholds,      setThresholds]      = useState({
    lpi_regular_max: '', lpi_type_a_min: '', lpi_sde_proactive: '',
    lpi_l3_win_exception: '', cascade_prevent_l3_thresh: '', accel_diss_trigger_ratio: '',
  })
  const [threshModalOpen, setThreshModalOpen] = useState(false)
  const [threshAdminPw,   setThreshAdminPw]   = useState('')
  const [threshSaving,    setThreshSaving]    = useState(false)

  // Draw Chronology
  const [drawFrequency,    setDrawFrequency]    = useState('weekly')
  const [drawDayOfWeek,    setDrawDayOfWeek]    = useState(6)
  const [gracePeriodHrs,   setGracePeriodHrs]   = useState('')
  const [cleanupMins,      setCleanupMins]      = useState('')
  const [paymentDueDays,   setPaymentDueDays]   = useState(4)
  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  const [graceCloseMins,   setGraceCloseMins]   = useState(5)
  const [chronoModalOpen,  setChronoModalOpen]  = useState(false)
  const [chronoAdminPw,    setChronoAdminPw]    = useState('')
  const [chronoSaving,     setChronoSaving]     = useState(false)

  // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
  // Compliance Config state (absorbed from PaymentCompliance Settings tab)
  const [elimSettings,   setElimSettings]   = useState(null)
  const [elimForm,       setElimForm]       = useState({})
  const [elimPw,         setElimPw]         = useState('')
  const [elimSaving,     setElimSaving]     = useState(false)
  const [feeMode,        setFeeMode]        = useState('preset')
  const [customFee,      setCustomFee]      = useState(50)
  const [graceMode,      setGraceMode]      = useState('preset')
  const [customGrace,    setCustomGrace]    = useState(48)

  // ── Helper: populate financial state ─────────────────────────────────────
  const _applyFinConfig = useCallback((cfg) => {
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
      lpi_regular_max:           String(cfg.lpi_regular_max),
      lpi_type_a_min:            String(cfg.lpi_type_a_min),
      lpi_sde_proactive:         String(cfg.lpi_sde_proactive),
      lpi_l3_win_exception:      String(cfg.lpi_l3_win_exception),
      cascade_prevent_l3_thresh: String(cfg.cascade_prevent_l3_thresh),
      accel_diss_trigger_ratio:  String(cfg.accel_diss_trigger_ratio),
    })
    setDrawFrequency(cfg.draw_frequency)
    setDrawDayOfWeek(cfg.draw_day_of_week)
    setGracePeriodHrs(String(cfg.grace_period_hours))
    setCleanupMins(String(cfg.cleanup_offset_minutes))
    setPaymentDueDays(String(cfg.payment_due_offset_days ?? 4))
    // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    setGraceCloseMins(String(cfg.grace_close_offset_minutes ?? 5))
  }, [])

  // ── Helper: populate elimination settings ─────────────────────────────────
  const _applyElimSettings = useCallback((s) => {
    setElimSettings(s)
    setElimForm({ ...s })
    const preset = LATE_FEE_OPTIONS.find(o => o.value === (s.late_fee_per_day_inr ?? 50) && o.value !== -1)
    setFeeMode(preset ? 'preset' : 'custom')
    setCustomFee(s.late_fee_per_day_inr ?? 50)
    setGraceMode('preset')
    setCustomGrace(s.grace_period_hours ?? 48)
  }, [])

  // ── Fetch all settings ────────────────────────────────────────────────────
  const fetchSettings = useCallback(async (silent = false) => {
    if (!silent) setPageLoading(true)
    else setRefreshing(true)
    try {
      const [thrRes, schedRes, finRes, elimRes] = await Promise.allSettled([
        getThreshold(), getDrawSchedule(), getFinancialConfig(), getEliminationSettings(),
      ])
      if (thrRes.status === 'fulfilled') {
        const val = thrRes.value.data.pool_creation_threshold
        setThreshold(val); setInputVal(String(val))
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
      if (finRes && finRes.status === 'fulfilled') {
        _applyFinConfig(finRes.value.data)
      } else if (finRes) {
        toast(finRes.reason?.response?.data?.detail ?? 'Failed to load financial config', 'error')
      }
      if (elimRes && elimRes.status === 'fulfilled') {
        _applyElimSettings(elimRes.value.data)
      }
    } finally {
      setPageLoading(false)
      setRefreshing(false)
    }
  }, [_applyFinConfig, _applyElimSettings]) // eslint-disable-line react-hooks/exhaustive-deps

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
  const drawHourInt    = parseInt(drawHour,   10)
  const drawMinuteInt  = parseInt(drawMinute, 10)
  const drawPrepInt    = parseInt(drawPrep,   10)
  const drawInputValid = (
    !isNaN(drawHourInt)   && drawHourInt   >= 0 && drawHourInt   <= 23 &&
    !isNaN(drawMinuteInt) && drawMinuteInt >= 0 && drawMinuteInt <= 59 &&
    !isNaN(drawPrepInt)   && drawPrepInt   >= 1 && drawPrepInt   <= 6
  )
  const drawIsDirty = drawInputValid && schedule && (
    drawHourInt !== schedule.draw_hour_utc || drawMinuteInt !== schedule.draw_minute_utc || drawPrepInt !== schedule.draw_prep_hours
  )
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
  const handleCloseDrawModal  = () => { if (drawSaveLoading) return; setDrawModalOpen(false); setDrawAdminPw('') }
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

  // ── Draw Chronology save ──────────────────────────────────────────────────
  const _chronoPayload = () => ({
    draw_frequency:            drawFrequency,
    draw_day_of_week:          parseInt(drawDayOfWeek, 10),
    grace_period_hours:        parseInt(gracePeriodHrs, 10),
    cleanup_offset_minutes:    parseInt(cleanupMins, 10),
    payment_due_offset_days:   parseInt(paymentDueDays, 10),
    // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
    grace_close_offset_minutes: parseInt(graceCloseMins, 10),
  })
  const _doChronoSave = async (pw) => {
    setChronoSaving(true)
    try {
      const r = await updateDrawCalendar(_chronoPayload(), pw)
      setFinConfig(prev => ({ ...prev, ...r.data }))
      toast(r.data.message, 'success')
      setChronoModalOpen(false); setChronoAdminPw('')
    } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update draw chronology', 'error') }
    finally { setChronoSaving(false) }
  }

  // ── Compliance save ───────────────────────────────────────────────────────
  const handleElimSave = async () => {
    if (!elimPw.trim()) { toast('Admin password required', 'error'); return }
    setElimSaving(true)
    try {
      const payload = {
        ...elimForm,
        late_fee_per_day_inr: feeMode === 'custom' ? customFee : elimForm.late_fee_per_day_inr,
        grace_period_hours:   graceMode === 'custom' ? customGrace : elimForm.grace_period_hours,
        admin_password: elimPw,
      }
      await updateEliminationSettings(payload)
      toast('Compliance settings saved', 'success')
      setElimPw('')
      fetchSettings(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to save compliance settings', 'error')
    } finally { setElimSaving(false) }
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
    <div className="p-8 space-y-6">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Settings className="w-6 h-6 text-slate-600" />
            System Settings
          </h1>
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

      {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
          ── 4-Tab Top Navigation ──────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-1.5 flex gap-1.5 flex-wrap">
        {TABS.map(t => {
          const active = settingsTab === t.id
          return (
            <button
              key={t.id}
              onClick={() => setSettingsTab(t.id)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-150 border ${
                active ? `${t.activeColor} shadow-sm` : 'bg-transparent text-slate-500 border-transparent hover:bg-slate-50 hover:text-slate-700'
              }`}
            >
              <t.icon className="w-4 h-4 flex-shrink-0" />
              {t.label}
              {active && <span className={`w-1.5 h-1.5 rounded-full ${t.dotColor} opacity-70`} />}
            </button>
          )
        })}
      </div>

      {/* ══════════════════════════════════════════════════════════════════
          TAB 1 — Pool Creation
          ══════════════════════════════════════════════════════════════════ */}
      {settingsTab === 'pool' && (
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
            <StatRow label="Current threshold" value={threshold !== null ? `${threshold} members` : '—'} accent="text-indigo-600" />
            <StatRow label="Applies to"        value="Auto pool creation (when toggle is ON)" />
            <StatRow label="Default value"     value="24 members" accent="text-slate-500" />
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
                  inputIsDirty ? 'border-indigo-300 ring-1 ring-indigo-200'
                  : !inputIsValid && inputVal !== '' ? 'border-red-300 ring-1 ring-red-200' : ''
                }`}
                placeholder="e.g. 24"
              />
              <span className="text-sm text-slate-400 select-none">members (1 – 1,000)</span>
            </div>
            {inputVal !== '' && !inputIsValid && (
              <p className="text-xs text-red-500 flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" />Must be a whole number between 1 and 1,000
              </p>
            )}
            {inputIsDirty && (
              <p className="text-xs text-indigo-600 flex items-center gap-1">
                <ChevronRight className="w-3.5 h-3.5" />
                Changing from <strong>{threshold}</strong> → <strong>{parsedInput}</strong>
                &nbsp;({parsedInput > threshold ? `+${parsedInput - threshold}` : parsedInput - threshold})
              </p>
            )}
            <SaveBtn onClick={handleSaveClick} disabled={!inputIsDirty || refreshing} color="indigo">
              <Lock className="w-4 h-4" />Save — Requires Password
            </SaveBtn>
          </div>
        </SettingCard>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          TAB 2 — Draw Calendar
          ══════════════════════════════════════════════════════════════════ */}
      {settingsTab === 'calendar' && (
        <SettingCard
          icon={Calendar}
          iconBg="bg-violet-50"
          iconColor="text-violet-600"
          title="Draw Calendar"
          subtitle="Weekly draw time (UTC) and T-2H preparation window. APScheduler picks up changes on the next draw fire — no server restart needed."
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
            <StatRow label="Draw time (IST)"  value={schedule?.draw_time_ist ?? '—'} accent="text-violet-600" />
            <StatRow label="Prep window"      value={schedule ? `T-${schedule.draw_prep_hours}H (${schedule.draw_prep_hours} hours before draw)` : '—'} />
            <StatRow label="Default schedule" value="13:30 UTC · 7:00 PM IST · T-2H prep" accent="text-slate-500" />
          </div>

          <div className="flex items-start gap-3 p-4 rounded-xl bg-violet-50 border border-violet-100 mb-6">
            <AlertTriangle className="w-4 h-4 text-violet-600 flex-shrink-0 mt-0.5" />
            <div className="text-xs text-violet-800 leading-relaxed space-y-1">
              <p className="font-semibold">How draw timing works</p>
              <ul className="list-disc list-inside space-y-0.5 text-violet-700">
                <li>T-2H: start_draw_preparation() — LPI snapshot, SDE staging</li>
                <li>T-0H: execute_weekly_draw() — full mass draw + SDE execution reveal</li>
                <li>T+5m: post_draw_cleanup() — reset flags, release locks</li>
                <li>Draw day is always Sunday — change requires a code update</li>
                <li>Changes take effect on the NEXT Sunday APScheduler fire</li>
              </ul>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 mb-6">
            <NumInput label="Draw Hour (UTC)"  value={drawHour}   onChange={setDrawHour}   min={0} max={23} unit="h"   note="0–23 UTC" />
            <NumInput label="Draw Minute (UTC)"value={drawMinute} onChange={setDrawMinute} min={0} max={59} unit="m"   note="0–59" />
            <NumInput label="Prep Window"       value={drawPrep}   onChange={setDrawPrep}   min={1} max={6}  unit="hrs" note="1–6 hours before draw" />
          </div>

          {drawInputValid && (
            <div className="mb-4 flex items-center gap-2 px-4 py-2.5 bg-violet-50 border border-violet-100 rounded-xl">
              <Calendar className="w-4 h-4 text-violet-500 flex-shrink-0" />
              <p className="text-sm text-violet-700">
                Preview: Sunday <strong>{String(drawHourInt).padStart(2,'0')}:{String(drawMinuteInt).padStart(2,'0')} UTC</strong>
                {' = '}<strong>{previewIst}</strong>{' · Prep at '}<strong>T-{drawPrepInt}H</strong>
              </p>
            </div>
          )}
          {drawIsDirty && (
            <p className="text-xs text-violet-600 flex items-center gap-1 mb-3">
              <ChevronRight className="w-3.5 h-3.5" />
              Changing from <strong>{String(schedule.draw_hour_utc).padStart(2,'0')}:{String(schedule.draw_minute_utc).padStart(2,'0')} UTC / T-{schedule.draw_prep_hours}H</strong>
              {' → '}<strong>{String(drawHourInt).padStart(2,'0')}:{String(drawMinuteInt).padStart(2,'0')} UTC / T-{drawPrepInt}H</strong>
            </p>
          )}
          <SaveBtn onClick={handleDrawSaveClick} disabled={!drawIsDirty || refreshing} color="violet">
            <Lock className="w-4 h-4" />Save — Requires Password
          </SaveBtn>
        </SettingCard>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          TAB 3 — Financial Strategy
          ══════════════════════════════════════════════════════════════════ */}
      {settingsTab === 'financial' && (
        <SettingCard
          icon={DollarSign}
          iconBg="bg-emerald-50"
          iconColor="text-emerald-600"
          title="Draw & Financial Strategy"
          subtitle="DB-backed financial constants — base installment, level payouts L1-L6, LPI thresholds, cascade risk, draw chronology. All changes active within 60 seconds."
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

              {/* A — Base Financial */}
              <div>
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">A — Base Financial Amounts</p>
                <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100 mb-4">
                  <StatRow label="Base Installment"     value={`₹${finConfig.base_installment_inr}`} accent="text-emerald-600" />
                  <StatRow label="Payout Fee (per win)" value={`₹${finConfig.payout_fee_inr}`}       accent="text-slate-600" />
                  <StatRow label="Late Fee / Day"       value={`₹${finConfig.late_fee_daily_inr}`}   accent="text-slate-600" />
                  <StatRow label="Late Fee Cap"         value={`₹${finConfig.late_fee_max_cap_inr}`} accent="text-slate-600" />
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <NumInput label="Base Installment (₹)" value={baseInstallment} onChange={setBaseInstallment} min={100} max={10000} unit="₹" note="₹100–₹10,000" />
                  <NumInput label="Payout Fee (₹)"       value={payoutFee}       onChange={setPayoutFee}       min={0}   max={5000}  unit="₹" note="₹0–₹5,000" />
                </div>
                <SaveBtn onClick={() => { setBaseAdminPw(''); setBaseModalOpen(true) }} disabled={false} color="emerald">
                  <Lock className="w-4 h-4" />Save Base — Requires Password
                </SaveBtn>
              </div>

              {/* Late Fees */}
              <div>
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">Late Fees</p>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <NumInput label="Daily Rate (₹)"  value={lateFeeDaily}  onChange={setLateFeeDaily}  min={0} max={500}  unit="₹" note="₹0–₹500" />
                  <NumInput label="Maximum Cap (₹)" value={lateFeeMaxCap} onChange={setLateFeeMaxCap} min={0} max={5000} unit="₹" note="₹0–₹5,000" />
                </div>
                <SaveBtn onClick={() => { setLateAdminPw(''); setLateModalOpen(true) }} disabled={false} color="slate">
                  <Lock className="w-4 h-4" />Save Late Fees — Requires Password
                </SaveBtn>
              </div>

              {/* B — Level Payout Table */}
              <div>
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">B — Level Payout Table (L1–L6)</p>
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
                <SaveBtn onClick={() => { setLevelAdminPw(''); setLevelModalOpen(true) }} disabled={false} color="indigo">
                  <Lock className="w-4 h-4" />Save Level Payouts — Requires Password
                </SaveBtn>
              </div>

              {/* C — LPI Thresholds */}
              <div>
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">C — LPI &amp; Pressure Thresholds</p>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  {[
                    { key: 'lpi_regular_max',          label: 'LPI Regular Max (%)',   min: 1,    max: 100,  note: 'LPI < this → Regular draw' },
                    { key: 'lpi_type_a_min',           label: 'LPI Type A Min (%)',    min: 1,    max: 100,  note: 'LPI ≥ this → Type A draw' },
                    { key: 'lpi_sde_proactive',        label: 'LPI SDE Proactive (%)', min: 1,    max: 100,  note: 'LPI ≥ this → SDE proactive' },
                    { key: 'lpi_l3_win_exception',     label: 'L3 Win Exception (%)',  min: 1,    max: 100,  note: 'LPI > this → L3 wins SDE' },
                    { key: 'cascade_prevent_l3_thresh',label: 'Cascade Risk Threshold',min: 0.1,  max: 10,   note: 'cascade_risk > this → Preventive L3' },
                    { key: 'accel_diss_trigger_ratio', label: 'Accel Dissolve Ratio',  min: 0.10, max: 1.00, note: 'L4+ fraction → Accel Dissolution' },
                  ].map(({ key, label, min, max, note }) => (
                    <NumInput key={key} label={label}
                      value={thresholds[key]}
                      onChange={v => setThresholds(p => ({ ...p, [key]: v }))}
                      min={min} max={max} note={note}
                    />
                  ))}
                </div>
                <SaveBtn onClick={() => { setThreshAdminPw(''); setThreshModalOpen(true) }} disabled={false} color="amber">
                  <Lock className="w-4 h-4" />Save Thresholds — Requires Password
                </SaveBtn>
              </div>

              {/* D — Draw Chronology */}
              <div>
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">D — Draw Chronology</p>
                <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100 mb-4">
                  <StatRow label="Draw Frequency"          value={finConfig.draw_frequency}  accent="text-violet-600" />
                  <StatRow label="Draw Day"                value={finConfig.draw_day_name}   accent="text-violet-600" />
                  <StatRow label="Grace Period"            value={`${finConfig.grace_period_hours}h`} />
                  <StatRow label="Cleanup Offset"          value={`T+${finConfig.cleanup_offset_minutes}min`} />
                  <StatRow label="Payment Due Offset"      value={`T+${finConfig.payment_due_offset_days ?? 4}d`} />
                  {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
                  <StatRow label="Grace Close Offset"      value={`T-2H − ${finConfig.grace_close_offset_minutes ?? 5}min`} accent="text-rose-600" />
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
                  <NumInput label="Grace Period (hours)"     value={gracePeriodHrs}  onChange={setGracePeriodHrs}  min={1}  max={168} unit="hrs" note="1–168 hours (max 7 days)" />
                  <NumInput label="Cleanup Offset (min)"     value={cleanupMins}     onChange={setCleanupMins}     min={1}  max={60}  unit="min" note="Minutes after draw T-0H" />
                  <NumInput label="Payment Due Offset (days)"value={paymentDueDays}  onChange={setPaymentDueDays}  min={1}  max={27}  unit="days" note="Days after cycle start before on-time window closes (1–27)" />
                  {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
                  <NumInput label="Grace Close Offset (min)" value={graceCloseMins}  onChange={setGraceCloseMins}  min={1}  max={119} unit="min" note="Minutes before T-2H when grace closes & elimination locks (1–119)" />
                </div>
                <SaveBtn onClick={() => { setChronoAdminPw(''); setChronoModalOpen(true) }} disabled={false} color="violet">
                  <Lock className="w-4 h-4" />Save Draw Chronology — Requires Password
                </SaveBtn>
              </div>

            </div>
          )}
        </SettingCard>
      )}

      {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
          ══════════════════════════════════════════════════════════════════
          TAB 4 — Compliance Config (absorbed from PaymentCompliance)
          ══════════════════════════════════════════════════════════════════ */}
      {settingsTab === 'compliance' && (
        <SettingCard
          icon={ShieldAlert}
          iconBg="bg-rose-50"
          iconColor="text-rose-600"
          title="Elimination & Grace Period Configuration"
          subtitle="Late fee accrual, grace window duration, seat-save fee, auto-eliminate toggles. Changes require admin password and take effect from the next penalty cycle."
        >
          {!elimSettings ? (
            <div className="flex items-center justify-center py-8"><Spinner className="w-6 h-6 text-slate-300" /></div>
          ) : (
            <div className="space-y-6">

              {/* Info banner */}
              <div className="flex gap-3 p-4 bg-blue-50 border border-blue-200 rounded-xl text-sm text-blue-800">
                <Info className="w-4 h-4 flex-shrink-0 mt-0.5 text-blue-600" />
                <p>Due date settings are relative to the weekly draw (Sunday T+0). Grace period duration is the window between due date and T-2H.</p>
              </div>

              {/* Config rows */}
              <div className="bg-white rounded-xl border border-slate-100 divide-y divide-slate-100">

                {/* Due day */}
                <SelectRow label="Payment Due Day" hint="Days after draw opens (draw = Sunday T+0)">
                  <select value={elimForm.payment_due_days ?? 4} onChange={e => setElimForm(p => ({ ...p, payment_due_days: +e.target.value }))}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-rose-400">
                    {DUE_DAY_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </SelectRow>

                {/* Due hour */}
                <SelectRow label="Payment Due Time" hint="Hour of the due day (IST, 24-hour format)">
                  <select value={elimForm.payment_due_hour ?? 23} onChange={e => setElimForm(p => ({ ...p, payment_due_hour: +e.target.value }))}
                    className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-rose-400">
                    {DUE_HOUR_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </SelectRow>

                {/* Late fee rate */}
                <SelectRow label="Late Fee Rate" hint="Charged per day from due date until payment or elimination">
                  <div className="space-y-2">
                    <select
                      value={feeMode === 'custom' ? -1 : (elimForm.late_fee_per_day_inr ?? 50)}
                      onChange={e => {
                        const v = +e.target.value
                        if (v === -1) { setFeeMode('custom') }
                        else { setFeeMode('preset'); setElimForm(p => ({ ...p, late_fee_per_day_inr: v })) }
                      }}
                      className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-rose-400">
                      {LATE_FEE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                    {feeMode === 'custom' && (
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-slate-500">₹</span>
                        <input type="number" min={0} max={500} step={5} value={customFee}
                          onChange={e => { const v = Math.max(0, Math.min(500, +e.target.value || 0)); setCustomFee(v); setElimForm(p => ({ ...p, late_fee_per_day_inr: v })) }}
                          className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-400" placeholder="Custom ₹ per day" />
                        <span className="text-xs text-slate-400">/ day (max ₹500)</span>
                      </div>
                    )}
                    <p className="text-[11px] text-slate-400">₹1,000 deposit × 5% min = <strong>₹50/day</strong> minimum recommended</p>
                  </div>
                </SelectRow>

                {/* Late fee max cap */}
                <SelectRow label="Late Fee Max Cap" hint="Maximum total late fee accumulation before member is auto-eliminated">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-500">₹</span>
                    <input type="number" min={50} max={2000} step={50} value={elimForm.late_fee_max_cap_inr ?? 500}
                      onChange={e => setElimForm(p => ({ ...p, late_fee_max_cap_inr: Math.max(50, Math.min(2000, +e.target.value || 50)) }))}
                      className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-400" />
                    <span className="text-xs text-slate-400">maximum total</span>
                  </div>
                </SelectRow>

                {/* Grace period duration */}
                <SelectRow label="Grace Period Duration" hint="Window between due date and draw T-2H for seat-saving payment">
                  <div className="space-y-2">
                    <select
                      value={graceMode === 'custom' ? -1 : (elimForm.grace_period_hours ?? 48)}
                      onChange={e => {
                        const v = +e.target.value
                        if (v === -1) { setGraceMode('custom') }
                        else { setGraceMode('preset'); setElimForm(p => ({ ...p, grace_period_hours: v })) }
                      }}
                      className="w-full border border-slate-300 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-rose-400">
                      {GRACE_HOURS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      <option value={-1}>Custom hours →</option>
                    </select>
                    {graceMode === 'custom' && (
                      <div className="flex items-center gap-2">
                        <input type="number" min={1} max={168} step={1} value={customGrace}
                          onChange={e => { const v = Math.max(1, Math.min(168, +e.target.value || 1)); setCustomGrace(v); setElimForm(p => ({ ...p, grace_period_hours: v })) }}
                          className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-400" />
                        <span className="text-xs text-slate-400">hours (1–168)</span>
                      </div>
                    )}
                  </div>
                </SelectRow>

                {/* Grace seat-save fee */}
                <SelectRow label="Grace Seat-Save Fee" hint="Extra fee member must pay during grace period to keep their seat (in addition to late fees)">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-500">₹</span>
                    <input type="number" min={0} max={2000} step={50} value={elimForm.grace_seat_save_fee_inr ?? 500}
                      onChange={e => setElimForm(p => ({ ...p, grace_seat_save_fee_inr: Math.max(0, Math.min(2000, +e.target.value || 0)) }))}
                      className="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rose-400" />
                    <span className="text-xs text-slate-400">seat-save fee</span>
                  </div>
                </SelectRow>

                {/* Auto-eliminate toggle */}
                <SelectRow label="Auto-Eliminate" hint="Automatically eliminate unpaid members when due date passes">
                  <div className="flex items-center gap-3">
                    <Toggle checked={!!elimForm.auto_eliminate_enabled} onChange={v => setElimForm(p => ({ ...p, auto_eliminate_enabled: v }))} />
                    <span className={`text-sm font-semibold ${elimForm.auto_eliminate_enabled ? 'text-emerald-600' : 'text-slate-500'}`}>
                      {elimForm.auto_eliminate_enabled ? 'Enabled — system eliminates automatically' : 'Disabled — manual elimination only'}
                    </span>
                  </div>
                </SelectRow>

                {/* Grace period enabled */}
                <SelectRow label="Grace Period" hint="Allow members to pay late fee + seat-save fee during grace window to keep their pool position">
                  <div className="flex items-center gap-3">
                    <Toggle checked={!!elimForm.grace_period_enabled} onChange={v => setElimForm(p => ({ ...p, grace_period_enabled: v }))} />
                    <span className={`text-sm font-semibold ${elimForm.grace_period_enabled ? 'text-emerald-600' : 'text-slate-500'}`}>
                      {elimForm.grace_period_enabled ? 'Enabled — grace period window active' : 'Disabled — no grace window (immediate elimination)'}
                    </span>
                  </div>
                </SelectRow>

              </div>

              {/* Timeline Preview */}
              <div className="bg-blue-50 border border-blue-200 rounded-xl p-5 text-sm">
                <p className="font-bold text-blue-800 mb-3 flex items-center gap-2">
                  <Timer className="w-4 h-4" />Timeline Preview (based on Sunday T+0 draw)
                </p>
                <div className="space-y-1.5 text-blue-700">
                  <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-emerald-400 mt-1.5 flex-shrink-0" /><p><strong>Draw opens:</strong> Sunday T+0 — new payment cycle starts</p></div>
                  <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
                    <p><strong>Due date:</strong> Day {elimForm.payment_due_days ?? 4} at {DUE_HOUR_OPTIONS.find(o => o.value === (elimForm.payment_due_hour ?? 23))?.label ?? '11:00 PM'}</p>
                  </div>
                  <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-orange-400 mt-1.5 flex-shrink-0" />
                    <p><strong>Late payment window:</strong> Due date → Grace trigger (late fee ₹{feeMode === 'custom' ? customFee : (elimForm.late_fee_per_day_inr ?? 50)}/day, no seat risk)</p>
                  </div>
                  <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-violet-400 mt-1.5 flex-shrink-0" />
                    <p><strong>Grace period:</strong> {elimForm.grace_period_hours ?? 48}h window — pay ₹{elimForm.grace_seat_save_fee_inr ?? 500} + late fees to save seat</p>
                  </div>
                  <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-red-400 mt-1.5 flex-shrink-0" />
                    <p><strong>Grace closes:</strong> T-2H − {finConfig?.grace_close_offset_minutes ?? 5}min — elimination list locked</p>
                  </div>
                  <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-red-600 mt-1.5 flex-shrink-0" />
                    <p><strong>Elimination:</strong> T+0 draw executes — unpaid members removed (non-refundable)</p>
                  </div>
                  <div className="flex gap-2"><span className="w-2 h-2 rounded-full bg-blue-400 mt-1.5 flex-shrink-0" />
                    <p><strong>Late fee accrual:</strong> ₹{feeMode === 'custom' ? customFee : (elimForm.late_fee_per_day_inr ?? 50)}/day (max ₹{elimForm.late_fee_max_cap_inr ?? 500})</p>
                  </div>
                </div>
              </div>

              {/* Save section */}
              <div className="bg-slate-50 rounded-xl border border-slate-100 p-5 space-y-4">
                <p className="text-sm font-bold text-slate-700 flex items-center gap-2">
                  <Lock className="w-4 h-4 text-slate-400" />Admin Authorization Required
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <input type="password" value={elimPw} onChange={e => setElimPw(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && !elimSaving && elimPw.trim() && handleElimSave()}
                    className="border border-slate-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-rose-400"
                    placeholder="Enter admin password to save changes" />
                  <SaveBtn onClick={handleElimSave} disabled={elimSaving || !elimPw.trim()} color="rose">
                    {elimSaving ? <Spinner className="w-4 h-4 text-white" /> : <Save className="w-4 h-4" />}
                    Save Compliance Settings
                  </SaveBtn>
                </div>
                <p className="text-[11px] text-slate-400">Settings take effect from the next penalty cycle. Members currently in grace period are not affected until the window closes.</p>
              </div>

            </div>
          )}
        </SettingCard>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          MODALS — Pool Threshold
          ═══════════════════════════════════════════════════════════════════ */}
      <Modal open={confirmOpen} onClose={handleCloseConfirm} title="Confirm Threshold Change" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-amber-50 border border-amber-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-amber-800 text-sm">You are about to change a system parameter</p>
              <p className="text-xs text-amber-700 mt-1 leading-relaxed">This affects how quickly new pools auto-form. The change takes effect immediately and cannot be automatically rolled back.</p>
            </div>
          </div>
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Setting</span><span className="text-sm font-semibold text-slate-800">Pool Creation Threshold</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Current value</span><span className="text-sm font-semibold text-slate-600">{threshold} members</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">New value</span><span className="text-sm font-bold text-indigo-600">{pendingVal} members</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Net change</span><span className={`text-sm font-bold ${delta > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>{delta > 0 ? `+${delta}` : delta} members</span></div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700"><Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password</label>
            <input type="password" className={inputCls} value={adminPw} onChange={e => setAdminPw(e.target.value)} onKeyDown={e => e.key === 'Enter' && !saveLoading && handleConfirmSave()} placeholder="Enter your admin password to authorise this change" autoComplete="current-password" autoFocus />
            <p className="text-xs text-slate-400">Your password is verified server-side before the change is written.</p>
          </div>
          <div className="flex items-center justify-end gap-3 pt-1">
            <button onClick={handleCloseConfirm} disabled={saveLoading} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button onClick={handleConfirmSave} disabled={!adminPw.trim() || saveLoading} className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              {saveLoading ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm Change</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* ═══════════════════════════════════════════════════════════════════
          MODALS — Draw Schedule
          ═══════════════════════════════════════════════════════════════════ */}
      <Modal open={drawModalOpen} onClose={handleCloseDrawModal} title="Confirm Draw Schedule Change" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-violet-50 border border-violet-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-violet-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-violet-800 text-sm">Changing the weekly draw schedule</p>
              <p className="text-xs text-violet-700 mt-1 leading-relaxed">The new time takes effect on the next APScheduler fire. Ensure the new time is before the current draw if changing this week.</p>
            </div>
          </div>
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Setting</span><span className="text-sm font-semibold text-slate-800">Draw Calendar</span></div>
            {schedule && <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Current</span><span className="text-sm font-semibold text-slate-600">{String(schedule.draw_hour_utc).padStart(2,'0')}:{String(schedule.draw_minute_utc).padStart(2,'0')} UTC · T-{schedule.draw_prep_hours}H</span></div>}
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">New value</span><span className="text-sm font-bold text-violet-600">{String(drawHourInt).padStart(2,'0')}:{String(drawMinuteInt).padStart(2,'0')} UTC · T-{drawPrepInt}H</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">IST preview</span><span className="text-sm font-bold text-violet-600">{previewIst} (Sunday)</span></div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700"><Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password</label>
            <input type="password" className={inputCls} value={drawAdminPw} onChange={e => setDrawAdminPw(e.target.value)} onKeyDown={e => e.key === 'Enter' && !drawSaveLoading && handleConfirmDrawSave()} placeholder="Enter your admin password to authorise this change" autoComplete="current-password" autoFocus />
            <p className="text-xs text-slate-400">Your password is verified server-side before the change is written.</p>
          </div>
          <div className="flex items-center justify-end gap-3 pt-1">
            <button onClick={handleCloseDrawModal} disabled={drawSaveLoading} className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button onClick={handleConfirmDrawSave} disabled={!drawAdminPw.trim() || drawSaveLoading} className="flex items-center gap-2 px-5 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              {drawSaveLoading ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm Change</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* ═══════════════════════════════════════════════════════════════════
          MODALS — Financial Config (5 modals)
          ═══════════════════════════════════════════════════════════════════ */}

      {/* Modal 1: Base Financial */}
      <Modal open={baseModalOpen} onClose={() => !baseSaving && setBaseModalOpen(false)} title="Confirm Base Financial Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-emerald-800">Changing base installment affects all future payment calculations. Level payout amounts are independent — update them separately if needed.</p>
          </div>
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Base Installment</span><span className="text-sm font-bold text-emerald-600">₹{baseInstallment}</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Payout Fee</span><span className="text-sm font-bold text-emerald-600">₹{payoutFee}</span></div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700"><Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password</label>
            <input type="password" className={inputCls} value={baseAdminPw} onChange={e => setBaseAdminPw(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter' && !baseSaving && baseAdminPw.trim()) {
                  setBaseSaving(true)
                  try {
                    const r = await updateBaseFinancial(parseInt(baseInstallment, 10), parseInt(payoutFee, 10), baseAdminPw)
                    _applyFinConfig({ ...finConfig, ...r.data })
                    toast(r.data.message, 'success')
                    setBaseModalOpen(false); setBaseAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update base financial config', 'error') }
                  finally { setBaseSaving(false) }
                }
              }} placeholder="Enter admin password" autoFocus />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setBaseModalOpen(false); setBaseAdminPw('') }} disabled={baseSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button disabled={!baseAdminPw.trim() || baseSaving}
              onClick={async () => {
                setBaseSaving(true)
                try {
                  const r = await updateBaseFinancial(parseInt(baseInstallment, 10), parseInt(payoutFee, 10), baseAdminPw)
                  _applyFinConfig({ ...finConfig, ...r.data })
                  toast(r.data.message, 'success')
                  setBaseModalOpen(false); setBaseAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update base financial config', 'error') }
                finally { setBaseSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              {baseSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal 2: Late Fees */}
      <Modal open={lateModalOpen} onClose={() => !lateSaving && setLateModalOpen(false)} title="Confirm Late Fee Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Daily Rate</span><span className="text-sm font-bold text-slate-700">₹{lateFeeDaily} / day</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Maximum Cap</span><span className="text-sm font-bold text-slate-700">₹{lateFeeMaxCap}</span></div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700"><Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password</label>
            <input type="password" className={inputCls} value={lateAdminPw} onChange={e => setLateAdminPw(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter' && !lateSaving && lateAdminPw.trim()) {
                  setLateSaving(true)
                  try {
                    const r = await updateLateFees(parseInt(lateFeeDaily, 10), parseInt(lateFeeMaxCap, 10), lateAdminPw)
                    _applyFinConfig({ ...finConfig, ...r.data })
                    toast(r.data.message, 'success')
                    setLateModalOpen(false); setLateAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update late fees', 'error') }
                  finally { setLateSaving(false) }
                }
              }} placeholder="Enter admin password" autoFocus />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setLateModalOpen(false); setLateAdminPw('') }} disabled={lateSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button disabled={!lateAdminPw.trim() || lateSaving}
              onClick={async () => {
                setLateSaving(true)
                try {
                  const r = await updateLateFees(parseInt(lateFeeDaily, 10), parseInt(lateFeeMaxCap, 10), lateAdminPw)
                  _applyFinConfig({ ...finConfig, ...r.data })
                  toast(r.data.message, 'success')
                  setLateModalOpen(false); setLateAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update late fees', 'error') }
                finally { setLateSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-slate-700 hover:bg-slate-800 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              {lateSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal 3: Level Payouts */}
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
                {[1,2,3,4,5,6].map(l => (
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
            <label className="block text-sm font-semibold text-slate-700"><Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password</label>
            <input type="password" className={inputCls} value={levelAdminPw} onChange={e => setLevelAdminPw(e.target.value)}
              onKeyDown={async e => {
                // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                if (e.key === 'Enter' && !levelSaving && levelAdminPw.trim()) {
                  setLevelSaving(true)
                  try {
                    const payload = {}
                    Object.entries(levelPayouts).forEach(([lvl, { gross, net }]) => { payload[lvl] = { gross_inr: parseInt(gross, 10), net_inr: parseInt(net, 10) } })
                    const r = await updateAllLevelPayouts(payload, levelAdminPw)
                    const refreshed = {}
                    Object.entries(r.data.all_level_payouts ?? {}).forEach(([l, { gross_inr, net_inr }]) => { refreshed[l] = { gross: String(gross_inr), net: String(net_inr) } })
                    if (Object.keys(refreshed).length) setLevelPayouts(refreshed)
                    setFinConfig(prev => ({ ...prev, level_payouts: r.data.all_level_payouts }))
                    toast(r.data.message, 'success')
                    setLevelModalOpen(false); setLevelAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update level payouts', 'error') }
                  finally { setLevelSaving(false) }
                }
              }} placeholder="Enter admin password" autoFocus />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setLevelModalOpen(false); setLevelAdminPw('') }} disabled={levelSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button disabled={!levelAdminPw.trim() || levelSaving}
              onClick={async () => {
                setLevelSaving(true)
                try {
                  const payload = {}
                  Object.entries(levelPayouts).forEach(([lvl, { gross, net }]) => { payload[lvl] = { gross_inr: parseInt(gross, 10), net_inr: parseInt(net, 10) } })
                  const r = await updateAllLevelPayouts(payload, levelAdminPw)
                  const refreshed = {}
                  Object.entries(r.data.all_level_payouts ?? {}).forEach(([l, { gross_inr, net_inr }]) => { refreshed[l] = { gross: String(gross_inr), net: String(net_inr) } })
                  if (Object.keys(refreshed).length) setLevelPayouts(refreshed)
                  setFinConfig(prev => ({ ...prev, level_payouts: r.data.all_level_payouts }))
                  toast(r.data.message, 'success')
                  setLevelModalOpen(false); setLevelAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update level payouts', 'error') }
                finally { setLevelSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              {levelSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal 4: LPI Thresholds */}
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
            <label className="block text-sm font-semibold text-slate-700"><Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password</label>
            <input type="password" className={inputCls} value={threshAdminPw} onChange={e => setThreshAdminPw(e.target.value)}
              onKeyDown={async e => {
                // SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
                if (e.key === 'Enter' && !threshSaving && threshAdminPw.trim()) {
                  setThreshSaving(true)
                  try {
                    const payload = Object.fromEntries(Object.entries(thresholds).map(([k, v]) => [k, parseFloat(v)]))
                    const r = await updateThresholds(payload, threshAdminPw)
                    setFinConfig(prev => ({ ...prev, ...r.data }))
                    toast(r.data.message, 'success')
                    setThreshModalOpen(false); setThreshAdminPw('')
                  } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update thresholds', 'error') }
                  finally { setThreshSaving(false) }
                }
              }} placeholder="Enter admin password" autoFocus />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setThreshModalOpen(false); setThreshAdminPw('') }} disabled={threshSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button disabled={!threshAdminPw.trim() || threshSaving}
              onClick={async () => {
                setThreshSaving(true)
                try {
                  const payload = Object.fromEntries(Object.entries(thresholds).map(([k, v]) => [k, parseFloat(v)]))
                  const r = await updateThresholds(payload, threshAdminPw)
                  setFinConfig(prev => ({ ...prev, ...r.data }))
                  toast(r.data.message, 'success')
                  setThreshModalOpen(false); setThreshAdminPw('')
                } catch (err) { toast(err.response?.data?.detail ?? 'Failed to update thresholds', 'error') }
                finally { setThreshSaving(false) }
              }}
              className="flex items-center gap-2 px-5 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              {threshSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal 5: Draw Chronology */}
      <Modal open={chronoModalOpen} onClose={() => !chronoSaving && setChronoModalOpen(false)} title="Confirm Draw Chronology Update" maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="bg-slate-50 rounded-xl border border-slate-100 divide-y divide-slate-100">
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Frequency</span><span className="text-sm font-bold text-violet-600 capitalize">{drawFrequency}</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Draw Day</span><span className="text-sm font-bold text-violet-600">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][drawDayOfWeek] ?? drawDayOfWeek}</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Grace Period</span><span className="text-sm font-bold text-violet-600">{gracePeriodHrs}h</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Cleanup Offset</span><span className="text-sm font-bold text-violet-600">T+{cleanupMins} min</span></div>
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Payment Due Offset</span><span className="text-sm font-bold text-violet-600">T+{paymentDueDays} days</span></div>
            {/* SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]: */}
            <div className="flex items-center justify-between px-4 py-3"><span className="text-sm text-slate-500">Grace Close Offset</span><span className="text-sm font-bold text-rose-600">T-2H − {graceCloseMins} min</span></div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-semibold text-slate-700"><Lock className="w-3.5 h-3.5 inline mr-1.5 text-slate-400" />Admin Password</label>
            <input type="password" className={inputCls} value={chronoAdminPw} onChange={e => setChronoAdminPw(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter' && !chronoSaving && chronoAdminPw.trim()) await _doChronoSave(chronoAdminPw)
              }} placeholder="Enter admin password" autoFocus />
          </div>
          <div className="flex items-center justify-end gap-3">
            <button onClick={() => { setChronoModalOpen(false); setChronoAdminPw('') }} disabled={chronoSaving} className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50">Cancel</button>
            <button disabled={!chronoAdminPw.trim() || chronoSaving}
              onClick={() => _doChronoSave(chronoAdminPw)}
              className="flex items-center gap-2 px-5 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
              {chronoSaving ? <><Spinner className="w-4 h-4" />Saving…</> : <><CheckCircle2 className="w-4 h-4" />Confirm</>}
            </button>
          </div>
        </div>
      </Modal>

    </div>
  )
}
