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
export const authRegister = (data)               => api.post('/auth/register', data)
export const authLogin    = (username, password) => api.post('/auth/login', { username, password })
export const authMe       = ()                   => api.get('/auth/me')

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

// ── Tokens ────────────────────────────────────────────────────────────────────
export const redeemToken = (code, userId) =>
  api.post(`/tokens/${encodeURIComponent(code)}/redeem`, { user_id: userId })

// Keep these for any remaining legacy code
export const registerUser = (data) => api.post('/users/', data)

export default api
