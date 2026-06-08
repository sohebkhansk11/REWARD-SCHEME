import axios from 'axios'

// In development this falls back to localhost.
// In production Vercel injects VITE_API_URL from your project environment variables.
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({ baseURL: BASE_URL })

export const findUserByMobile = (mobile)  => api.get('/users/', { params: { mobile } })
export const registerUser     = (data)    => api.post('/users/', data)
export const getUser          = (id)      => api.get(`/users/${id}`)
export const redeemToken      = (code, userId) =>
  api.post(`/tokens/${encodeURIComponent(code)}/redeem`, { user_id: userId })

export default api
