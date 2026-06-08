import { createContext, useContext, useState, useCallback } from 'react'

const AuthCtx = createContext(null)

const STORAGE_KEY = 'rs_admin_jwt'

export function AuthProvider({ children }) {
  const [token, setToken]   = useState(() => localStorage.getItem(STORAGE_KEY) ?? null)
  const [adminName, setAdminName] = useState(
    () => localStorage.getItem('rs_admin_name') ?? null
  )

  const login = useCallback((jwt, username) => {
    localStorage.setItem(STORAGE_KEY, jwt)
    localStorage.setItem('rs_admin_name', username)
    setToken(jwt)
    setAdminName(username)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem('rs_admin_name')
    setToken(null)
    setAdminName(null)
  }, [])

  return (
    <AuthCtx.Provider value={{ token, adminName, isAuthed: !!token, login, logout }}>
      {children}
    </AuthCtx.Provider>
  )
}

export const useAuth = () => useContext(AuthCtx)
