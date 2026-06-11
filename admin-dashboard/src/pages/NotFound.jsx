import { useNavigate } from 'react-router-dom'

export default function NotFound() {
  const navigate = useNavigate()
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center p-8">
      <p className="text-7xl font-black text-slate-700">404</p>
      <p className="text-slate-400 text-sm font-medium">
        This page does not exist.
      </p>
      <button
        onClick={() => navigate('/')}
        className="mt-2 px-4 py-2 text-xs font-semibold rounded-lg
                   bg-slate-800 hover:bg-slate-700 text-slate-300
                   border border-slate-700 transition-colors"
      >
        Back to Dashboard
      </button>
    </div>
  )
}
