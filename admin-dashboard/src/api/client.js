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

// ── Auth (no JWT needed for these calls) ──────────────────────────────────────
export const adminLogin     = (username, password) =>
  api.post('/admin/auth/login',      { username, password })
export const adminVerifyOTP = (temp_token, otp)    =>
  api.post('/admin/auth/verify-otp', { temp_token, otp })
export const adminSetup     = (username, password, setup_secret) =>
  api.post('/admin/auth/setup',      { username, password, setup_secret })

export default api
