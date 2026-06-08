import { createContext, useContext, useState, useCallback } from 'react'

const Ctx = createContext(null)

const JWT_KEY  = 'rs_user_jwt'
const USER_KEY = 'rs_user'

export function UserProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(JWT_KEY) ?? null)
  const [user,  setUser]  = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null }
  })

  /** Called after successful login or registration. */
  const login = useCallback((userData, jwt) => {
    setUser(userData)
    localStorage.setItem(USER_KEY, JSON.stringify(userData))
    if (jwt) {
      setToken(jwt)
      localStorage.setItem(JWT_KEY, jwt)
    }
  }, [])

  /** Clear everything and send to auth screen. */
  const logout = useCallback(() => {
    setUser(null)
    setToken(null)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(JWT_KEY)
  }, [])

  /** Refresh only the user object (e.g. after a token redemption). */
  const refresh = useCallback((updatedUser) => {
    setUser(updatedUser)
    localStorage.setItem(USER_KEY, JSON.stringify(updatedUser))
  }, [])

  return (
    <Ctx.Provider value={{
      user,
      token,
      isAuthed: !!token,   // true only when a real JWT is present
      login,
      logout,
      refresh,
    }}>
      {children}
    </Ctx.Provider>
  )
}

export const useUser = () => useContext(Ctx)
