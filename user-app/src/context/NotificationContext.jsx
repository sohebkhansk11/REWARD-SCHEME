/**
 * NotificationContext.jsx — In-App Flash Notification System
 *
 * Provides the useNotifications() hook to any component that needs to:
 *   - Read the current notification list
 *   - Add a manual notification
 *   - Dismiss a notification
 *
 * The context also handles polling GET /auth/my-notifications every 60 seconds
 * when the user is authenticated.  Backend-driven notifications (elimination risk,
 * grace period, draw countdown) arrive this way.
 *
 * Local notifications (e.g. "Promoted!" toasts from the waitlist rank change) can
 * also be added inline via addNotification().
 */

import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { useUser } from './UserContext'

const NotificationContext = createContext(null)

// ── Polling interval ──────────────────────────────────────────────────────────
const POLL_INTERVAL_MS = 60_000   // 60 seconds

// ── API helper (no axios dependency here — raw fetch with JWT) ────────────────
async function fetchNotifications(jwt) {
  const base = import.meta.env.VITE_API_URL || 'https://reward-scheme-api.onrender.com'
  const res = await fetch(`${base}/auth/my-notifications`, {
    headers: {
      Authorization: `Bearer ${jwt}`,
      'Content-Type': 'application/json',
    },
    signal: AbortSignal.timeout(10_000),   // 10s timeout
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ── Provider ──────────────────────────────────────────────────────────────────
export function NotificationProvider({ children }) {
  const { isAuthed, token } = useUser()
  const [notifications, setNotifications] = useState([])   // active notices list
  const [lastPoll,      setLastPoll]      = useState(null) // Date of last successful poll
  const pollRef = useRef(null)

  // ── Auto-dismiss timer ────────────────────────────────────────────────────
  // Non-persistent notifications are removed after 8 seconds
  useEffect(() => {
    const ids = notifications
      .filter(n => !n.persistent && !n._scheduled)
      .map(n => n.id)

    ids.forEach(id => {
      const t = setTimeout(() => dismiss(id), 8_000)
      setNotifications(prev =>
        prev.map(n => (n.id === id ? { ...n, _scheduled: true } : n))
      )
      return () => clearTimeout(t)
    })
  }, [notifications.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Poll backend ──────────────────────────────────────────────────────────
  const poll = useCallback(async () => {
    if (!isAuthed || !token) return
    try {
      const data = await fetchNotifications(token)
      if (data?.notifications) {
        // Merge backend notifications — replace any existing backend ones
        setNotifications(prev => {
          const local = prev.filter(n => n._local)   // keep manually-added local notices
          const server = (data.notifications || []).map((n, i) => ({
            ...n,
            id:     `srv_${i}_${Date.now()}`,
            _local: false,
          }))
          return [...server, ...local]
        })
        setLastPoll(new Date())
      }
    } catch {
      // Polling failure is silent — don't show error toasts for background polling
    }
  }, [isAuthed, token])

  // Start/stop polling based on auth state
  useEffect(() => {
    if (!isAuthed) {
      clearInterval(pollRef.current)
      setNotifications([])
      return
    }
    poll()   // immediate first poll
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS)
    return () => clearInterval(pollRef.current)
  }, [isAuthed, poll])

  // ── Public API ────────────────────────────────────────────────────────────
  const addNotification = useCallback((notification) => {
    setNotifications(prev => [
      {
        id:         `local_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        persistent: false,
        _local:     true,
        _scheduled: false,
        ...notification,
      },
      ...prev,
    ])
  }, [])

  const dismiss = useCallback((id) => {
    setNotifications(prev => prev.filter(n => n.id !== id))
  }, [])

  const dismissAll = useCallback(() => {
    setNotifications([])
  }, [])

  const value = {
    notifications,
    addNotification,
    dismiss,
    dismissAll,
    lastPoll,
    poll,   // expose for manual refresh
  }

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export function useNotifications() {
  const ctx = useContext(NotificationContext)
  if (!ctx) throw new Error('useNotifications must be used inside NotificationProvider')
  return ctx
}
