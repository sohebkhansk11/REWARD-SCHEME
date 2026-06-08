import axios from 'axios'

// Uses VITE_API_URL env var if set, otherwise falls back to the live Render backend.
// For local development override this in user-app/.env
const BASE_URL = import.meta.env.VITE_API_URL || 'https://reward-scheme-api.onrender.com'

const api = axios.create({ baseURL: BASE_URL })

export const findUserByMobile    = (mobile)   => api.get('/users/', { params: { mobile } })
export const findUserByUsername  = (username) => api.get('/users/', { params: { username } })
export const registerUser        = (data)     => api.post('/users/', data)
export const getUser          = (id)      => api.get(`/users/${id}`)
export const redeemToken      = (code, userId) =>
  api.post(`/tokens/${encodeURIComponent(code)}/redeem`, { user_id: userId })

export default api
