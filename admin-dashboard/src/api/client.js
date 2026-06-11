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
export const getAdminUsers  = (params) =>
  api.get('/admin/users', { params: { limit: 500, ...params } })

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

/**
 * POST /dev/advanced-simulation — isolated stress-test engine
 * @param {Object} params
 * @param {number} params.total_cycles        1–1000
 * @param {number} params.late_fee_pct        default 5.0
 * @param {number} params.late_users_ratio_pct default 2.0
 * @param {boolean} params.volatility_mode    default false
 * @param {number} params.volatility_max_inflow default 100
 */
export const advancedSimulationDev = (params) =>
  api.post('/dev/advanced-simulation', params, {
    timeout: 120_000,   // 120 s — sufficient for 1000-cycle in-memory run
  })

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

/** POST /dev/inject-timed — Inject users with custom date/time distribution */
export const devInjectTimed = (params) =>
  api.post('/dev/inject-timed', params, { timeout: 60_000 })

/** POST /dev/mark-all-paid — Master paid toggle for all active pool members */
export const devMarkAllPaid = () =>
  api.post('/dev/mark-all-paid')

/** POST /dev/set-payment-scenario — Set paid/late/elimination percentages */
export const devSetPaymentScenario = (params) =>
  api.post('/dev/set-payment-scenario', params)

// ── System Settings ───────────────────────────────────────────────────────────

/** GET  /admin/settings/threshold — current pool-creation threshold */
export const getThreshold = () =>
  api.get('/admin/settings/threshold')

/** PUT  /admin/settings/threshold — update threshold (admin password required) */
export const updateThreshold = (newThreshold, adminPassword) =>
  api.put('/admin/settings/threshold', { new_threshold: newThreshold, admin_password: adminPassword })

// ── Auth (no JWT needed for these calls) ──────────────────────────────────────
export const adminLogin     = (username, password) =>
  api.post('/admin/auth/login',      { username, password })
export const adminVerifyOTP = (temp_token, otp)    =>
  api.post('/admin/auth/verify-otp', { temp_token, otp })
export const adminSetup     = (username, password, setup_secret) =>
  api.post('/admin/auth/setup',      { username, password, setup_secret })

export default api
