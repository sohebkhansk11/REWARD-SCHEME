/**
 * Modal.jsx — Reusable overlay modal
 *
 * Usage:
 *   <Modal open={show} onClose={() => setShow(false)} title="Edit User">
 *     ...content...
 *   </Modal>
 *
 * Props:
 *   open      bool     — controls visibility
 *   onClose   fn       — called on backdrop click or Escape key
 *   title     string   — header text
 *   maxWidth  string   — Tailwind max-w-* class (default "max-w-lg")
 *   children  ReactNode
 */

import { useEffect } from 'react'
import { X } from 'lucide-react'

export default function Modal({ open, onClose, title, maxWidth = 'max-w-lg', children }) {
  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className={`relative z-10 bg-white rounded-2xl shadow-2xl w-full ${maxWidth} flex flex-col`}
        style={{ maxHeight: '90vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 flex-shrink-0">
          <h2 className="font-bold text-slate-800 text-base leading-tight">{title}</h2>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition-colors rounded-lg p-1 hover:bg-slate-100 flex-shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 p-6">
          {children}
        </div>
      </div>
    </div>
  )
}
