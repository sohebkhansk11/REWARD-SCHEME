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

// ── Users ────────────────────────────────────────────────────────────────────
export const getUsers   = (params) => api.get('/users/',   { params: { limit: 500, ...params } })

// ── Pools ────────────────────────────────────────────────────────────────────
export const getPools   = (params) => api.get('/pools/',   { params: { limit: 100, ...params } })

// ── Tokens ───────────────────────────────────────────────────────────────────
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
export const applyDailyPenalty   = () => api.post('/admin/penalty/apply-daily')
export const eliminateUnpaid     = () => api.post('/admin/penalty/eliminate-unpaid')

// ── Auth (no JWT needed for these two calls) ──────────────────────────────────
export const adminLogin      = (username, password)    =>
  api.post('/admin/auth/login',      { username, password })
export const adminVerifyOTP  = (temp_token, otp)       =>
  api.post('/admin/auth/verify-otp', { temp_token, otp })
export const adminSetup      = (username, password, telegram_chat_id, setup_secret) =>
  api.post('/admin/auth/setup',      { username, password, telegram_chat_id, setup_secret })

export default api
