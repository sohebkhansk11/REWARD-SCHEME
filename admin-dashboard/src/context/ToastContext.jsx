import { createContext, useContext, useState, useCallback } from 'react'
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from 'lucide-react'

const ToastCtx = createContext(null)

const CONFIG = {
  success: { icon: CheckCircle2, bar: 'bg-emerald-500', text: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
  error:   { icon: XCircle,      bar: 'bg-red-500',     text: 'text-red-700',     bg: 'bg-red-50   border-red-200'   },
  warning: { icon: AlertTriangle, bar: 'bg-amber-500',  text: 'text-amber-700',   bg: 'bg-amber-50 border-amber-200' },
  info:    { icon: Info,          bar: 'bg-blue-500',   text: 'text-blue-700',    bg: 'bg-blue-50  border-blue-200'  },
}

function Toast({ toast, onClose }) {
  const c = CONFIG[toast.type] ?? CONFIG.info
  const Icon = c.icon
  return (
    <div className={`relative flex items-start gap-3 rounded-xl border shadow-lg p-4 pr-10 w-80 overflow-hidden ${c.bg}`}>
      <div className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-xl ${c.bar}`} />
      <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${c.text}`} />
      <p className="text-sm text-slate-700 leading-snug">{toast.message}</p>
      <button onClick={() => onClose(toast.id)} className="absolute top-3 right-3 text-slate-400 hover:text-slate-600">
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const addToast = useCallback((message, type = 'info') => {
    const id = Date.now() + Math.random()
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4500)
  }, [])

  const remove = useCallback(id => setToasts(t => t.filter(x => x.id !== id)), [])

  return (
    <ToastCtx.Provider value={addToast}>
      {children}
      <div className="fixed bottom-5 right-5 flex flex-col gap-2 z-50">
        {toasts.map(t => <Toast key={t.id} toast={t} onClose={remove} />)}
      </div>
    </ToastCtx.Provider>
  )
}

export const useToast = () => useContext(ToastCtx)
