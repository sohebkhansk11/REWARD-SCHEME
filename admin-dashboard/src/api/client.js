import axios from 'axios'

// Uses VITE_API_URL env var if set, otherwise falls back to the live Render backend.
// For local development override this in admin-dashboard/.env
export const BASE_URL = import.meta.env.VITE_API_URL || 'https://reward-scheme-api.onrender.com'

const api = axios.create({ baseURL: BASE_URL })

// ── Auth interceptors ─────────────────────────────────────────────────────────

// Attach Bearer JWT to every request if one is stored in localStorage
api.interceptors.request.use(config => {
  const token = localStorage.getItem('rs_admin_jwt')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  return config
})

// Global response interceptor:
//  401 → clear auth state and redirect to /login
//  500/502/503/504 → attach a user-friendly message so catch blocks
//                    can display err.userMessage without parsing raw JSON
api.interceptors.response.use(
  res => res,
  err => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem('rs_admin_jwt')
      localStorage.removeItem('rs_admin_name')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    if ([500, 502, 503, 504].includes(status)) {
      err.userMessage =
        err.response?.data?.detail ||
        'The server encountered an error. Please try again or contact support.'
    }
    return Promise.reject(err)
  }
)

// ── Stats ────────────────────────────────────────────────────────────────────
export const getStats   = ()       => api.get('/admin/stats')

// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
/** GET /admin/stats/reconciliation — SSOT (single source of truth) payload.
 *  ONE authoritative server-computed snapshot every headline/pool view should
 *  consume so counts can never disagree ("84 active vs 577").  Computed from the
 *  User + Pool tables (never the denormalized counter).  Returns
 *  { users{}, active_placement{}, pools{}, active_by_level{}, winners{},
 *    capital{}, integrity{}, + flat active_users/active_pools/live_pools }. */
export const getReconciliation = () =>
  api.get('/admin/stats/reconciliation')

// ── Pools ────────────────────────────────────────────────────────────────────
export const getPools   = (params) => api.get('/pools/',   { params: { limit: 100, ...params } })

// ── Tokens (legacy public endpoint — used for quick recent list) ──────────────
export const getTokens  = (params) => api.get('/tokens/',  { params: { limit: 200, ...params } })

export const generateToken = (type, valueInr) =>
  api.post('/admin/tokens/generate', { type, value_inr: valueInr })

export const burnToken = (code) =>
  api.post(`/admin/tokens/${encodeURIComponent(code)}/burn`)

// ── Draw ─────────────────────────────────────────────────────────────────────
export const triggerDraw = (poolId) => api.post(`/admin/pools/${poolId}/draw`)

// ── Waitlist ─────────────────────────────────────────────────────────────────
export const checkWaitlist = () =>
  api.post('/admin/waitlist/check', undefined, { timeout: 120_000 })

// ── Pool Creation Settings ────────────────────────────────────────────────────
/** GET  /admin/pool-settings — returns { auto_pool_creation_enabled, message } */
export const getPoolSettings     = ()        => api.get('/admin/pool-settings')
/** POST /admin/pool-settings/auto-creation?enabled=bool — flips the toggle */
export const setAutoPoolCreation = (enabled) => api.post(`/admin/pool-settings/auto-creation?enabled=${enabled}`)
/** POST /admin/pools/manual-create — force-create pool from oldest paid waitlist members */
export const manualCreatePool       = ()        => api.post('/admin/pools/manual-create')
/** POST /admin/waitlist/check — fill existing pool vacancies then auto-scale */
export const fillPoolVacancies      = ()        =>
  api.post('/admin/waitlist/check', undefined, { timeout: 120_000 })
/** POST /admin/pools/sync-member-counts — recompute + fix stale pool.total_members */
export const syncPoolMemberCounts   = ()        => api.post('/admin/pools/sync-member-counts')

// ── Penalties ────────────────────────────────────────────────────────────────
export const applyDailyPenalty = () => api.post('/admin/penalty/apply-daily')
export const eliminateUnpaid   = () => api.post('/admin/penalty/eliminate-unpaid')

// ── Users (legacy public read — used by PoolOversight for member lists) ───────
export const getUsers = (params) => api.get('/users/', { params: { limit: 500, ...params } })

// ── Admin User Directory ──────────────────────────────────────────────────────
// Default limit 2000 — backend now supports up to 5000.  UserDirectory
// renders with a "Load More" pattern; this covers even large stress-test
// injections (2000+ users) in a single fetch without pagination overhead.
export const getAdminUsers  = (params) =>
  api.get('/admin/users', { params: { limit: 2000, ...params } })

export const getAdminUser   = (userId) => api.get(`/admin/users/${userId}`)

export const importUsersCsv = (file) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/admin/import/users', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ── Admin Token Audit ─────────────────────────────────────────────────────────
export const getAdminTokens = (params) =>
  api.get('/admin/tokens', { params: { limit: 500, ...params } })

// ── CSV Downloads (returns Blob for browser download) ─────────────────────────
export const downloadUsersCSV  = () =>
  api.get('/admin/export/users',  { responseType: 'blob' })

export const downloadTokensCSV = () =>
  api.get('/admin/export/tokens', { responseType: 'blob' })

/** Helper: trigger a browser file download from a Blob response. */
export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a   = document.createElement('a')
  a.href     = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ── Analytics — Phase 4A endpoints ───────────────────────────────────────────

/** GET /admin/stats/financials — full financial & liability snapshot */
export const getFinancials = () =>
  api.get('/admin/stats/financials')

/** GET /admin/stats/pools — pool-wise micro analytics + member lists */
export const getPoolStats = () =>
  api.get('/admin/stats/pools')

/** GET /admin/stats/tokens — DEP / WIT / REF breakdown by status */
export const getTokenStats = () =>
  api.get('/admin/stats/tokens')

/** GET /admin/stats/ai-forecast — waitlist velocity + liquidity runway */
export const getAiForecast = (lookbackDays = 30) =>
  api.get('/admin/stats/ai-forecast', { params: { lookback_days: lookbackDays } })

/** GET /admin/stats/charts — time-series chart data (day or week) */
export const getChartData = (days = 30, granularity = 'auto') =>
  api.get('/admin/stats/charts', { params: { days, granularity } })

/** PUT /admin/tokens/{id}/status — approve or reject a pending WIT token */
export const updateTokenStatus = (tokenId, action, note = undefined) =>
  api.put(`/admin/tokens/${tokenId}/status`, { action, ...(note ? { note } : {}) })

// ── Admin Deep User & Token Management (Phase 5) ──────────────────────────────

/** PUT /admin/users/{id}/full-update — patch any user field */
export const adminFullUpdateUser = (userId, data) =>
  api.put(`/admin/users/${userId}/full-update`, data)

/** DELETE /admin/users/{id} — permanently delete user + owned tokens (admin password required) */
export const adminDeleteUser = (userId, adminPassword) =>
  api.delete(`/admin/users/${userId}`, { data: { admin_password: adminPassword } })

/** DELETE /admin/tokens/{id} — permanently delete token (admin password required) */
export const adminDeleteToken = (tokenId, adminPassword) =>
  api.delete(`/admin/tokens/${tokenId}`, { data: { admin_password: adminPassword } })

// ── Referral Payout Queue (Phase 5) ───────────────────────────────────────────

/** GET /admin/referrals/pending — list Pending_Approval Referral_Withdraw tokens */
export const getPendingReferrals = () =>
  api.get('/admin/referrals/pending')

/** PUT /admin/referrals/{id}/status — approve or reject a referral payout */
export const updateReferralStatus = (tokenId, action, note = undefined) =>
  api.put(`/admin/referrals/${tokenId}/status`, { action, ...(note ? { note } : {}) })

/** PUT /admin/referrals/{id}/settle — mark approved payout as Burned after cash paid */
export const settleReferralPayout = (tokenId) =>
  api.put(`/admin/referrals/${tokenId}/settle`)

// ── Developer Mode — /dev/* endpoints (JWT + ENABLE_DEV_MODE=true required) ───
// JWT is attached automatically by the request interceptor above.

/** POST /dev/force-draw — instantly run Sunday draw; auto-pays unpaid members.
 *  @param poolId              Target pool (undefined → first active pool)
 *  @param autoPayInstallments When true, backend creates real Burned DEP records
 *                             before drawing so Cash Inflow stats are accurate.
 */
export const forceDrawDev = (poolId = undefined, autoPayInstallments = false) =>
  api.post('/dev/force-draw', {
    ...(poolId ? { pool_id: poolId } : {}),
    auto_pay_installments: autoPayInstallments,
  })

/** POST /dev/simulate-cycle — generate fake users + run N draw cycles.
 *  @param autoPayInstallments When true, backend creates Burned DEP records per
 *                             cycle so Total Collection figures stay accurate.
 */
export const simulateCycleDev = (nCycles = 3, cleanup = true, autoPayInstallments = false) =>
  api.post('/dev/simulate-cycle', {
    n_cycles: nCycles,
    cleanup,
    auto_pay_installments: autoPayInstallments,
  })

/** POST /dev/simulate-users — bulk-insert fake Waitlist users with Burned DEP tokens */
export const simulateUsersDev = (count, autoPool = true) =>
  api.post('/dev/simulate-users', { count, auto_pool: autoPool })

/** DELETE /dev/reset-data — nuke all users/pools/tokens; reset DB sequences */
export const resetDataDev = () =>
  api.delete('/dev/reset-data', { data: { confirm: 'CONFIRM_NUKE' } })

// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
// advancedSimulationDev (POST /dev/advanced-simulation) removed — the Fast Preview
// in-memory engine it called was deleted completely (Point 4: "fast stress test
// remove completely that is useless"). The Real-Engine background-job API below
// (startRealSimulation + polling) is the only simulation path now.

/**
 * POST /dev/real-simulation — Zero-duplication Real-Strategy Stress-Test Engine
 *
 * Calls the ACTUAL production services (draw, SDE, waitlist, Brain 2/3/5) on an
 * isolated in-memory SQLite database with mocked time (Chronos Engine).
 *
 * DRY guarantee: any rule change in production is automatically reflected.
 * Returns the canonical simulation-result schema consumed by the Stress Test panel.
 *
 * @param {Object} params
 * @param {number}  params.weeks                  1–200 (weekly draw cycles)
 * @param {number}  params.users_per_week          new users per week (0–2000)
 * @param {number}  params.initial_users           seed users before week 1 (≥12)
 * @param {number}  params.organic_ratio           0.0–1.0 (Brain 3 RDR feed)
 * @param {number}  params.late_users_ratio_pct    % who miss payment per week
 * @param {number}  params.elim_pct_a              A: % of late payers directly eliminated
 * @param {number}  params.grace_saver_pct_c       C: % of grace-eligible who survive
 * @param {boolean} params.volatility_mode         random weekly inflow
 * @param {number}  params.volatility_max_inflow   max inflow in volatility mode
 * @param {string}  params.inflow_pattern          K-12: linear|sine|burst|step
 * @param {number}  params.referral_burst_week     K-13: week for 2× referral surge (0=off)
 * @param {number}  params.payment_shock_week      K-14: week for payment shock (0=off)
 * @param {number}  params.waitlist_dropout_pct    K-15: % of waitlist who drop out (0–50)
 * @param {number}  params.organic_decay_rate      K-16: weekly organic ratio decay (0–1)
 * @param {string}  params.simulation_label        K-17: label for multi-run comparison
 */
/**
 * POST /dev/real-simulation — Start background Real-Engine simulation job.
 *
 * Returns { job_id, status:"queued", total_weeks, message } immediately
 * (< 200 ms).  No long HTTP hold — the engine runs in a daemon thread.
 * Poll getRealSimStatus(jobId) every 3 s for live progress.
 * Fetch getRealSimResult(jobId) when status == "done".
 *
 * Replaces the old realSimulationDev() which had a 600-second timeout and
 * was killed by Render's 60-second proxy timeout on runs > 12 weeks.
 */
export const startRealSimulation = (params) =>
  api.post('/dev/real-simulation', params, {
    timeout: 15_000,   // 15 s — only needs to register the job and start the thread
  })

/** @deprecated Use startRealSimulation() + polling instead. */
export const realSimulationDev = (params) =>
  api.post('/dev/real-simulation', params, {
    timeout: 15_000,   // kept for backwards-compat; now returns job_id, not result
  })

/**
 * GET /dev/real-simulation-status/{jobId}
 * Returns { job_id, status, current_week, total_weeks, percent, error_*, ... }
 * Call every 3 s while status is "queued" or "running".
 */
export const getRealSimStatus = (jobId) =>
  api.get(`/dev/real-simulation-status/${jobId}`, { timeout: 10_000 })

/**
 * GET /dev/real-simulation-result/{jobId}
 * Returns the full simulation result dict (the canonical Stress Test result schema).
 * Only call after getRealSimStatus() returns status == "done".
 * Returns 202 if still running, 500 with debugger info if failed.
 */
export const getRealSimResult = (jobId) =>
  api.get(`/dev/real-simulation-result/${jobId}`, { timeout: 30_000 })

/** GET /admin/draw/live-stream — Server-Sent Events for real-time draw monitoring (U-05) */
export const getDrawLiveStream = (token) => {
  const url = `${BASE_URL}/admin/draw/live-stream`
  // Uses fetch-event-source pattern: returns a URL + headers so callers can
  // use @microsoft/fetch-event-source or eventsource-parser with auth.
  return { url, headers: { Authorization: `Bearer ${token}` } }
}

// ── Winners History & AI Snapshot ────────────────────────────────────────────

/**
 * GET /admin/winners/history — paginated winner ledger with full journey data
 * @param {Object} params  { limit, offset, level, journey_type }
 */
export const getWinnersHistory = (params = {}) =>
  api.get('/admin/winners/history', { params })

/**
 * GET /admin/stats/level-breakdown — L1–L6 aggregate: winners, collected, distributed
 * Used by Statistics tab Level-Wise Financial Distribution BarChart.
 */
export const getLevelBreakdown = () =>
  api.get('/admin/stats/level-breakdown')

/**
 * GET /admin/stats/ai-snapshot — live AI quant engine system snapshot
 * Returns velocity, burn_rate, momentum, rdr, scenario, multiplier, etc.
 */
export const getAiSnapshot = () =>
  api.get('/admin/stats/ai-snapshot')

// ── Draw Engine — scheduler + manual execution ───────────────────────────────

/** GET /admin/draw/scheduler-status — APScheduler running state + next-run times */
export const getSchedulerStatus = () =>
  api.get('/admin/draw/scheduler-status')

/** POST /admin/draw/execute — Manually run the weekly draw (recovery / dev) */
export const manualExecuteDraw = () =>
  api.post('/admin/draw/execute')

/** GET /admin/draw/state — Current WeeklyDrawState */
export const getDrawState = () =>
  api.get('/admin/draw/state')

/** POST /admin/draw/prepare — Manually trigger T-2H preparation */
export const prepareWeeklyDraw = (drawTimeUtcIso) =>
  api.post('/admin/draw/prepare', null, { params: { draw_time_utc_iso: drawTimeUtcIso } })

/** POST /admin/draw/cleanup — Manually trigger post-draw cleanup */
export const triggerPostDrawCleanup = () =>
  api.post('/admin/draw/cleanup')

/** GET /admin/draw/override-dashboard — Admin override option A/B dashboard */
export const getOverrideDashboard = (weekId) =>
  api.get('/admin/draw/override-dashboard', { params: weekId ? { week_id: weekId } : {} })

/** POST /admin/draw/override-decision — Submit admin override choice */
export const submitOverrideDecision = (choice, weekId) =>
  api.post('/admin/draw/override-decision', null, {
    params: { choice, ...(weekId ? { week_id: weekId } : {}) }
  })

/** GET /draw/countdown — Two-flag authoritative countdown (public) */
export const getDrawCountdown = () =>
  api.get('/draw/countdown')

/** GET /admin/stats/brain5-lpi — Brain 5 LPI live snapshot */
export const getBrain5Lpi = () =>
  api.get('/admin/stats/brain5-lpi')

/** GET /admin/health — System health watchdog: DB pool, user/pool counts, last draw */
export const getSystemHealth = () =>
  api.get('/admin/health')

/** GET /admin/pipeline-health — Full pipeline health: DB pool + injection tasks + integrity */
export const getPipelineHealth = () =>
  api.get('/admin/pipeline-health')

// ── Payment Compliance & Elimination Engine ────────────────────────────────────

/** GET /admin/elimination/settings — all 8 elimination config settings */
export const getEliminationSettings = () =>
  api.get('/admin/elimination/settings')

/** PUT /admin/elimination/settings — update settings (admin password required) */
export const updateEliminationSettings = (data) =>
  api.put('/admin/elimination/settings', data)

/** GET /admin/elimination/late-payers — all unpaid active members */
export const getLatePayers = (params = {}) =>
  api.get('/admin/elimination/late-payers', { params })

/** GET /admin/elimination/at-risk — members past due date, not in grace */
export const getAtRiskUsers = (params = {}) =>
  api.get('/admin/elimination/at-risk', { params })

/** GET /admin/elimination/grace-period — members in grace period window */
export const getGracePeriodUsers = () =>
  api.get('/admin/elimination/grace-period')

/** GET /admin/elimination/history — EliminationEvent audit log */
export const getEliminationHistory = (params = {}) =>
  api.get('/admin/elimination/history', { params })

/** POST /admin/elimination/mark-at-risk — flag all unpaid-past-due users */
export const markAtRisk = () =>
  api.post('/admin/elimination/mark-at-risk')

/** POST /admin/elimination/grant-grace/:uid — move user to grace period */
export const grantGracePeriod = (uid, hours = 48) =>
  api.post(`/admin/elimination/grant-grace/${uid}`, { hours_until_expiry: hours })

/** POST /admin/elimination/save-seat/:uid — confirm grace payment received */
export const saveSeat = (uid, adminPassword, notes = undefined) =>
  api.post(`/admin/elimination/save-seat/${uid}`, {
    admin_password: adminPassword,
    ...(notes ? { notes } : {}),
  })

/** POST /admin/elimination/execute — run elimination cycle */
export const executeElimination = (adminPassword, dryRun = false) =>
  api.post('/admin/elimination/execute', {
    admin_password: adminPassword,
    dry_run: dryRun,
  })

// ── Developer Mode — new analytics endpoints ──────────────────────────────────

/** GET /dev/live-stats — Combined real-time statistics for dev panel */
export const devLiveStats = () =>
  api.get('/dev/live-stats')

/** GET /dev/level-map — All pools with member level breakdown */
export const devLevelMap = () =>
  api.get('/dev/level-map')

/** GET /dev/winners-analytics — Level-wise winner analysis */
export const devWinnersAnalytics = () =>
  api.get('/dev/winners-analytics')

/** GET /dev/projection — Next draw projection engine */
export const devProjection = () =>
  api.get('/dev/projection')

/** POST /dev/inject-timed — Inject users with custom date/time distribution.
 *  Pool formation now runs in background for count > 100; response returns
 *  immediately (~1s).  Poll getInjectionStatus(prefix) for pool-formation progress.
 */
export const devInjectTimed = (params) =>
  api.post('/dev/inject-timed', params, { timeout: 120_000 })

/** GET /dev/injection-status?prefix=<prefix> — Poll background pool-formation status */
export const getInjectionStatus = (prefix) =>
  api.get('/dev/injection-status', { params: { prefix } })

/** POST /dev/mark-all-paid — Master paid toggle for all active pool members */
export const devMarkAllPaid = () =>
  api.post('/dev/mark-all-paid')

/** POST /dev/set-payment-scenario — Set paid/late/elimination percentages */
export const devSetPaymentScenario = (params) =>
  api.post('/dev/set-payment-scenario', params)

/** GET /admin/stats/pause-calendar — rolling 90-day system pause heatmap */
export const getPauseCalendar = () =>
  api.get('/admin/stats/pause-calendar')

/** GET /admin/stats/weekly-pool-reports — per-week draw & pool activity report */
export const getWeeklyPoolReports = (weeks = 24) =>
  api.get('/admin/stats/weekly-pool-reports', { params: { weeks } })

// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
/** GET /admin/stats/weekly-timeline — system-birth-anchored week-by-week cumulative
 *  timeline (users in/out, cash in/out, pools created, draws, winners + running totals).
 *  Week 1 begins the instant the first user joins. */
export const getWeeklyTimeline = () =>
  api.get('/admin/stats/weekly-timeline')

/** GET /admin/stats/referral-trend — weekly RDR% trend for S-04 Referral Heatmap */
export const getReferralTrend = (weeks = 52) =>
  api.get('/admin/stats/referral-trend', { params: { weeks } })

/** GET /admin/stats/winner-level-trend — weekly winner level breakdown for S-03 panel */
export const getWinnerLevelTrend = (weeks = 24) =>
  api.get('/admin/stats/winner-level-trend', { params: { weeks } })

// ── System Settings ───────────────────────────────────────────────────────────

/** GET  /admin/settings/threshold — current pool-creation threshold */
export const getThreshold = () =>
  api.get('/admin/settings/threshold')

/** PUT  /admin/settings/threshold — update threshold (admin password required) */
export const updateThreshold = (newThreshold, adminPassword) =>
  api.put('/admin/settings/threshold', { new_threshold: newThreshold, admin_password: adminPassword })

// SESSION EDIT [Claude Session Jun-13 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Draw Calendar settings — runtime-configurable draw timing.
/** GET  /admin/settings/draw-schedule — current draw day/time/prep window */
export const getDrawSchedule    = () =>
  api.get('/admin/settings/draw-schedule')

/** PUT  /admin/settings/draw-schedule — update draw timing (admin password required) */
export const updateDrawSchedule = (drawHourUtc, drawMinuteUtc, drawPrepHours, adminPassword) =>
  api.put('/admin/settings/draw-schedule', {
    draw_hour_utc:   drawHourUtc,
    draw_minute_utc: drawMinuteUtc,
    draw_prep_hours: drawPrepHours,
    admin_password:  adminPassword,
  })

// SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
// Draw & Financial Strategy — backs the new admin sub-tab in System Settings.
/** GET  /admin/financial-config — full 30-key config snapshot */
export const getFinancialConfig = () =>
  api.get('/admin/financial-config')

/** PUT  /admin/financial-config/base — base installment + payout fee */
export const updateBaseFinancial = (baseInstallmentInr, payoutFeeInr, adminPassword) =>
  api.put('/admin/financial-config/base', {
    base_installment_inr: baseInstallmentInr,
    payout_fee_inr:       payoutFeeInr,
    admin_password:       adminPassword,
  })

/** PUT  /admin/financial-config/late-fees — daily rate + cap */
export const updateLateFees = (lateFeeDaily, lateFeeMaxCap, adminPassword) =>
  api.put('/admin/financial-config/late-fees', {
    late_fee_daily_inr:   lateFeeDaily,
    late_fee_max_cap_inr: lateFeeMaxCap,
    admin_password:       adminPassword,
  })

/** PUT  /admin/financial-config/level-payouts — bulk all 6 levels */
export const updateAllLevelPayouts = (payouts, adminPassword) =>
  api.put('/admin/financial-config/level-payouts', {
    payouts,
    admin_password: adminPassword,
  })

/** PUT  /admin/financial-config/thresholds — LPI + cascade + accel thresholds */
export const updateThresholds = (thresholdData, adminPassword) =>
  api.put('/admin/financial-config/thresholds', {
    ...thresholdData,
    admin_password: adminPassword,
  })

/** PUT  /admin/financial-config/draw-calendar — frequency, day, grace, cleanup */
export const updateDrawCalendar = (calendarData, adminPassword) =>
  api.put('/admin/financial-config/draw-calendar', {
    ...calendarData,
    admin_password: adminPassword,
  })

// SESSION EDIT [Claude Session Jun-15 — Soheb Khan User 2 / Sohebkhan.sk11]:
// ── Global System Debugger ────────────────────────────────────────────────────

/** POST /dev/debugger/toggle — { enabled: bool } — flip the debugger toggle */
export const toggleDebugger = (enabled) =>
  api.post('/dev/debugger/toggle', { enabled })

/** GET /dev/debugger/status — { enabled, run_id, week, log_count } */
export const getDebuggerStatus = () =>
  api.get('/dev/debugger/status')

/**
 * GET /dev/debugger/logs — paginated DebugLog rows, newest-first.
 * @param {{ run_id?, week_num?, phase?, limit?, offset? }} params
 */
export const getDebuggerLogs = (params = {}) =>
  api.get('/dev/debugger/logs', { params })

/** DELETE /dev/debugger/logs — clear all debug log entries */
export const clearDebuggerLogs = () =>
  api.delete('/dev/debugger/logs')

// SESSION EDIT [Claude Session Jun-16 — Soheb Khan User 2 / Sohebkhan.sk11]:
// ── Forensic Debugger (event-level "every breath" recorder) ───────────────────

/** POST /dev/forensic/toggle — { enabled: bool, run_id?: str } */
export const toggleForensic = (enabled, runId = undefined) =>
  api.post('/dev/forensic/toggle', { enabled, run_id: runId })

/** GET /dev/forensic/status — { enabled, run_id, week, tick, buffered, event_count } */
export const getForensicStatus = () =>
  api.get('/dev/forensic/status')

/**
 * GET /dev/forensic/events — paginated ForensicEvent rows.
 * @param {{ run_id?, week_id?, category?, event_type?, severity?, entity_id?,
 *           search?, order?, limit?, offset? }} params
 */
export const getForensicEvents = (params = {}) =>
  api.get('/dev/forensic/events', { params })

/** GET /dev/forensic/summary — aggregate counts by category/event/severity/week */
export const getForensicSummary = (params = {}) =>
  api.get('/dev/forensic/summary', { params })

/**
 * GET /dev/forensic/export — full filtered dump as a downloadable blob.
 * @param {'csv'|'json'} format
 * @param {object} filters — same filter keys as getForensicEvents
 */
export const exportForensicEvents = (format = 'csv', filters = {}) =>
  api.get('/dev/forensic/export', {
    params: { format, ...filters },
    responseType: 'blob',
  })

/** DELETE /dev/forensic/events — clear events (optionally scoped to one run_id) */
export const clearForensicEvents = (runId = undefined) =>
  api.delete('/dev/forensic/events', { params: runId ? { run_id: runId } : {} })

// ── Auth (no JWT needed for these calls) ──────────────────────────────────────
export const adminLogin     = (username, password) =>
  api.post('/admin/auth/login',      { username, password })
export const adminVerifyOTP = (temp_token, otp)    =>
  api.post('/admin/auth/verify-otp', { temp_token, otp })
export const adminSetup     = (username, password, setup_secret) =>
  api.post('/admin/auth/setup',      { username, password, setup_secret })

export default api
