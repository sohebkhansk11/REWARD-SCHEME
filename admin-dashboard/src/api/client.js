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

// On 401, clear stored credentials and redirect to /login
api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('rs_admin_jwt')
      localStorage.removeItem('rs_admin_name')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
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
export const checkWaitlist = () => api.post('/admin/waitlist/check')

// ── Pool Creation Settings ────────────────────────────────────────────────────
/** GET  /admin/pool-settings — returns { auto_pool_creation_enabled, message } */
export const getPoolSettings     = ()        => api.get('/admin/pool-settings')
/** POST /admin/pool-settings/auto-creation?enabled=bool — flips the toggle */
export const setAutoPoolCreation = (enabled) => api.post(`/admin/pool-settings/auto-creation?enabled=${enabled}`)
/** POST /admin/pools/manual-create — force-create pool from oldest paid waitlist members */
export const manualCreatePool    = ()        => api.post('/admin/pools/manual-create')

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

/** DELETE /admin/users/{id} — permanently delete user + owned tokens */
export const adminDeleteUser = (userId) =>
  api.delete(`/admin/users/${userId}`)

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

// ── Auth (no JWT needed for these calls) ──────────────────────────────────────
export const adminLogin     = (username, password) =>
  api.post('/admin/auth/login',      { username, password })
export const adminVerifyOTP = (temp_token, otp)    =>
  api.post('/admin/auth/verify-otp', { temp_token, otp })
export const adminSetup     = (username, password, setup_secret) =>
  api.post('/admin/auth/setup',      { username, password, setup_secret })

export default api
