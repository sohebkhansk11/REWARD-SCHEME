import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Users, Download, Upload, RefreshCw, Search,
  CheckCircle2, XCircle, AlertTriangle, ChevronUp, ChevronDown,
  Pencil, Trash2, IndianRupee,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import StatusBadge from '../components/StatusBadge'
import Modal from '../components/Modal'
import {
  getAdminUsers, importUsersCsv, downloadUsersCSV, triggerDownload,
  adminFullUpdateUser, adminDeleteUser,
} from '../api/client'
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

const ALL_STATUSES  = ['Active', 'Waitlist', 'Eliminated', 'Eliminated_Won']
const ALL_PAY_STATS = ['Paid', 'Unpaid']

// ─── Import Result Banner ─────────────────────────────────────────────────────
function ImportBanner({ result, onClose }) {
  if (!result) return null
  return (
    <div className={`rounded-xl p-4 border flex gap-3 ${
      result.errors.length > 0 ? 'bg-amber-50 border-amber-200' : 'bg-emerald-50 border-emerald-200'
    }`}>
      <div className="flex-shrink-0 mt-0.5">
        {result.errors.length > 0
          ? <AlertTriangle className="w-5 h-5 text-amber-500" />
          : <CheckCircle2 className="w-5 h-5 text-emerald-600" />}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-800">
          Import complete — {result.created_count} created, {result.skipped_count} skipped
          {result.errors.length > 0 && `, ${result.errors.length} errors`}
        </p>
        {result.errors.length > 0 && (
          <ul className="mt-2 space-y-0.5">
            {result.errors.slice(0, 5).map((e, i) => (
              <li key={i} className="text-xs text-amber-700">Row {e.row} · {e.mobile} — {e.reason}</li>
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
          : <ChevronUp className="w-3 h-3 opacity-20" />}
      </span>
    </th>
  )
}

// ─── Labelled field helper ────────────────────────────────────────────────────
function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
        {label}
      </label>
      {children}
    </div>
  )
}

const inputCls = "w-full px-3 py-2 border border-slate-200 rounded-xl text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
const selectCls = "w-full px-3 py-2 border border-slate-200 rounded-xl text-sm text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"


// ═════════════════════════════════════════════════════════════════════════════
export default function UserDirectory() {
  const toast   = useToast()
  const fileRef = useRef(null)

  // ── Data ────────────────────────────────────────────────────────────────
  const [users,        setUsers]        = useState([])
  const [loading,      setLoading]      = useState(true)
  const [refreshing,   setRefreshing]   = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  const [search,       setSearch]       = useState('')
  const [sortBy,       setSortBy]       = useState('join_date')
  const [sortDir,      setSortDir]      = useState('desc')
  const [importing,    setImporting]    = useState(false)
  const [downloading,  setDownloading]  = useState(false)
  const [importResult, setImportResult] = useState(null)

  // ── Edit modal state ────────────────────────────────────────────────────
  const [editTarget,  setEditTarget]  = useState(null)   // full user object
  const [editForm,    setEditForm]    = useState({})
  const [editLoading, setEditLoading] = useState(false)

  // ── Delete modal state ──────────────────────────────────────────────────
  const [delTarget,   setDelTarget]   = useState(null)   // full user object
  const [delConfirm,  setDelConfirm]  = useState('')
  const [delLoading,  setDelLoading]  = useState(false)

  // ── Load ─────────────────────────────────────────────────────────────────
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

  // ── Sort helper ───────────────────────────────────────────────────────────
  const handleSort = field => {
    if (sortBy === field) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(field); setSortDir('asc') }
  }

  // ── Filter + sort ─────────────────────────────────────────────────────────
  const q = search.toLowerCase().trim()
  const displayed = [...users]
    .filter(u => !q || (
      u.name?.toLowerCase().includes(q) ||
      u.username?.toLowerCase().includes(q) ||
      u.mobile?.includes(q)
    ))
    .sort((a, b) => {
      let av = a[sortBy] ?? '', bv = b[sortBy] ?? ''
      if (typeof av === 'string') av = av.toLowerCase()
      if (typeof bv === 'string') bv = bv.toLowerCase()
      return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
    })

  // ── Download CSV ──────────────────────────────────────────────────────────
  const handleDownload = async () => {
    setDownloading(true)
    try {
      const res = await downloadUsersCSV()
      triggerDownload(res.data, `users_${new Date().toISOString().slice(0, 10)}.csv`)
      toast('Users CSV downloaded', 'success')
    } catch { toast('Download failed', 'error') }
    finally { setDownloading(false) }
  }

  // ── Import CSV ────────────────────────────────────────────────────────────
  const handleFileChange = async e => {
    const file = e.target.files?.[0]
    if (!file) return
    fileRef.current.value = ''
    setImporting(true)
    setImportResult(null)
    try {
      const res = await importUsersCsv(file)
      setImportResult(res.data)
      if (res.data.created_count > 0) { toast(`${res.data.created_count} users imported`, 'success'); load(true) }
      else toast('No new users imported', 'info')
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Import failed', 'error')
    } finally {
      setImporting(false)
    }
  }

  // ─── Edit handlers ────────────────────────────────────────────────────────
  const openEdit = user => {
    setEditTarget(user)
    setEditForm({
      name:                           user.name          ?? '',
      mobile:                         user.mobile        ?? '',
      username:                       user.username      ?? '',
      new_password:                   '',
      status:                         user.status        ?? '',
      current_level:                  user.current_level ?? 1,
      weekly_payment_status:          user.weekly_payment_status ?? '',
      total_referrals_count:          user.total_referrals_count ?? 0,
      accumulated_referral_bonus_inr: user.accumulated_referral_bonus_inr ?? 0,
    })
  }

  const ef = (key, val) => setEditForm(f => ({ ...f, [key]: val }))

  const handleEditSubmit = async () => {
    setEditLoading(true)
    try {
      const payload = {}
      if (editForm.name.trim())     payload.name     = editForm.name.trim()
      if (editForm.mobile.trim())   payload.mobile   = editForm.mobile.trim()
      if (editForm.username.trim()) payload.username = editForm.username.trim()
      if (editForm.new_password.trim()) payload.new_password = editForm.new_password.trim()
      if (editForm.status)          payload.status   = editForm.status
      if (editForm.current_level)   payload.current_level = parseInt(editForm.current_level, 10)
      if (editForm.weekly_payment_status) payload.weekly_payment_status = editForm.weekly_payment_status
      payload.total_referrals_count          = parseInt(editForm.total_referrals_count, 10) || 0
      payload.accumulated_referral_bonus_inr = parseFloat(editForm.accumulated_referral_bonus_inr) || 0

      await adminFullUpdateUser(editTarget.id, payload)
      toast(`User @${editTarget.username} updated successfully`, 'success')
      setEditTarget(null)
      load(true)
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Update failed', 'error')
    } finally {
      setEditLoading(false)
    }
  }

  // ─── Delete handlers ──────────────────────────────────────────────────────
  const openDelete = user => {
    setDelTarget(user)
    setDelConfirm('')
  }

  const handleDeleteUser = async () => {
    setDelLoading(true)
    try {
      const res = await adminDeleteUser(delTarget.id)
      toast(res.data.message ?? `User deleted`, 'success')
      setDelTarget(null)
      setDelConfirm('')
      setUsers(u => u.filter(x => x.id !== delTarget.id))
    } catch (err) {
      toast(err.response?.data?.detail ?? 'Delete failed', 'error')
    } finally {
      setDelLoading(false)
    }
  }

  const statusCounts = users.reduce((acc, u) => {
    acc[u.status] = (acc[u.status] || 0) + 1
    return acc
  }, {})

  // ════════════════════════════════════════════════════════════════════════════
  return (
    <div className="p-8 space-y-6">

      {/* ── Header ────────────────────────────────────────────────────────── */}
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
          <button onClick={() => load(true)} disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition">
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={handleDownload} disabled={downloading}
            className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 shadow-sm disabled:opacity-50 transition">
            {downloading ? <Spinner className="w-4 h-4" /> : <Download className="w-4 h-4" />}
            Export CSV
          </button>
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={handleFileChange} />
          <button onClick={() => fileRef.current?.click()} disabled={importing}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium shadow-sm shadow-blue-200 disabled:opacity-60 transition">
            {importing ? <Spinner className="w-4 h-4 text-white" /> : <Upload className="w-4 h-4" />}
            {importing ? 'Importing…' : 'Bulk Import CSV'}
          </button>
        </div>
      </div>

      <ImportBanner result={importResult} onClose={() => setImportResult(null)} />

      {/* CSV hint */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-xs text-slate-500 font-mono">
        CSV format — required: <span className="text-slate-700 font-semibold">name, mobile</span>
        &nbsp; optional: <span className="text-slate-600">username, referred_by_username</span>
      </div>

      {/* ── Filters ────────────────────────────────────────────────────────── */}
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          <input type="text" placeholder="Search name, username, mobile…"
            value={search} onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white" />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="px-3 py-2 border border-slate-200 rounded-xl text-sm text-slate-700 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          {STATUS_FILTERS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
        <span className="flex items-center text-sm text-slate-400 ml-auto">{displayed.length} rows</span>
      </div>

      {/* ── Table ──────────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        {loading ? (
          <div className="flex justify-center py-16"><Spinner className="w-8 h-8" /></div>
        ) : displayed.length === 0 ? (
          <div className="py-16 text-center text-slate-400 text-sm">
            {search || statusFilter ? 'No users match your filters.' : 'No users yet.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[1000px]">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider w-10">#</th>
                  <SortTh label="Name"       field="name"           sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="Mobile"     field="mobile"         sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="Status"     field="status"         sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="Level"      field="current_level"  sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Payment</th>
                  <SortTh label="Refs"       field="total_referrals_count" sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <SortTh label="Joined"     field="join_date"      sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {displayed.map((u, i) => (
                  <tr key={u.id} className="hover:bg-slate-50/60 transition-colors group">
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
                      {u.status === 'Active'
                        ? <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-blue-100 text-blue-700 text-xs font-bold">L{u.current_level}</span>
                        : <span className="text-slate-300 text-xs">—</span>}
                    </td>

                    {/* Payment */}
                    <td className="px-4 py-3"><StatusBadge status={u.weekly_payment_status} /></td>

                    {/* Referral count + bonus */}
                    <td className="px-4 py-3">
                      {(u.total_referrals_count > 0 || parseFloat(u.accumulated_referral_bonus_inr) > 0) ? (
                        <div>
                          <p className="text-xs font-semibold text-slate-700">{u.total_referrals_count} refs</p>
                          {parseFloat(u.accumulated_referral_bonus_inr) > 0 && (
                            <p className="text-[10px] text-emerald-600 font-semibold">
                              {INR(u.accumulated_referral_bonus_inr)} pending
                            </p>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-300 text-xs">—</span>
                      )}
                    </td>

                    {/* Joined */}
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{fmtDate(u.join_date)}</td>

                    {/* Actions */}
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        {/* Edit */}
                        <button
                          onClick={() => openEdit(u)}
                          className="flex items-center gap-1 px-2.5 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-600 rounded-lg text-xs font-semibold transition-colors"
                          title="Edit user"
                        >
                          <Pencil className="w-3 h-3" />
                          Edit
                        </button>

                        {/* Delete */}
                        <button
                          onClick={() => openDelete(u)}
                          className="flex items-center gap-1 px-2.5 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 rounded-lg text-xs font-semibold transition-colors"
                          title="Delete user"
                        >
                          <Trash2 className="w-3 h-3" />
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          EDIT USER MODAL
      ══════════════════════════════════════════════════════════════════════ */}
      <Modal
        open={!!editTarget}
        onClose={() => !editLoading && setEditTarget(null)}
        title={editTarget ? `Edit User — @${editTarget.username}` : ''}
        maxWidth="max-w-2xl"
      >
        {editTarget && (
          <div className="space-y-5">
            {/* Row 1: Name + Mobile */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Full Name">
                <input className={inputCls} value={editForm.name}
                  onChange={e => ef('name', e.target.value)} placeholder="Full name" />
              </Field>
              <Field label="Mobile">
                <input className={inputCls} value={editForm.mobile}
                  onChange={e => ef('mobile', e.target.value)} placeholder="+91…" />
              </Field>
            </div>

            {/* Row 2: Username + New Password */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Username">
                <input className={inputCls} value={editForm.username}
                  onChange={e => ef('username', e.target.value)} placeholder="username" />
              </Field>
              <Field label="New Password">
                <input className={inputCls} type="password" value={editForm.new_password}
                  onChange={e => ef('new_password', e.target.value)}
                  placeholder="Leave blank to keep current" />
              </Field>
            </div>

            {/* Row 3: Status + Level */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Status">
                <select className={selectCls} value={editForm.status}
                  onChange={e => ef('status', e.target.value)}>
                  <option value="">— unchanged —</option>
                  {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
              <Field label="Level (1–6)">
                <input className={inputCls} type="number" min={1} max={6}
                  value={editForm.current_level}
                  onChange={e => ef('current_level', Math.min(6, Math.max(1, parseInt(e.target.value) || 1)))} />
              </Field>
            </div>

            {/* Row 4: Payment status */}
            <Field label="Weekly Payment Status">
              <select className={selectCls} value={editForm.weekly_payment_status}
                onChange={e => ef('weekly_payment_status', e.target.value)}>
                <option value="">— unchanged —</option>
                {ALL_PAY_STATS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>

            {/* Row 5: Referral correction */}
            <div className="border-t border-slate-100 pt-4">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                <IndianRupee className="w-3.5 h-3.5" />
                Referral Balance (Admin Correction)
              </p>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Total Referrals Count">
                  <input className={inputCls} type="number" min={0}
                    value={editForm.total_referrals_count}
                    onChange={e => ef('total_referrals_count', Math.max(0, parseInt(e.target.value) || 0))} />
                </Field>
                <Field label="Accumulated Bonus (₹)">
                  <input className={inputCls} type="number" min={0} step="0.01"
                    value={editForm.accumulated_referral_bonus_inr}
                    onChange={e => ef('accumulated_referral_bonus_inr', Math.max(0, parseFloat(e.target.value) || 0))} />
                </Field>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3 pt-2 border-t border-slate-100">
              <button
                onClick={() => setEditTarget(null)}
                disabled={editLoading}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleEditSubmit}
                disabled={editLoading}
                className="flex items-center gap-2 px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-semibold shadow-sm shadow-blue-200 disabled:opacity-60 transition-colors"
              >
                {editLoading ? <><Spinner className="w-4 h-4 text-white" />Saving…</> : 'Save Changes'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* ══════════════════════════════════════════════════════════════════════
          DELETE USER MODAL
      ══════════════════════════════════════════════════════════════════════ */}
      <Modal
        open={!!delTarget}
        onClose={() => !delLoading && (setDelTarget(null), setDelConfirm(''))}
        title="Delete User"
        maxWidth="max-w-md"
      >
        {delTarget && (
          <div className="space-y-5">
            {/* Warning block */}
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4">
              <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-red-800 text-sm">This action cannot be undone</p>
                <p className="text-xs text-red-600 mt-1 leading-relaxed">
                  Permanently deletes user <span className="font-bold">@{delTarget.username}</span>,
                  all their tokens, and removes them from any active pool.
                  Their referral history will be disconnected.
                </p>
              </div>
            </div>

            {/* User summary */}
            <div className="bg-slate-50 rounded-xl p-4 space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">Name</span>
                <span className="font-semibold text-slate-800">{delTarget.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Username</span>
                <span className="font-mono text-slate-700">@{delTarget.username}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Status</span>
                <StatusBadge status={delTarget.status} />
              </div>
              {delTarget.current_pool_id && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Pool</span>
                  <span className="text-amber-600 font-semibold text-xs">Active in Pool #{delTarget.current_pool_id}</span>
                </div>
              )}
            </div>

            {/* Typed confirmation */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1.5">
                Type <span className="text-red-600 font-mono">DELETE</span> to confirm
              </label>
              <input
                className={`${inputCls} font-mono ${delConfirm === 'DELETE' ? 'border-red-500 ring-2 ring-red-300' : ''}`}
                value={delConfirm}
                onChange={e => setDelConfirm(e.target.value)}
                placeholder="DELETE"
                autoComplete="off"
                spellCheck={false}
              />
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={() => { setDelTarget(null); setDelConfirm('') }}
                disabled={delLoading}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteUser}
                disabled={delConfirm !== 'DELETE' || delLoading}
                className="flex items-center gap-2 px-5 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {delLoading
                  ? <><Spinner className="w-4 h-4 text-white" />Deleting…</>
                  : <><Trash2 className="w-4 h-4" />Delete User</>}
              </button>
            </div>
          </div>
        )}
      </Modal>

    </div>
  )
}
