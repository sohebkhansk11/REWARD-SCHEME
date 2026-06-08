import axios from 'axios'

// Uses VITE_API_URL env var if set, otherwise falls back to the live Render backend.
// For local development override this in admin-dashboard/.env
export const BASE_URL = import.meta.env.VITE_API_URL || 'https://reward-scheme-api.onrender.com'

const api = axios.create({ baseURL: BASE_URL })

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

export default api
