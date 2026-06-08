import { useState, useEffect } from 'react'
import { Copy, Check, Flame, Plus, Clock, AlertCircle } from 'lucide-react'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import { generateToken, burnToken, getTokens } from '../api/client'
import { useToast } from '../context/ToastContext'

const INR = v =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)

function CodeDisplay({ code }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="relative mt-4">
      <div className="bg-slate-900 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
        <span className="font-mono text-emerald-400 text-lg tracking-[0.25em] select-all">{code}</span>
        <button
          onClick={copy}
          className="flex-shrink-0 flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition"
        >
          {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="mt-2 text-xs text-slate-400 text-center">
        Hand this code to the user for redemption
      </div>
    </div>
  )
}

export default function TokenManager() {
  const toast = useToast()

  // Generate panel
  const [genAmount, setGenAmount] = useState('1000')
  const [genLoading, setGenLoading] = useState(false)
  const [lastCode, setLastCode] = useState(null)

  // Burn panel
  const [burnCode, setBurnCode] = useState('')
  const [burnLoading, setBurnLoading] = useState(false)
  const [burnResult, setBurnResult] = useState(null)

  // Recent tokens
  const [tokens, setTokens] = useState([])
  const [tokensLoading, setTokensLoading] = useState(true)

  const loadTokens = async () => {
    try {
      const res = await getTokens({ limit: 20 })
      setTokens(res.data.slice().reverse())
    } catch { /* ignore */ }
    finally { setTokensLoading(false) }
  }

  useEffect(() => { loadTokens() }, [])

  const handleGenerate = async e => {
    e.preventDefault()
    const amount = parseFloat(genAmount)
    if (!amount || amount <= 0) { toast('Enter a valid amount', 'warning'); return }
    setGenLoading(true)
    setLastCode(null)
    try {
      const res = await generateToken('Deposit', amount)
      setLastCode(res.data.code)
      toast(`Token ${res.data.code} generated`, 'success')
      loadTokens()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Generation failed', 'error')
    } finally {
      setGenLoading(false)
    }
  }

  const handleBurn = async e => {
    e.preventDefault()
    const code = burnCode.trim().toUpperCase()
    if (!code) { toast('Enter a token code', 'warning'); return }
    setBurnLoading(true)
    setBurnResult(null)
    try {
      const res = await burnToken(code)
      setBurnResult(res.data)
      toast(`Token ${code} settled — ₹${res.data.value_inr} paid out`, 'success')
      setBurnCode('')
      loadTokens()
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Burn failed', 'error')
    } finally {
      setBurnLoading(false)
    }
  }

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Token Manager</h1>
        <p className="text-sm text-slate-400 mt-0.5">Issue deposit tokens and settle winning withdrawals</p>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* ── Issue Deposit Token ─────────────────────────────── */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-3">
            <div className="bg-blue-50 p-2 rounded-lg">
              <Plus className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <h2 className="font-semibold text-slate-800">Issue Deposit Token</h2>
              <p className="text-xs text-slate-400">Creates a one-time redemption code for a user</p>
            </div>
          </div>
          <form onSubmit={handleGenerate} className="p-6 space-y-5">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Face Value (₹)
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 font-semibold">₹</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={genAmount}
                  onChange={e => setGenAmount(e.target.value)}
                  className="w-full pl-7 pr-4 py-2.5 border border-slate-200 rounded-xl text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  placeholder="1000"
                />
              </div>
              <p className="mt-1.5 text-xs text-slate-400">Standard deposit is ₹1,000</p>
            </div>

            <button
              type="submit"
              disabled={genLoading}
              className="w-full flex items-center justify-center gap-2 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold text-sm shadow-sm shadow-blue-200 disabled:opacity-60 transition"
            >
              {genLoading ? <Spinner className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
              Generate Token
            </button>

            {lastCode && <CodeDisplay code={lastCode} />}
          </form>
        </div>

        {/* ── Settle Withdraw Token ───────────────────────────── */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-3">
            <div className="bg-red-50 p-2 rounded-lg">
              <Flame className="w-4 h-4 text-red-500" />
            </div>
            <div>
              <h2 className="font-semibold text-slate-800">Settle Withdraw Token</h2>
              <p className="text-xs text-slate-400">Burn a winner's payout token after cash settlement</p>
            </div>
          </div>
          <form onSubmit={handleBurn} className="p-6 space-y-5">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Token Code
              </label>
              <input
                type="text"
                value={burnCode}
                onChange={e => setBurnCode(e.target.value.toUpperCase())}
                className="w-full px-4 py-2.5 border border-slate-200 rounded-xl font-mono text-sm tracking-widest text-slate-900 placeholder:text-slate-300 placeholder:font-sans placeholder:tracking-normal focus:outline-none focus:ring-2 focus:ring-red-400 uppercase"
                placeholder="WIT-XXXXXX"
              />
              <p className="mt-1.5 text-xs text-slate-400">
                Enter the WIT-XXXXXX code from the winner's payout slip
              </p>
            </div>

            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl p-3">
              <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-amber-700">
                Burning a token is <strong>irreversible</strong>. Only proceed after physically paying the winner.
              </p>
            </div>

            <button
              type="submit"
              disabled={burnLoading}
              className="w-full flex items-center justify-center gap-2 py-3 bg-red-500 hover:bg-red-600 text-white rounded-xl font-semibold text-sm shadow-sm shadow-red-200 disabled:opacity-60 transition"
            >
              {burnLoading ? <Spinner className="w-4 h-4" /> : <Flame className="w-4 h-4" />}
              Settle & Burn Token
            </button>

            {burnResult && (
              <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 space-y-1.5">
                <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">Settlement Confirmed</p>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Code</span>
                  <span className="font-mono font-semibold text-slate-800">{burnResult.code}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Amount Paid</span>
                  <span className="font-semibold text-emerald-700">{INR(burnResult.value_inr)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500">Status</span>
                  <StatusBadge status={burnResult.status} />
                </div>
              </div>
            )}
          </form>
        </div>
      </div>

      {/* Recent Tokens */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
          <Clock className="w-4 h-4 text-slate-400" />
          <h2 className="font-semibold text-slate-800">Recent Tokens</h2>
          <span className="ml-auto text-xs text-slate-400">Latest 20</span>
        </div>
        {tokensLoading ? (
          <div className="flex justify-center py-10"><Spinner /></div>
        ) : tokens.length === 0 ? (
          <div className="py-12 text-center text-slate-400 text-sm">No tokens yet</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100">
                {['Code', 'Type', 'Value', 'User ID', 'Status'].map(h => (
                  <th key={h} className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tokens.map((t, i) => (
                <tr key={t.id} className={`border-b border-slate-50 ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50/40'}`}>
                  <td className="px-6 py-3 font-mono font-semibold text-slate-800 tracking-widest">{t.code}</td>
                  <td className="px-6 py-3">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      t.type === 'Deposit' ? 'bg-blue-100 text-blue-700' :
                      t.type === 'Withdraw' ? 'bg-violet-100 text-violet-700' :
                      'bg-slate-100 text-slate-600'
                    }`}>{t.type}</span>
                  </td>
                  <td className="px-6 py-3 font-semibold text-slate-700">{INR(t.value_inr)}</td>
                  <td className="px-6 py-3 text-slate-500">{t.user_id ?? '—'}</td>
                  <td className="px-6 py-3"><StatusBadge status={t.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
