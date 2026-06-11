/**
 * HydraulicPipeline.jsx — Live Flow Visualizer (Module 6)
 *
 * 3-Chamber Kanban board representing the mathematical pipeline:
 *   Column 1 — Layer 3 (Master Overflow / Waitlist)
 *              Virtualized list — renders only visible 20 items even
 *              with 1000+ members. Toggle to paginated table view.
 *   Column 2 — Layer 2 (Shared Active Reserve / Buffer)
 *              Glowing capacity indicator + AI multiplier.
 *   Column 3 — Layer 1 (Execution Engines / Active Pools)
 *              Mini pool cards with vacancy pulsing.
 *
 * Entity Search: dim everything, draw glowing path to found member.
 * Hover tooltip: exact member status + queue time estimate.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  Search, RefreshCw, AlertTriangle, Users, Layers,
  Clock, Zap, ToggleLeft, ToggleRight, ChevronLeft, ChevronRight,
  Activity, Shield, X, Info,
} from 'lucide-react'
import Spinner from '../components/Spinner'
import { getAdminUsers, getPools, getAiSnapshot } from '../api/client'
import { useToast } from '../context/ToastContext'

// ─── Constants ────────────────────────────────────────────────────────────────
const ITEM_H     = 46    // px per virtual list row
const PAGE_SIZE  = 50    // rows per paginated page

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fP = v => parseFloat(v ?? 0)
const fI = v => parseInt(v ?? 0, 10)

function timeAgo(iso) {
  if (!iso) return '—'
  const d = (Date.now() - new Date(iso).getTime()) / 1000
  if (d < 60)   return `${Math.floor(d)}s ago`
  if (d < 3600) return `${Math.floor(d/60)}m ago`
  if (d < 86400) return `${Math.floor(d/3600)}h ${Math.floor((d%3600)/60)}m ago`
  return `${Math.floor(d/86400)}d ago`
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })
}

// ─────────────────────────────────────────────────────────────────────────────
// VIRTUALIZED LIST — renders only ~22 rows regardless of total count
// ─────────────────────────────────────────────────────────────────────────────
function VirtualizedList({ items, renderItem, containerH = 480 }) {
  const [scrollTop, setScrollTop] = useState(0)
  const ref = useRef(null)

  const visStart  = Math.floor(scrollTop / ITEM_H)
  const visCount  = Math.ceil(containerH / ITEM_H) + 3    // +3 buffer
  const visEnd    = Math.min(visStart + visCount, items.length)
  const visible   = items.slice(visStart, visEnd)
  const totalH    = items.length * ITEM_H
  const offsetY   = visStart * ITEM_H

  return (
    <div
      ref={ref}
      className="overflow-y-auto scrollbar-thin"
      style={{ height: containerH, position: 'relative' }}
      onScroll={e => setScrollTop(e.currentTarget.scrollTop)}
    >
      <div style={{ height: totalH, position: 'relative' }}>
        <div style={{ position: 'absolute', top: offsetY, left: 0, right: 0 }}>
          {visible.map((item, i) => (
            <div key={visStart + i} style={{ height: ITEM_H }}>
              {renderItem(item, visStart + i)}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MEMBER TAG — compact row for waitlist user
// ─────────────────────────────────────────────────────────────────────────────
function MemberTag({ member, dimmed, highlighted, onHover, onLeave, onClick }) {
  const joinDate = member.join_date ?? member.created_at
  const isPaid   = member.deposit_token_status === 'Burned' || member.has_paid

  return (
    <div
      className={`flex items-center gap-2.5 px-3 py-2 cursor-pointer transition-all duration-150 border-b border-slate-800/40 ${
        highlighted
          ? 'bg-blue-950/50 ring-1 ring-inset ring-blue-500/40'
          : dimmed
            ? 'opacity-20'
            : 'hover:bg-slate-800/40'
      }`}
      style={{ height: ITEM_H }}
      onMouseEnter={e => onHover(member, e)}
      onMouseLeave={onLeave}
      onClick={onClick}
    >
      {/* Avatar initials */}
      <div className={`w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-[10px] font-bold ${
        isPaid ? 'bg-blue-800/60 text-blue-300' : 'bg-slate-700 text-slate-400'
      }`}>
        {(member.name ?? member.username ?? '?').charAt(0).toUpperCase()}
      </div>

      {/* Identity */}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-slate-200 truncate">@{member.username ?? '—'}</p>
        <p className="text-[9px] text-slate-500 truncate">
          Joined: {formatDate(joinDate)}
        </p>
      </div>

      {/* Payment badge */}
      <div className={`flex-shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
        isPaid
          ? 'bg-emerald-900/40 text-emerald-400 border border-emerald-800/50'
          : 'bg-slate-800 text-slate-600 border border-slate-700'
      }`}>
        {isPaid ? 'PAID' : 'WAIT'}
      </div>

      {/* Time in queue */}
      <div className="flex-shrink-0 text-[9px] text-slate-600 font-mono w-14 text-right">
        {timeAgo(joinDate)}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// LAYER 3 — Master Overflow (Waitlist)
// ─────────────────────────────────────────────────────────────────────────────
function LayerThreePanel({ members, loading, searchHighlight, searchDimAll, onHoverMember, onLeaveMember, onClickMember, viewMode, page, setPage }) {
  const total = members.length

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center py-8">
        <Spinner className="w-6 h-6 text-slate-500"/>
      </div>
    )
  }

  if (viewMode === 'virtual') {
    return (
      <VirtualizedList
        items={members}
        containerH={460}
        renderItem={(m, idx) => (
          <MemberTag
            key={m.id ?? idx}
            member={m}
            dimmed={searchDimAll && m.id !== searchHighlight?.id}
            highlighted={searchHighlight && m.id === searchHighlight.id}
            onHover={onHoverMember}
            onLeave={onLeaveMember}
            onClick={() => onClickMember(m)}
          />
        )}
      />
    )
  }

  // Paginated mode
  const start  = (page - 1) * PAGE_SIZE
  const slice  = members.slice(start, start + PAGE_SIZE)
  const pages  = Math.ceil(total / PAGE_SIZE)

  return (
    <>
      <div className="flex-1 overflow-y-auto">
        {slice.map((m, idx) => (
          <MemberTag
            key={m.id ?? idx}
            member={m}
            dimmed={searchDimAll && m.id !== searchHighlight?.id}
            highlighted={searchHighlight && m.id === searchHighlight.id}
            onHover={onHoverMember}
            onLeave={onLeaveMember}
            onClick={() => onClickMember(m)}
          />
        ))}
        {slice.length === 0 && (
          <p className="text-xs text-slate-600 text-center py-8">No members on this page</p>
        )}
      </div>
      {/* Pagination bar */}
      {pages > 1 && (
        <div className="flex items-center justify-between px-3 py-2.5 border-t border-slate-700/40 flex-shrink-0">
          <span className="text-[10px] text-slate-500">
            {start + 1}–{Math.min(start + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded text-slate-500 hover:text-white disabled:opacity-30 transition"
            >
              <ChevronLeft className="w-3.5 h-3.5"/>
            </button>
            <span className="text-[10px] text-slate-400 px-1">{page}/{pages}</span>
            <button
              onClick={() => setPage(p => Math.min(pages, p + 1))}
              disabled={page >= pages}
              className="p-1 rounded text-slate-500 hover:text-white disabled:opacity-30 transition"
            >
              <ChevronRight className="w-3.5 h-3.5"/>
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// LAYER 2 — Shared Active Reserve (Buffer)
// ─────────────────────────────────────────────────────────────────────────────
function LayerTwoPanel({ waitlistCount, paidWaitlist, multiplier, targetBuffer }) {
  const fillPct  = Math.min(1, paidWaitlist / Math.max(targetBuffer, 1))
  const isDraining = fillPct < 0.33
  const isFull     = fillPct >= 1

  const borderColor =
    isFull    ? '#10b981' :
    isDraining ? '#f59e0b' :
                 '#1e293b'

  return (
    <div className="flex flex-col h-full p-3 gap-3">
      {/* Glowing tank visual */}
      <div
        className="rounded-xl border-2 overflow-hidden flex-1 relative"
        style={{ borderColor }}
      >
        {/* Fill */}
        <div
          className="absolute bottom-0 left-0 right-0 transition-all duration-700 rounded-b"
          style={{
            height: `${fillPct * 100}%`,
            background: isDraining
              ? 'linear-gradient(180deg, #f59e0b20 0%, #f59e0b40 100%)'
              : isFull
                ? 'linear-gradient(180deg, #10b98120 0%, #10b98140 100%)'
                : 'linear-gradient(180deg, #3b82f620 0%, #3b82f640 100%)',
          }}
        />

        {/* Labels */}
        <div className="relative z-10 flex flex-col items-center justify-center h-full py-4 gap-2">
          <p className="text-[9px] text-slate-500 uppercase tracking-widest">Buffer</p>
          <p className="text-3xl font-black text-white tabular-nums">{paidWaitlist}</p>
          <p className="text-[10px] text-slate-500">Paid ready</p>
          <div className="w-full px-4 mt-1">
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${fillPct * 100}%`,
                  background: isFull ? '#10b981' : isDraining ? '#f59e0b' : '#3b82f6',
                }}
              />
            </div>
            <div className="flex justify-between text-[9px] text-slate-600 mt-0.5">
              <span>0</span>
              <span className={isFull ? 'text-emerald-500' : isDraining ? 'text-amber-500' : 'text-blue-400'}>
                {paidWaitlist} / {targetBuffer}
              </span>
            </div>
          </div>

          {/* Status badge */}
          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border mt-1 ${
            isFull
              ? 'bg-emerald-950/60 text-emerald-400 border-emerald-700/50'
              : isDraining
                ? 'bg-amber-950/60 text-amber-400 border-amber-700/50 animate-pulse'
                : 'bg-blue-950/60 text-blue-400 border-blue-700/50'
          }`}>
            {isFull ? '▶ POOL TRIGGER READY' : isDraining ? '⚠ DRAINING' : '● FILLING'}
          </span>
        </div>
      </div>

      {/* AI Multiplier card */}
      <div className="bg-slate-800 rounded-xl p-3 flex-shrink-0">
        <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-1 text-center">AI Multiplier</p>
        <p className={`text-2xl font-black text-center tabular-nums ${
          multiplier > 1.5 ? 'text-emerald-400' :
          multiplier < 0.75 ? 'text-red-400' :
          'text-blue-400'
        }`}>{multiplier.toFixed(2)}×</p>
        <p className="text-[9px] text-slate-600 text-center mt-0.5">
          {multiplier > 1.5 ? 'Fast-fill mode' : multiplier < 0.75 ? 'Throttled' : 'Normal flow'}
        </p>
      </div>

      {/* Total waitlist */}
      <div className="bg-slate-800 rounded-xl p-3 flex-shrink-0 text-center">
        <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-1">Total Overflow</p>
        <p className="text-xl font-bold text-slate-200 tabular-nums">{waitlistCount}</p>
        <p className="text-[9px] text-slate-600">all waitlist members</p>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// LAYER 1 — Execution Engines (Active Pools)
// ─────────────────────────────────────────────────────────────────────────────
function PoolMiniCard({ pool, dimmed }) {
  const name    = pool.name ?? pool.pool_name ?? `Pool #${pool.id ?? pool.pool_id}`
  const members = pool.total_members ?? pool.current_member_count ?? 0
  const status  = pool.status ?? pool.pool_status
  const hasVacancy = members < 12 && status === 'Active'

  return (
    <div className={`rounded-xl border p-3 transition-all ${
      dimmed ? 'opacity-20' : ''
    } ${
      hasVacancy
        ? 'border-red-700/50 bg-red-950/15'
        : 'border-slate-700/50 bg-slate-800/50'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-bold text-slate-200 truncate">{name}</span>
        {hasVacancy && (
          <span className="text-[8px] font-black text-red-400 border border-red-800/50 px-1 py-0.5 rounded-full ml-1 flex-shrink-0 animate-pulse">
            VACANCY
          </span>
        )}
      </div>
      {/* Fill progress */}
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden mb-1.5">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${(members / 12) * 100}%`,
            background: members >= 12 ? '#10b981' : members >= 8 ? '#3b82f6' : members >= 4 ? '#f59e0b' : '#ef4444',
          }}
        />
      </div>
      <div className="flex items-center justify-between text-[9px]">
        <span className={`font-mono font-bold ${members >= 12 ? 'text-emerald-400' : 'text-amber-400'}`}>
          {members}/12
        </span>
        {pool.contains_flagged_l4 && (
          <span className="text-rose-500 font-bold">⊕ L4</span>
        )}
        {pool.draw_completed_this_week && (
          <span className="text-slate-600">✓ done</span>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MEMBER HOVER TOOLTIP
// ─────────────────────────────────────────────────────────────────────────────
function MemberTooltip({ member, x, y }) {
  if (!member) return null
  const joinDate  = member.join_date ?? member.created_at
  const queueTime = joinDate ? ((Date.now() - new Date(joinDate).getTime()) / 3600000).toFixed(1) : '?'
  const isPaid    = member.deposit_token_status === 'Burned' || member.has_paid

  return (
    <div
      className="fixed z-50 bg-slate-900 border border-slate-600 rounded-xl p-3 shadow-2xl pointer-events-none w-64"
      style={{ top: Math.min(y + 10, window.innerHeight - 160), left: Math.min(x + 10, window.innerWidth - 270) }}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 rounded-full bg-blue-800/50 text-blue-300 flex items-center justify-center text-xs font-bold">
          {(member.name ?? member.username ?? '?').charAt(0).toUpperCase()}
        </div>
        <div>
          <p className="text-sm font-bold text-white">@{member.username}</p>
          <p className="text-[10px] text-slate-500">{member.name}</p>
        </div>
      </div>
      <div className="space-y-1.5 text-[10px]">
        <div className="flex justify-between">
          <span className="text-slate-500">Status</span>
          <span className="font-bold text-blue-400">WAITLIST</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Payment</span>
          <span className={`font-bold ${isPaid ? 'text-emerald-400' : 'text-slate-500'}`}>
            {isPaid ? 'Paid ✓' : 'Pending'}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Time in Queue</span>
          <span className="font-mono text-slate-300">{queueTime}h</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Joined</span>
          <span className="font-mono text-slate-400">{formatDate(joinDate)}</span>
        </div>
        {isPaid && (
          <div className="mt-1.5 pt-1.5 border-t border-slate-700 text-amber-400 font-semibold">
            Predicted injection: Next Draw
          </div>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// ENTITY SEARCH — spotlight an individual member across all layers
// ─────────────────────────────────────────────────────────────────────────────
function EntitySearch({ allMembers, onHighlight, onClear, highlighted }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])

  const search = useCallback((q) => {
    const t = q.trim().toLowerCase()
    if (!t) { setResults([]); return }
    setResults(allMembers.filter(m =>
      (m.username ?? '').toLowerCase().includes(t) ||
      String(m.id ?? '').includes(t) ||
      (m.name ?? '').toLowerCase().includes(t)
    ).slice(0, 8))
  }, [allMembers])

  useEffect(() => { search(query) }, [query, search])

  return (
    <div className="relative">
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-800 border border-slate-600 rounded-xl">
        <Search className="w-4 h-4 text-slate-500 flex-shrink-0"/>
        <input
          className="flex-1 bg-transparent text-sm text-white placeholder-slate-600 focus:outline-none"
          placeholder="Search username / ID… dim everything else"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        {(query || highlighted) && (
          <button onClick={() => { setQuery(''); setResults([]); onClear() }}
                  className="text-slate-500 hover:text-white transition">
            <X className="w-3.5 h-3.5"/>
          </button>
        )}
      </div>

      {results.length > 0 && (
        <div className="absolute z-40 mt-1 w-full bg-slate-900 border border-slate-600 rounded-xl shadow-2xl overflow-hidden">
          {results.map(m => (
            <button
              key={m.id ?? m.username}
              onClick={() => { onHighlight(m); setResults([]); setQuery(`@${m.username}`) }}
              className="w-full text-left px-3 py-2.5 hover:bg-slate-800 transition border-b border-slate-700/50 last:border-0"
            >
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-slate-700 text-slate-300 flex items-center justify-center text-[10px] font-bold">
                  {(m.name ?? m.username ?? '?').charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="text-xs font-bold text-white">@{m.username}</p>
                  <p className="text-[10px] text-slate-500">{m.name} · {m.status}</p>
                </div>
                <span className={`ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${
                  m.status === 'Active' ? 'bg-blue-950/50 text-blue-400 border-blue-800/50' :
                  'bg-slate-800 text-slate-500 border-slate-700'
                }`}>{m.status}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────
export default function HydraulicPipeline() {
  const toast = useToast()

  const [waitlist,    setWaitlist]    = useState([])
  const [activeUsers, setActiveUsers] = useState([])
  const [pools,       setPools]       = useState([])
  const [aiData,      setAiData]      = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [refreshing,  setRefreshing]  = useState(false)
  const [lastAt,      setLastAt]      = useState(null)

  // View toggle: 'virtual' or 'paginated'
  const [viewMode, setViewMode] = useState('paginated')
  const [page, setPage] = useState(1)

  // Entity search / highlight state
  const [hoveredMember,    setHoveredMember]    = useState(null)
  const [hoverPos,         setHoverPos]         = useState({ x: 0, y: 0 })
  const [highlightedMember, setHighlightedMember] = useState(null)

  const fetchAll = useCallback(async (silent = false) => {
    silent ? setRefreshing(true) : setLoading(true)
    const [wR, aR, pR, aiR] = await Promise.allSettled([
      getAdminUsers({ status: 'Waitlist', limit: 1000 }),
      getAdminUsers({ status: 'Active',   limit: 500  }),
      getPools({ limit: 100 }),
      getAiSnapshot(),
    ])
    if (wR.status  === 'fulfilled') { setWaitlist(wR.value.data ?? []);    setPage(1) }
    if (aR.status  === 'fulfilled')   setActiveUsers(aR.value.data ?? [])
    if (pR.status  === 'fulfilled')   setPools(pR.value.data ?? [])
    if (aiR.status === 'fulfilled')   setAiData(aiR.value.data)
    setLoading(false); setRefreshing(false); setLastAt(new Date())
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])
  useEffect(() => {
    const id = setInterval(() => fetchAll(true), 30_000)
    return () => clearInterval(id)
  }, [fetchAll])

  // Derived
  const multiplier  = fP(aiData?.multiplier ?? 1.0)
  const paidWaitlist = waitlist.filter(u => u.deposit_token_status === 'Burned' || u.has_paid).length
  const targetBuffer = 24
  const activePools  = pools.filter(p => (p.status ?? p.pool_status) === 'Active')
  const poolsWithVacancy = activePools.filter(p => (p.total_members ?? p.current_member_count ?? 0) < 12)

  // All members across all layers for entity search
  const allMembers = useMemo(() => [...waitlist, ...activeUsers], [waitlist, activeUsers])

  const dimAll = !!highlightedMember

  return (
    <div className="p-6 space-y-5 h-full">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-blue-900/40">
              <Activity className="w-5 h-5 text-blue-400"/>
            </div>
            Hydraulic Pipeline
          </h1>
          <p className="text-sm text-slate-500 mt-0.5 ml-11">
            Live 3-layer flow visualizer ·{' '}
            {lastAt ? `Synced ${lastAt.toLocaleTimeString()}` : 'Connecting…'}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {/* View mode toggle */}
          <button
            onClick={() => setViewMode(v => v === 'virtual' ? 'paginated' : 'virtual')}
            className="flex items-center gap-2 px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs font-medium text-slate-300 hover:bg-slate-700 transition"
          >
            {viewMode === 'virtual'
              ? <><ToggleRight className="w-4 h-4 text-blue-400"/> Virtualized</>
              : <><ToggleLeft  className="w-4 h-4 text-slate-500"/> Paginated</>
            }
          </button>

          <button
            onClick={() => fetchAll(true)} disabled={refreshing}
            className="flex items-center gap-2 px-3 py-2 bg-slate-800 border border-slate-700 text-slate-300 rounded-xl text-sm font-medium hover:bg-slate-700 transition disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`}/>
          </button>
        </div>
      </div>

      {/* ── Entity Search ──────────────────────────────────────────────────── */}
      <EntitySearch
        allMembers={allMembers}
        highlighted={highlightedMember}
        onHighlight={m => { setHighlightedMember(m); setPage(1) }}
        onClear={() => setHighlightedMember(null)}
      />

      {/* Stats strip */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { l: 'Layer 3 Total',  v: waitlist.length,          c: 'text-slate-300' },
          { l: 'Paid Buffer',    v: paidWaitlist,             c: paidWaitlist >= targetBuffer ? 'text-emerald-400' : 'text-blue-400' },
          { l: 'Active Pools',   v: activePools.length,       c: 'text-blue-400' },
          { l: 'Vacancies',      v: poolsWithVacancy.length,  c: poolsWithVacancy.length > 0 ? 'text-red-400 animate-pulse' : 'text-slate-500' },
          { l: 'AI Multiplier',  v: `${multiplier.toFixed(2)}×`, c: multiplier > 1.5 ? 'text-emerald-400' : 'text-slate-400' },
        ].map(({ l, v, c }) => (
          <div key={l} className="bg-slate-900 border border-slate-700/50 rounded-xl p-3 text-center">
            <p className="text-[9px] text-slate-600 uppercase tracking-widest mb-1">{l}</p>
            <p className={`text-xl font-black tabular-nums ${c}`}>{v}</p>
          </div>
        ))}
      </div>

      {/* ── 3-Chamber Kanban ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-12 gap-4" style={{ minHeight: 520 }}>

        {/* ─── COLUMN 1 — LAYER 3 (Master Overflow) ─── */}
        <div className="col-span-5 bg-slate-900 border border-slate-700/50 rounded-2xl overflow-hidden flex flex-col">
          {/* Header */}
          <div className="px-4 py-3 border-b border-slate-700/40 flex items-center gap-2 flex-shrink-0">
            <div className="w-2 h-2 rounded-full bg-slate-400"/>
            <h3 className="font-semibold text-slate-200 text-sm">Layer 3 — Master Overflow</h3>
            <span className="ml-auto text-[10px] font-bold text-slate-400 bg-slate-800 px-2 py-0.5 rounded-full">
              {waitlist.length} members
            </span>
          </div>

          <LayerThreePanel
            members={waitlist}
            loading={loading}
            searchHighlight={highlightedMember}
            searchDimAll={dimAll}
            onHoverMember={(m, e) => { setHoveredMember(m); if (e) setHoverPos({ x: e.clientX, y: e.clientY }) }}
            onLeaveMember={() => setHoveredMember(null)}
            onClickMember={m => setHighlightedMember(prev => prev?.id === m.id ? null : m)}
            viewMode={viewMode}
            page={page}
            setPage={setPage}
          />
        </div>

        {/* ─── COLUMN 2 — LAYER 2 (Buffer) ─── */}
        <div className="col-span-3 bg-slate-900 border border-slate-700/50 rounded-2xl overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-slate-700/40 flex items-center gap-2 flex-shrink-0">
            <div className={`w-2 h-2 rounded-full ${paidWaitlist >= targetBuffer ? 'bg-emerald-400' : 'bg-amber-400 animate-pulse'}`}/>
            <h3 className="font-semibold text-slate-200 text-sm">Layer 2 — Reserve</h3>
          </div>

          <div className="flex-1 overflow-hidden">
            <LayerTwoPanel
              waitlistCount={waitlist.length}
              paidWaitlist={paidWaitlist}
              multiplier={multiplier}
              targetBuffer={targetBuffer}
            />
          </div>
        </div>

        {/* ─── COLUMN 3 — LAYER 1 (Execution Engines) ─── */}
        <div className="col-span-4 bg-slate-900 border border-slate-700/50 rounded-2xl overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-slate-700/40 flex items-center gap-2 flex-shrink-0">
            <div className={`w-2 h-2 rounded-full ${poolsWithVacancy.length > 0 ? 'bg-red-400 animate-pulse' : 'bg-emerald-400'}`}/>
            <h3 className="font-semibold text-slate-200 text-sm">Layer 1 — Execution Engines</h3>
            {poolsWithVacancy.length > 0 && (
              <span className="text-[9px] font-bold text-red-400 ml-auto">
                {poolsWithVacancy.length} vacancy
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Spinner className="w-5 h-5 text-slate-500"/>
              </div>
            ) : activePools.length === 0 ? (
              <p className="text-xs text-slate-600 text-center py-8">No active pools</p>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {activePools.map(p => (
                  <PoolMiniCard
                    key={p.id ?? p.pool_id}
                    pool={p}
                    dimmed={dimAll}
                  />
                ))}
                {pools.filter(p => (p.status ?? p.pool_status) !== 'Active').slice(0, 4).map(p => (
                  <PoolMiniCard
                    key={p.id ?? p.pool_id}
                    pool={p}
                    dimmed={true}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Footer: vacancy routing hint */}
          {!loading && poolsWithVacancy.length > 0 && (
            <div className="px-3 py-2 border-t border-slate-700/40 text-[10px] text-red-400 flex items-center gap-1.5 flex-shrink-0">
              <AlertTriangle className="w-3 h-3 flex-shrink-0"/>
              {poolsWithVacancy.length} pool{poolsWithVacancy.length !== 1 ? 's' : ''} need buffer injection
            </div>
          )}
        </div>
      </div>

      {/* Member hover tooltip */}
      {hoveredMember && !highlightedMember && (
        <MemberTooltip
          member={hoveredMember}
          x={hoverPos.x}
          y={hoverPos.y}
        />
      )}

      {/* Highlighted member spotlight */}
      {highlightedMember && (
        <div className="bg-blue-950/40 border border-blue-700/40 rounded-2xl p-4 flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-blue-800/50 text-blue-300 flex items-center justify-center text-sm font-bold flex-shrink-0">
            {(highlightedMember.name ?? highlightedMember.username ?? '?').charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <p className="font-bold text-white">@{highlightedMember.username}</p>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                highlightedMember.status === 'Active'
                  ? 'bg-blue-950 text-blue-400 border-blue-700/50'
                  : 'bg-slate-800 text-slate-500 border-slate-700'
              }`}>{highlightedMember.status}</span>
              {highlightedMember.current_level && (
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-violet-950/60 text-violet-300 border border-violet-700/50">
                  L{highlightedMember.current_level}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-400 mt-0.5">{highlightedMember.name}</p>
            <div className="flex items-center gap-4 mt-2 text-[10px] text-slate-500">
              <span>Joined: {formatDate(highlightedMember.join_date ?? highlightedMember.created_at)}</span>
              <span>Time in system: {timeAgo(highlightedMember.join_date ?? highlightedMember.created_at)}</span>
              {highlightedMember.current_pool_id && (
                <span className="text-blue-400 font-semibold">Pool #{highlightedMember.current_pool_id}</span>
              )}
            </div>
          </div>
          <button onClick={() => setHighlightedMember(null)}
                  className="flex-shrink-0 text-slate-600 hover:text-white transition">
            <X className="w-4 h-4"/>
          </button>
        </div>
      )}
    </div>
  )
}
