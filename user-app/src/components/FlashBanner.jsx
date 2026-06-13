/**
 * FlashBanner.jsx — Stacked in-app flash notification banners
 *
 * Displayed below the page header, above the main content area.
 * Uses framer-motion for slide-in/slide-out animation.
 * Multiple banners stack vertically — newest on top.
 *
 * Banner types:
 *   danger  — red  background (grace period expiry, critical elimination risk)
 *   warning — amber background (payment overdue, elimination risk)
 *   info    — blue background  (draw approaching, general info)
 *   success — green background (seat saved, payment confirmed)
 *
 * Usage:
 *   import FlashBanner from '../components/FlashBanner'
 *   <FlashBanner />   ← renders inside the page, reads from NotificationContext
 */

import { AnimatePresence, motion } from 'framer-motion'
import { X, AlertTriangle, Info, CheckCircle2, XCircle } from 'lucide-react'
import { useNotifications } from '../context/NotificationContext'

const TYPE_CONFIG = {
  danger:  {
    bg:     'bg-red-600',
    border: 'border-red-700',
    text:   'text-white',
    icon:   XCircle,
    iconCls:'text-white',
  },
  warning: {
    bg:     'bg-amber-500',
    border: 'border-amber-600',
    text:   'text-white',
    icon:   AlertTriangle,
    iconCls:'text-white',
  },
  info:    {
    bg:     'bg-blue-600',
    border: 'border-blue-700',
    text:   'text-white',
    icon:   Info,
    iconCls:'text-white',
  },
  success: {
    bg:     'bg-emerald-600',
    border: 'border-emerald-700',
    text:   'text-white',
    icon:   CheckCircle2,
    iconCls:'text-white',
  },
}

function Banner({ notification, onDismiss }) {
  const cfg   = TYPE_CONFIG[notification.type] || TYPE_CONFIG.info
  const Icon  = cfg.icon

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -12, scale: 0.97 }}
      animate={{ opacity: 1, y: 0,   scale: 1 }}
      exit={{    opacity: 0, y: -8,  scale: 0.96 }}
      transition={{ duration: 0.22, ease: [0.25, 1, 0.5, 1] }}
      className={`
        flex items-start gap-3 px-4 py-3 rounded-2xl border shadow-lg
        ${cfg.bg} ${cfg.border} ${cfg.text}
      `}
    >
      <Icon className={`w-5 h-5 flex-shrink-0 mt-0.5 ${cfg.iconCls}`} />
      <div className="flex-1 min-w-0">
        {notification.title && (
          <p className="text-sm font-bold leading-tight">{notification.title}</p>
        )}
        {notification.message && (
          <p className="text-xs leading-relaxed mt-0.5 opacity-90">{notification.message}</p>
        )}
        {notification.action_url && (
          <a
            href={notification.action_url}
            className="inline-block mt-1.5 text-xs font-bold underline underline-offset-2 opacity-90 hover:opacity-100"
          >
            Take Action →
          </a>
        )}
      </div>
      {/* Dismiss button — always shown so user can clear persistent banners */}
      <button
        onClick={() => onDismiss(notification.id)}
        className="flex-shrink-0 p-0.5 rounded-full opacity-70 hover:opacity-100 transition"
        aria-label="Dismiss notification"
      >
        <X className="w-4 h-4" />
      </button>
    </motion.div>
  )
}

export default function FlashBanner() {
  const { notifications, dismiss } = useNotifications()

  if (!notifications.length) return null

  return (
    <div className="px-4 pt-3 space-y-2" aria-live="polite" aria-atomic="false">
      <AnimatePresence mode="popLayout" initial={false}>
        {notifications.map(n => (
          <Banner key={n.id} notification={n} onDismiss={dismiss} />
        ))}
      </AnimatePresence>
    </div>
  )
}
