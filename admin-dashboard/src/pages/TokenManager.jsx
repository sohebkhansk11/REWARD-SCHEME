import { useState, useEffect, useCallback } from 'react'
import { Copy, Check, Flame, Plus, Clock, AlertCircle, Download, RefreshCw, Filter, Trash2, KeyRound } from 'lucide-react'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import Modal from '../components/Modal'
import { generateToken, burnToken, getAdminTokens, downloadTokensCSV, triggerDownload, adminDeleteToken } from '../api/client'
import { useToast } from '../context/ToastContext'

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

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

  // Token audit ledger
  const [tokens,          setTokens]          = useState([])
  const [tokensLoading,   setTokensLoading]   = useState(true)
  const [tokensRefreshing,setTokensRefreshing]= useState(false)
  const [typeFilter,      setTypeFilter]      = useState('')
  const [statusFilter,    setStatusFilter]    = useState('')
  const [downloading,     setDownloading]     = useState(false)

  // Delete token modal
  const [delToken,     setDelToken]     = useState(null)   // token object
  const [delAdminPw,   setDelAdminPw]   = useState('')
  const [delLoading,   setDelLoading]   = useState(false)
  const [pwVisible,    setPwVisible]    = useState(false)

  const loadTokens = useCallback(async (silent = false) => {
    if (!silent) setTokensLoading(true)
    else setTokensRefreshing(true)
    try {
      const params = {}
      if (typeFilter)   params.type   = typeFilter
      if (statusFilter) params.status = statusFilter
      const res = await getAdminTokens(params)
      setTokens(res.data)
    } catch { /* ignore */ }
    finally { setTokensLoading(false); setTokensRefreshing(false) }
  }, [typeFilter, statusFilter])

  useEffect(() => { loadTokens() }, [loadTokens])

  // Auto-refresh every 60 s
  useEffect(() => {
    const id = setInterval(() => loadTokens(true), 60_000)
    return () => clearInterval(id)
  }, [loadTokens])

  const handleDownloadTokens = async () => {
    setDownloading(true)
    try {
      const res = await downloadTokensCSV()
      triggerDownload(res.data, `tokens_${new Date().toISOString().slice(0, 10)}.csv`)
      toast('Tokens CSV downloaded', 'success')
    } catch { toast('Download failed', 'error') }
    finally { setDownloading(false) }
  }

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

  // ── Delete token handler ───────────────────────────────────────────────────
  const openDeleteToken = token => {
    setDelToken(token)
    setDelAdminPw('')
    setPwVisible(false)
  }

  const handleDeleteToken = async () => {
    if (!delAdminPw.trim()) { toast('Enter your admin password', 'warning'); return }
    setDelLoading(true)
    try {
      await adminDeleteToken(delToken.id, delAdminPw.trim())
      toast(`Token ${delToken.code} permanently deleted`, 'success')
      setTokens(t => t.filter(x => x.id !== delToken.id))
      setDelToken(null)
      setDelAdminPw('')
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Delete failed', 'error')
    } finally {
      setDelLoading(false)
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

      {/* ── Token Audit Ledger ───────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100">
        {/* Ledger header */}
        <div className="px-6 py-4 border-b border-slate-100 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 mr-auto">
            <Clock className="w-4 h-4 text-slate-400" />
            <h2 className="font-semibold text-slate-800">Token Audit Ledger</h2>
            <span className="text-xs text-slate-400">{tokens.length} tokens</span>
          </div>

          {/* Type filter — chip buttons */}
          <div className="flex items-center gap-1 flex-wrap">
            {[
              { value: '',                   label: 'All'     },
              { value: 'Deposit',            label: 'DEP'     },
              { value: 'Withdraw',           label: 'WIT'     },
              { value: 'Referral',           label: 'REF'     },
              { value: 'Referral_Withdraw',  label: 'REF-WIT' },
            ].map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setTypeFilter(value)}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors ${
                  typeFilter === value
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-xs text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Statuses</option>
            <option value="Active">Active</option>
            <option value="Burned">Burned</option>
            <option value="Rejected">Rejected</option>
            <option value="Pending_Approval">Pending Approval</option>
          </select>

          {/* Refresh */}
          <button
            onClick={() => loadTokens(true)}
            disabled={tokensRefreshing}
            className="p-1.5 border border-slate-200 rounded-lg text-slate-500 hover:bg-slate-50 disabled:opacity-50 transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${tokensRefreshing ? 'animate-spin' : ''}`} />
          </button>

          {/* Download */}
          <button
            onClick={handleDownloadTokens}
            disabled={downloading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 transition"
          >
            {downloading ? <Spinner className="w-3.5 h-3.5" /> : <Download className="w-3.5 h-3.5" />}
            Export CSV
          </button>
        </div>

        {/* Ledger table */}
        {tokensLoading ? (
          <div className="flex justify-center py-10"><Spinner /></div>
        ) : tokens.length === 0 ? (
          <div className="py-12 text-center text-slate-400 text-sm">No tokens match the current filters.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[920px]">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  {['Code', 'Type', 'Value', 'Status', 'Owner', 'Redeemed By', 'Created', 'Redeemed At', ''].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {tokens.map(t => (
                  <tr key={t.id} className={`transition-colors group hover:brightness-95 ${
                    t.status === 'Burned'           ? 'bg-emerald-50/40' :
                    t.status === 'Active'           ? 'bg-blue-50/30'    :
                    t.status === 'Rejected'         ? 'bg-red-50/30'     :
                    t.status === 'Pending_Approval' ? 'bg-amber-50/30'   :
                    'hover:bg-slate-50/60'
                  }`}>
                    {/* Code */}
                    <td className="px-4 py-3 font-mono font-semibold text-slate-800 tracking-widest text-xs">
                      {t.code}
                    </td>

                    {/* Type badge */}
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                        t.type === 'Deposit'  ? 'bg-blue-100 text-blue-700' :
                        t.type === 'Withdraw' ? 'bg-violet-100 text-violet-700' :
                        'bg-teal-100 text-teal-700'
                      }`}>
                        {t.type}
                      </span>
                    </td>

                    {/* Value */}
                    <td className="px-4 py-3 font-semibold text-slate-700 tabular-nums">
                      {INR(t.value_inr)}
                    </td>

                    {/* Status */}
                    <td className="px-4 py-3"><StatusBadge status={t.status} /></td>

                    {/* Owner (assigned to) */}
                    <td className="px-4 py-3">
                      {t.user_username ? (
                        <div>
                          <p className="font-medium text-slate-700 text-xs">@{t.user_username}</p>
                          <p className="text-slate-400 text-[10px]">{t.user_name}</p>
                        </div>
                      ) : <span className="text-slate-300 text-xs">Unassigned</span>}
                    </td>

                    {/* Redeemed by */}
                    <td className="px-4 py-3">
                      {t.redeemed_by_username ? (
                        <span className="text-xs font-mono text-emerald-700">@{t.redeemed_by_username}</span>
                      ) : (
                        <span className="text-slate-300 text-xs">
                          {t.status === 'Burned' ? 'Admin' : '—'}
                        </span>
                      )}
                    </td>

                    {/* Created at */}
                    <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">
                      {fmtDate(t.created_at)}
                    </td>

                    {/* Redeemed at */}
                    <td className="px-4 py-3 text-xs whitespace-nowrap">
                      {t.redeemed_at
                        ? <span className="text-slate-600">{fmtDate(t.redeemed_at)}</span>
                        : <span className="text-slate-300">Pending</span>
                      }
                    </td>

                    {/* Delete action */}
                    <td className="px-4 py-3">
                      <button
                        onClick={() => openDeleteToken(t)}
                        className="opacity-0 group-hover:opacity-100 flex items-center gap-1 px-2 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-lg text-xs font-semibold transition-all"
                        title="Delete token"
                      >
                        <Trash2 className="w-3 h-3" />
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          DELETE TOKEN MODAL  (requires admin password)
      ══════════════════════════════════════════════════════════════════════ */}
      <Modal
        open={!!delToken}
        onClose={() => !delLoading && (setDelToken(null), setDelAdminPw(''))}
        title="Delete Token"
        maxWidth="max-w-md"
      >
        {delToken && (
          <div className="space-y-5">
            {/* Warning */}
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4">
              <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-red-800 text-sm">Permanent deletion — cannot be undone</p>
                <p className="text-xs text-red-600 mt-1">
                  This token will be removed from the database entirely. Your admin password
                  is required as a second-factor safety gate.
                </p>
              </div>
            </div>

            {/* Token summary */}
            <div className="bg-slate-50 rounded-xl p-4 space-y-2 text-sm">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Token Code</span>
                <span className="font-mono font-bold text-slate-800 tracking-widest">{delToken.code}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Type</span>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                  delToken.type === 'Deposit'  ? 'bg-blue-100 text-blue-700' :
                  delToken.type === 'Withdraw' ? 'bg-violet-100 text-violet-700' :
                  'bg-teal-100 text-teal-700'
                }`}>{delToken.type}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Value</span>
                <span className="font-bold text-slate-800">{INR(delToken.value_inr)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Status</span>
                <StatusBadge status={delToken.status} />
              </div>
              {delToken.user_username && (
                <div className="flex justify-between items-center">
                  <span className="text-slate-500">Owner</span>
                  <span className="text-xs font-mono text-slate-700">@{delToken.user_username}</span>
                </div>
              )}
            </div>

            {/* Admin password */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5" />
                Admin Password
              </label>
              <div className="relative">
                <input
                  type={pwVisible ? 'text' : 'password'}
                  value={delAdminPw}
                  onChange={e => setDelAdminPw(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleDeleteToken()}
                  placeholder="Your admin account password"
                  autoComplete="current-password"
                  className="w-full px-3 py-2 pr-20 border border-slate-200 rounded-xl text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-red-400 bg-white"
                />
                <button
                  type="button"
                  onClick={() => setPwVisible(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-600"
                >
                  {pwVisible ? 'Hide' : 'Show'}
                </button>
              </div>
              <p className="mt-1.5 text-xs text-slate-400">
                Verified against your stored bcrypt hash before deletion proceeds.
              </p>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 pt-1">
              <button
                onClick={() => { setDelToken(null); setDelAdminPw('') }}
                disabled={delLoading}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteToken}
                disabled={!delAdminPw.trim() || delLoading}
                className="flex items-center gap-2 px-5 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {delLoading
                  ? <><Spinner className="w-4 h-4 text-white" />Deleting…</>
                  : <><Trash2 className="w-4 h-4" />Delete Token</>}
              </button>
            </div>
          </div>
        )}
      </Modal>

    </div>
  )
}
