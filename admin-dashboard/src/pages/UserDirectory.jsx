import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Users, Download, Upload, RefreshCw, Search,
  CheckCircle2, XCircle, AlertTriangle, ChevronUp, ChevronDown,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import { getAdminUsers, importUsersCsv, downloadUsersCSV, triggerDownload } from '../api/client'
import { useToast } from '../context/ToastContext'

const INR = v =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

const STATUS_FILTERS = [
  { label: 'All Users',    value: '' },
  { label: 'Active',       value: 'Active' },
  { label: 'Waitlist',     value: 'Waitlist' },
  { label: 'Winners',      value: 'Eliminated_Won' },
  { label: 'Eliminated',   value: 'Eliminated' },
]

// ─── Import Result Banner ─────────────────────────────────────────────────────
function ImportBanner({ result, onClose }) {
  if (!result) return null
  return (
    <div className={`rounded-xl p-4 border flex gap-3 ${
      result.errors.length > 0
        ? 'bg-amber-50 border-amber-200'
        : 'bg-emerald-50 border-emerald-200'
    }`}>
      <div className="flex-shrink-0 mt-0.5">
        {result.errors.length > 0
          ? <AlertTriangle className="w-5 h-5 text-amber-500" />
          : <CheckCircle2 className="w-5 h-5 text-emerald-600" />
        }
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-800">
          Import complete — {result.created_count} created, {result.skipped_count} skipped
          {result.errors.length > 0 && `, ${result.errors.length} errors`}
        </p>
        {result.errors.length > 0 && (
          <ul className="mt-2 space-y-0.5">
            {result.errors.slice(0, 5).map((e, i) => (
              <li key={i} className="text-xs text-amber-700">
                Row {e.row} · {e.mobile} — {e.reason}
              </li>
            ))}
            {result.errors.length > 5 && (
              <li className="text-xs text-amber-600">…and {result.errors.length - 5} more</li>
            )}
          </ul>
        )}
      </div>
      <button onClick={onClose} className="text-slate-400 hover:text-slate-700 flex-shrink-0">
        <XCircle className="w-4 h-4" />
      </button>
    </div>
  )
}

// ─── Sortable column header ───────────────────────────────────────────────────
function SortTh({ label, field, sortBy, sortDir, onSort }) {
  const active = sortBy === field
  return (
    <th
      className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider cursor-pointer select-none hover:text-slate-600 transition-colors"
      onClick={() => onSort(field)}
    >
      <span className="flex items-center gap-1">
        {label}
        {active
          ? sortDir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
          : <ChevronUp className="w-3 h-3 opacity-20" />
        }
      </span>
    </th>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
export default function UserDirectory() {
  const toast      = useToast()
  const fileRef    = useRef(null)

  const [users,          setUsers]          = useState([])
  const [loading,        setLoading]        = useState(true)
  const [refreshing,     setRefreshing]     = useState(false)
  const [statusFilter,   setStatusFilter]   = useState('')
  const [search,         setSearch]         = useState('')
  const [sortBy,         setSortBy]         = useState('join_date')
  const [sortDir,        setSortDir]        = useState('desc')
  const [importing,      setImporting]      = useState(false)
  const [downloading,    setDownloading]    = useState(false)
  const [importResult,   setImportResult]   = useState(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    try {
      const params = {}
      if (statusFilter) params.status = statusFilter
      const res = await getAdminUsers(params)
      setUsers(res.data)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Failed to load users', 'error')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [statusFilter])

  useEffect(() => { load() }, [load])

  // ── Sort ────────────────────────────────────────────────────────────────
  const handleSort = (field) => {
    if (sortBy === field) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(field); setSortDir('asc') }
  }

  // ── Filter + sort rows ──────────────────────────────────────────────────
  const q = search.toLowerCase().trim()
  const displayed = [...users]
    .filter(u => !q || (
      u.name?.toLowerCase().includes(q)    ||
      u.username?.toLowerCase().includes(q) ||
      u.mobile?.includes(q)
    ))
    .sort((a, b) => {
      let av = a[sortBy], bv = b[sortBy]
      if (av == null) av = ''
      if (bv == null) bv = ''
      if (typeof av === 'string') av = av.toLowerCase()
      if (typeof bv === 'string') bv = bv.toLowerCase()
      return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
    })

  // ── Download ─────────────────────────────────────────────────────────────
  const handleDownload = async () => {
    setDownloading(true)
    try {
      const res = await downloadUsersCSV()
      triggerDownload(res.data, `users_${new Date().toISOString().slice(0,10)}.csv`)
      toast('Users CSV downloaded', 'success')
    } catch {
      toast('Download failed', 'error')
    } finally {
      setDownloading(false)
    }
  }

  // ── Import ────────────────────────────────────────────────────────────────
  const handleFileChange = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    fileRef.current.value = ''   // reset so same file can be re-uploaded
    setImporting(true)
    setImportResult(null)
    try {
      const res = await importUsersCsv(file)
      setImportResult(res.data)
      if (res.data.created_count > 0) {
        toast(`${res.data.created_count} users imported`, 'success')
        load(true)
      } else {
        toast('No new users imported', 'info')
      }
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Import failed', 'error')
    } finally {
      setImporting(false)
    }
  }

  // ── Status dot ────────────────────────────────────────────────────────────
  const statusCounts = users.reduce((acc, u) => {
    acc[u.status] = (acc[u.status] || 0) + 1
    return acc
  }, {})

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Users className="w-6 h-6 text-blue-600" />
            User Directory
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {users.length} total · {statusCounts.Active ?? 0} active · {statusCounts.Waitlist ?? 0} waiting
          </p>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Refresh */}
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>

          {/* Download CSV */}
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition"
          >
            {downloading ? <Spinner className="w-4 h-4" /> : <Download className="w-4 h-4" />}
            Export CSV
          </button>

          {/* Bulk Import */}
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleFileChange}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={importing}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium shadow-sm shadow-blue-200 disabled:opacity-60 transition"
          >
            {importing ? <Spinner className="w-4 h-4" /> : <Upload className="w-4 h-4" />}
            {importing ? 'Importing…' : 'Bulk Import CSV'}
          </button>
        </div>
      </div>

      {/* Import banner */}
      <ImportBanner result={importResult} onClose={() => setImportResult(null)} />

      {/* CSV format hint */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-xs text-slate-500 font-mono">
        CSV format — required: <span className="text-slate-700 font-semibold">name, mobile</span>
        &nbsp; optional: <span className="text-slate-600">username, referred_by_username</span>
      </div>

      {/* Filter bar */}
      <div className="flex gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Search name, username, mobile…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
          />
        </div>

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="px-3 py-2 border border-slate-200 rounded-xl text-sm text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {STATUS_FILTERS.map(f => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>

        <span className="flex items-center text-sm text-slate-400 ml-auto">
          {displayed.length} rows
        </span>
      </div>

      {/* Table */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-16"><Spinner className="w-8 h-8" /></div>
        ) : displayed.length === 0 ? (
          <div className="py-16 text-center text-slate-400 text-sm">
            {search || statusFilter ? 'No users match your filters.' : 'No users yet.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[860px]">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider w-10">#</th>
                  <SortTh label="Name"       field="name"       sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="Mobile"     field="mobile"     sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="Status"     field="status"     sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="Level"      field="current_level" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Payment</th>
                  <SortTh label="Joined"     field="join_date"       sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="First Paid" field="first_payment_at" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {displayed.map((u, i) => (
                  <tr key={u.id} className="hover:bg-slate-50/60 transition-colors">
                    <td className="px-4 py-3 text-xs text-slate-400 tabular-nums">{i + 1}</td>

                    {/* Name + username */}
                    <td className="px-4 py-3">
                      <p className="font-semibold text-slate-800 text-sm">{u.name}</p>
                      <p className="text-xs text-slate-400 font-mono">@{u.username}</p>
                    </td>

                    {/* Mobile */}
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">{u.mobile}</td>

                    {/* Status */}
                    <td className="px-4 py-3"><StatusBadge status={u.status} /></td>

                    {/* Level */}
                    <td className="px-4 py-3">
                      {u.status === 'Active' ? (
                        <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-blue-100 text-blue-700 text-xs font-bold">
                          L{u.current_level}
                        </span>
                      ) : (
                        <span className="text-slate-300 text-xs">—</span>
                      )}
                    </td>

                    {/* Payment */}
                    <td className="px-4 py-3">
                      <StatusBadge status={u.weekly_payment_status} />
                    </td>

                    {/* Joined */}
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{fmtDate(u.join_date)}</td>

                    {/* First paid */}
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                      {u.first_payment_at
                        ? <span className="text-emerald-600">{fmtDate(u.first_payment_at)}</span>
                        : <span className="text-slate-300">Not paid</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
