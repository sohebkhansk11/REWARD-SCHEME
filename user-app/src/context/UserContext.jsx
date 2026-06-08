import { createContext, useContext, useState } from 'react'

const Ctx = createContext(null)

export function UserProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('rs_user')) } catch { return null }
  })

  const login = data => {
    setUser(data)
    localStorage.setItem('rs_user', JSON.stringify(data))
  }

  const logout = () => {
    setUser(null)
    localStorage.removeItem('rs_user')
  }

  const refresh = data => {
    const updated = { ...user, ...data }
    setUser(updated)
    localStorage.setItem('rs_user', JSON.stringify(updated))
  }

  return <Ctx.Provider value={{ user, login, logout, refresh }}>{children}</Ctx.Provider>
}

export const useUser = () => useContext(Ctx)
