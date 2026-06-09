import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'https://reward-scheme-api.onrender.com'

const api = axios.create({ baseURL: BASE_URL })

// ── Auth interceptors ─────────────────────────────────────────────────────────

// Attach the user JWT to every request if one is stored in localStorage.
api.interceptors.request.use(config => {
  const token = localStorage.getItem('rs_user_jwt')
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  return config
})

// On 401, wipe credentials and send the user back to the auth screen.
api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('rs_user_jwt')
      localStorage.removeItem('rs_user')
      if (!window.location.pathname.endsWith('/')) {
        window.location.href = '/'
      }
    }
    return Promise.reject(err)
  }
)

// ── User Auth ─────────────────────────────────────────────────────────────────
export const authRegister     = (data)               => api.post('/auth/register', data)
export const authLogin        = (username, password) => api.post('/auth/login', { username, password })
export const authMe           = ()                   => api.get('/auth/me')
// Real-time referral code validation — no auth required, called during registration
export const validateReferral = (code)               => api.get(`/auth/validate-referral/${encodeURIComponent(code.trim().toUpperCase())}`)

// ── Users (public read — no JWT required) ────────────────────────────────────
export const findUserByMobile   = (mobile)   => api.get('/users/', { params: { mobile } })
export const findUserByUsername = (username) => api.get('/users/', { params: { username } })
export const getUser            = (id)       => api.get(`/users/${id}`)
export const getUsers           = (params)   => api.get('/users/', { params: { limit: 200, ...params } })

// ── User profile (JWT required via interceptor) ───────────────────────────────
export const updateProfile         = (data)           => api.patch('/auth/profile', data)
export const changePassword        = (oldPw, newPw)   => api.post('/auth/change-password', { old_password: oldPw, new_password: newPw })
export const rejoinWaitlist        = (depositToken)   => api.post('/auth/rejoin', { deposit_token: depositToken })
export const requestReferralPayout = ()               => api.post('/users/request-referral-payout')

// ── Deposit redemption (user-facing — uses user JWT, never admin JWT) ──────────
// The old redeemToken() called the admin-gated /tokens/{code}/redeem endpoint
// which returned 401 for user JWTs and triggered the logout interceptor.
// redeemDeposit() calls the correct user-facing endpoint instead.
export const redeemDeposit = (code) =>
  api.post('/auth/deposit/redeem', { deposit_token: code })

// ── Wallet history ─────────────────────────────────────────────────────────────
export const getWalletHistory = () => api.get('/users/me/wallet-history')

// ── Waitlist rank (JWT required — Waitlist users only) ────────────────────────
// Returns: { rank, total_waiting, status, message }
// rank is null when the user is not currently on the Waitlist.
export const getWaitlistRank = () => api.get('/users/me/waitlist-rank')

// Keep these for any remaining legacy code
export const registerUser = (data) => api.post('/users/', data)

export default api
