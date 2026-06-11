/**
 * CommandCenter.jsx — Quantitative Command Center
 *
 * Module 1: Global Telemetry & Liquidity HUD
 *   · LPI Thermometer (vertical neon gauge)
 *   · Velocity vs Burn Rate "Breathing Chart"
 *   · Liability / Float / Sinking Fund Radar bars
 *
 * Module 2: Neural Interface — visualising all 5 Brains
 *   · Brain 1 & 4 — Hydraulic Topology Map (buffer → pool schematic)
 *   · Brain 2 & 3 — Hype Scatterplot (RDR vs Momentum)
 *   · Brain 5     — Anti-Maturity Execution Grid (L3/L4 members)
 *
 * Flash-Flood mode: when rdr > 70 AND momentum > 0, the entire page
 * border shifts amber and a ⚡ FLASH FLOOD warning pulses.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Cpu, Activity, Target, AlertTriangle, TrendingUp, TrendingDown,
  RefreshCw, Zap, Shield, Users, IndianRupee, Terminal,
  Crosshair, Radio, Network, Layers, BarChart3, Clock,
} from 'lucide-react'
import {
  ResponsiveContainer, ComposedChart, Area, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'
import Spinner from '../components/Spinner'
import {
  getBrain5Lpi, getAiSnapshot, getFinancials, getChartData,
  getAdminUsers, getPoolStats,
} from '../api/client'
import { useToast } from '../context/ToastContext'

// ─── Helpers ──────────────────────────────────────────────────────────────────
const INR  = v => `₹${Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const NUM  = v => Number(v ?? 0).toLocaleString('en-IN')
const fP   = v => parseFloat(v ?? 0)
const fI   = v => parseInt(v ?? 0, 10)

// Pointy-top hexagon polygon points for SVG
const hexPts = (cx, cy, r) =>
  Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i - Math.PI / 2
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`
  }).join(' ')

// ─────────────────────────────────────────────────────────────────────────────
// MODULE 1-A — LPI Thermometer (vertical neon gauge)
// ─────────────────────────────────────────────────────────────────────────────
function LpiThermometer({ lpi = 0 }) {
  const tubeH = 220          // total tube length in SVG units
  const tubeTop = 18
  const tubeBot = tubeTop + tubeH   // 238
  const bulbCy  = 260

  const pct    = Math.min(100, Math.max(0, lpi)) / 100
  const fillH  = tubeH * pct
  const fillY  = tubeBot - fillH

  const color =
    lpi < 14 ? '#10b981' :
    lpi < 25 ? '#f59e0b' :
    lpi < 50 ? '#f97316' :
               '#ef4444'
  const glow = `drop-shadow(0 0 ${lpi >= 50 ? 14 : lpi >= 25 ? 8 : 5}px ${color})`

  // Zone boundary y-coordinates (from bottom)
  const z14 = tubeBot - tubeH * 0.14
  const z25 = tubeBot - tubeH * 0.25
  const z50 = tubeBot - tubeH * 0.50

  const zoneLabel =
    lpi < 14 ? 'Regular Pool Dominance' :
    lpi < 25 ? 'Type A Spawning Active' :
    lpi < 50 ? 'SDE Protocol Engaged'   :
               'CRITICAL CLEARANCE'

  return (
    <div className="flex flex-col items-center select-none">
      <svg viewBox="0 0 80 288" style={{ height: 240 }}>
        {/* Zone background fills (faint) */}
        <rect x="27" y={z50}         width="16" height={tubeBot - z50}         fill="#ef4444" opacity="0.07" rx="3"/>
        <rect x="27" y={z25}         width="16" height={z50  - z25}            fill="#f97316" opacity="0.07" rx="3"/>
        <rect x="27" y={z14}         width="16" height={z25  - z14}            fill="#f59e0b" opacity="0.07" rx="3"/>
        <rect x="27" y={tubeTop}     width="16" height={z14  - tubeTop}        fill="#10b981" opacity="0.05" rx="3"/>

        {/* Tube outline */}
        <rect x="27" y={tubeTop} width="16" height={tubeH}
              rx="8" fill="none" stroke="#1e293b" strokeWidth="1.5"/>

        {/* Fill bar */}
        <rect
          x="29.5" y={fillY} width="11" height={Math.max(fillH, 2)}
          rx={fillH > 12 ? 5 : 2}
          fill={color}
          style={{ filter: glow, transition: 'y 0.9s ease, height 0.9s ease' }}
          className={lpi >= 50 ? 'animate-pulse' : lpi >= 25 ? '' : ''}
        />

        {/* Bulb */}
        <circle cx="35" cy={bulbCy} r="14" fill={color} style={{ filter: glow }}
                className={lpi >= 50 ? 'animate-pulse' : ''}/>
        <circle cx="35" cy={bulbCy} r="8"  fill="white" opacity="0.2"/>

        {/* Zone marker dashes + labels */}
        {[
          { y: z14, t: '14%', c: '#f59e0b' },
          { y: z25, t: '25%', c: '#f97316' },
          { y: z50, t: '50%', c: '#ef4444' },
        ].map(({ y, t, c }) => (
          <g key={t}>
            <line x1="23" y1={y} x2="47" y2={y} stroke={c} strokeWidth="1" strokeDasharray="2 1.5" opacity="0.7"/>
            <text x="51" y={y + 3.5} fontSize="7.5" fill="#64748b" fontFamily="monospace">{t}</text>
          </g>
        ))}

        {/* Current value */}
        {fillH > 16 && (
          <text x="35" y={fillY - 4} textAnchor="middle"
                fontSize="8" fill={color} fontWeight="800" fontFamily="monospace">
            {lpi.toFixed(1)}
          </text>
        )}
      </svg>

      {/* Label below */}
      <div className="mt-1 text-center px-2">
        <p className="text-[11px] font-bold" style={{ color }}>{lpi.toFixed(1)}%</p>
        <p className={`text-[9px] font-bold uppercase tracking-widest mt-0.5 ${
          lpi >= 50 ? 'text-red-400 animate-pulse' :
          lpi >= 25 ? 'text-orange-400' :
          lpi >= 14 ? 'text-amber-400' : 'text-emerald-400'
        }`}>{zoneLabel}</p>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MODULE 1-B — Velocity vs Burn Rate "Breathing Chart"
// ─────────────────────────────────────────────────────────────────────────────
function VelocityBurnChart({ chartData = [], burnRate = 0 }) {
  const pts = chartData.map(pt => ({
    l:  pt.period?.length >= 10 ? pt.period.slice(5) : (pt.period ?? ''),
    v:  fI(pt.registrations),
    b:  burnRate,
  }))

  const isDry = pts.length > 0 && pts[pts.length - 1].v < burnRate

  return (
    <div>
      {isDry && (
        <div className="mb-2 flex items-center gap-2 px-3 py-1.5 bg-red-950/40 border border-red-800/40 rounded-lg text-xs font-bold text-red-400">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0"/>
          DRY PHASE — velocity below burn rate. Liquidity bleed detected.
        </div>
      )}
      <ResponsiveContainer width="100%" height={160}>
        <ComposedChart data={pts} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <defs>
            <linearGradient id="gVel" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.35}/>
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.02}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false}/>
          <XAxis dataKey="l" tick={{ fontSize: 9, fill: '#475569' }} tickLine={false} axisLine={false}
                 interval="preserveStartEnd"/>
          <YAxis tick={{ fontSize: 9, fill: '#475569' }} tickLine={false} axisLine={false}/>
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 11 }}
            labelStyle={{ color: '#94a3b8' }}
            itemStyle={{ color: '#e2e8f0' }}
          />
          <ReferenceLine y={burnRate} stroke="#ef4444" strokeWidth={1.5} strokeDasharray="5 3" label={{ value: `Burn ${burnRate}`, position: 'right', fontSize: 8, fill: '#ef4444' }}/>
          <Area type="monotone" dataKey="v" name="Velocity"
                stroke="#3b82f6" strokeWidth={2} fill="url(#gVel)" dot={false}/>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MODULE 1-C — Liability vs Float Radar (horizontal bars)
// ─────────────────────────────────────────────────────────────────────────────
function LiabilityFloatBar({ financials }) {
  const float       = fP(financials?.in_hand_liquidity_inr    ?? 0)
  const liability   = fP(financials?.doomsday_liability_inr   ?? 0)
  const profit      = fP(financials?.pure_realized_profit_inr ?? 0)
  const sinkingFund = Math.max(0, profit)

  const maxVal = Math.max(float, liability, 1)

  const bars = [
    { label: 'Master Float',   value: float,       color: '#10b981', glow: '#10b981' },
    { label: 'Max Liability',  value: liability,    color: '#ef4444', glow: '#ef4444' },
    { label: 'Sinking Fund',   value: sinkingFund,  color: '#f59e0b', glow: '#f59e0b' },
  ]

  return (
    <div className="space-y-3.5">
      {bars.map(({ label, value, color, glow }) => (
        <div key={label}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">{label}</span>
            <span className="text-xs font-bold tabular-nums" style={{ color }}>{INR(value)}</span>
          </div>
          <div className="h-2.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width: `${Math.min(100, value / maxVal * 100)}%`,
                background: color,
                boxShadow: `0 0 8px ${glow}40`,
              }}
            />
          </div>
        </div>
      ))}
      <div className="mt-3 pt-3 border-t border-slate-700/40">
        <div className="flex justify-between text-[10px]">
          <span className="text-slate-500">Float Coverage Ratio</span>
          <span className={`font-bold ${float >= liability ? 'text-emerald-400' : 'text-red-400'}`}>
            {liability > 0 ? (float / liability * 100).toFixed(0) : '∞'}%
          </span>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MODULE 2-A — Brain 1 & 4: Hydraulic Topology Map
// ─────────────────────────────────────────────────────────────────────────────
function TopologyMap({ pools = [], waitlistCount = 0, multiplier = 1.0, condensationActive = false }) {
  // Buffer node (left)
  const bufX = 20, bufY = 40, bufW = 80, bufH = 200
  const bufCY = bufY + bufH / 2

  // Up to 6 pool nodes in a 2-col grid
  const visible = pools.slice(0, 6)
  const poolNodes = visible.map((p, i) => ({
    cx: 250 + (i % 2) * 110,
    cy:  60 + Math.floor(i / 2) * 90,
    pool: p,
  }))

  const lineW = Math.max(0.5, Math.min(4, multiplier * 1.5))

  return (
    <div className="relative">
      <svg viewBox="0 0 480 280" className="w-full" style={{ height: 200 }}>
        {/* Buffer container */}
        <rect x={bufX} y={bufY} width={bufW} height={bufH} rx="6"
              fill="#0f172a" stroke={multiplier > 1.4 ? '#10b981' : multiplier < 0.7 ? '#f59e0b' : '#1e293b'}
              strokeWidth="1.5"/>

        {/* Buffer fill level */}
        {(() => {
          const capacity = 24
          const fillPct = Math.min(1, waitlistCount / Math.max(capacity, 1))
          const fillH = bufH * fillPct
          return (
            <rect x={bufX + 4} y={bufY + bufH - fillH} width={bufW - 8} height={fillH}
                  rx="4" fill="#3b82f6" opacity="0.25"/>
          )
        })()}

        {/* Buffer label */}
        <text x={bufX + bufW / 2} y={bufY - 6} textAnchor="middle" fontSize="8" fill="#64748b" fontFamily="monospace">BUFFER</text>
        <text x={bufX + bufW / 2} y={bufY + bufH / 2 - 6} textAnchor="middle" fontSize="13" fill="#3b82f6" fontWeight="800">{waitlistCount}</text>
        <text x={bufX + bufW / 2} y={bufY + bufH / 2 + 8} textAnchor="middle" fontSize="7" fill="#475569">WAITLIST</text>
        <text x={bufX + bufW / 2} y={bufY + bufH / 2 + 20} textAnchor="middle" fontSize="7.5" fill={multiplier > 1.2 ? '#10b981' : '#f59e0b'} fontWeight="700">{multiplier.toFixed(2)}× AI</text>

        {/* Connecting bezier paths */}
        {poolNodes.map(({ cx, cy, pool }) => {
          const active = pool.pool_status === 'Active' || pool.status === 'Active'
          return (
            <path key={pool.pool_id ?? pool.id}
              d={`M ${bufX + bufW} ${bufCY} C ${bufX + bufW + 50} ${bufCY}, ${cx - 50} ${cy}, ${cx - 32} ${cy}`}
              fill="none"
              stroke={active ? '#3b82f6' : '#334155'}
              strokeWidth={lineW}
              opacity={active ? 0.7 : 0.3}
            />
          )
        })}

        {/* Condensation overlay arrow (Brain 4) */}
        {condensationActive && visible.length >= 2 && (
          <path
            d={`M ${poolNodes[0].cx + 30} ${poolNodes[0].cy} Q 440 ${bufCY} ${poolNodes[visible.length - 1].cx + 30} ${poolNodes[visible.length - 1].cy}`}
            fill="none" stroke="#ef4444" strokeWidth="2" strokeDasharray="5 3" opacity="0.6"
          />
        )}

        {/* Pool hexagons */}
        {poolNodes.map(({ cx, cy, pool }) => {
          const members = pool.current_member_count ?? 0
          const capacity = 12
          const fillPct = members / capacity
          const hexColor =
            fillPct >= 1    ? '#10b981' :
            fillPct >= 0.67 ? '#3b82f6' :
            fillPct >= 0.33 ? '#f59e0b' :
                              '#ef4444'
          const active = pool.pool_status === 'Active' || pool.status === 'Active'

          return (
            <g key={pool.pool_id ?? pool.id} opacity={active ? 1 : 0.5}>
              {/* Hex background */}
              <polygon points={hexPts(cx, cy, 30)}
                       fill={hexColor} opacity="0.12" stroke={hexColor} strokeWidth="1.2"/>
              {/* Count label */}
              <text x={cx} y={cy - 4} textAnchor="middle" fontSize="11" fill={hexColor} fontWeight="800">{members}</text>
              <text x={cx} y={cy + 8} textAnchor="middle" fontSize="7" fill="#475569">/12</text>
              {/* Pool name below */}
              <text x={cx} y={cy + 26} textAnchor="middle" fontSize="6.5" fill="#64748b">
                {(pool.pool_name ?? `Pool #${pool.pool_id ?? pool.id ?? '?'}`).slice(0, 8)}
              </text>
              {/* L4 flag */}
              {(pool.contains_flagged_l4 ?? false) && (
                <circle cx={cx + 22} cy={cy - 24} r="5" fill="#f43f5e" opacity="0.9">
                  <animate attributeName="opacity" values="0.9;0.4;0.9" dur="1s" repeatCount="indefinite"/>
                </circle>
              )}
            </g>
          )
        })}

        {/* More pools indicator */}
        {pools.length > 6 && (
          <text x="460" y={bufCY + 4} fontSize="9" fill="#475569" textAnchor="middle">+{pools.length - 6}</text>
        )}

        {/* AI Multiplier label on arrow */}
        <text x={bufX + bufW + 30} y={bufCY - 8} fontSize="7.5" fill="#3b82f6" fontWeight="700">
          {multiplier.toFixed(2)}×
        </text>
      </svg>

      {condensationActive && (
        <div className="absolute top-1 right-1 px-2 py-0.5 rounded text-[9px] font-bold bg-red-950/80 text-red-400 border border-red-800/60 animate-pulse">
          ⚠ CONDENSATION ACTIVE
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MODULE 2-B — Brain 2 & 3: Hype Scatterplot (RDR vs Momentum)
// ─────────────────────────────────────────────────────────────────────────────
function BrainScatterplot({ rdr = 0, momentum = 0, scenario = '' }) {
  // SVG plot area
  const W = 340, H = 260
  const PAD = 44
  const plotW = W - PAD * 2
  const plotH = H - PAD * 2

  // Current state point
  const normMom = Math.max(-100, Math.min(100, fP(momentum)))
  const sx = PAD + (Math.min(100, Math.max(0, fP(rdr))) / 100) * plotW
  const sy = PAD + plotH / 2 - (normMom / 100) * (plotH / 2)

  const isFlashFlood = fP(rdr) > 70 && normMom > 0
  const isDryPhase   = normMom < -20

  const dotColor = isFlashFlood ? '#f59e0b' : isDryPhase ? '#ef4444' : '#3b82f6'

  return (
    <div className={`relative rounded-xl overflow-hidden ${isFlashFlood ? 'ring-2 ring-amber-500/60' : ''}`}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: 210 }}>
        {/* Quadrant fills */}
        {/* TL: High Momentum, Low RDR */}
        <rect x={PAD} y={PAD} width={plotW/2} height={plotH/2} fill="#ef4444" opacity="0.04"/>
        {/* TR: FLASH FLOOD — High Momentum, High RDR */}
        <rect x={PAD + plotW/2} y={PAD} width={plotW/2} height={plotH/2}
              fill={isFlashFlood ? '#f59e0b' : '#3b82f6'} opacity={isFlashFlood ? 0.12 : 0.04}/>
        {/* BL: Low Momentum, Low RDR */}
        <rect x={PAD} y={PAD + plotH/2} width={plotW/2} height={plotH/2} fill="#10b981" opacity="0.04"/>
        {/* BR: Low Momentum, High RDR */}
        <rect x={PAD + plotW/2} y={PAD + plotH/2} width={plotW/2} height={plotH/2} fill="#94a3b8" opacity="0.03"/>

        {/* Quadrant dividers */}
        <line x1={PAD + plotW/2} y1={PAD} x2={PAD + plotW/2} y2={PAD + plotH}
              stroke="#1e293b" strokeWidth="1" strokeDasharray="4 3"/>
        <line x1={PAD} y1={PAD + plotH/2} x2={PAD + plotW} y2={PAD + plotH/2}
              stroke="#1e293b" strokeWidth="1" strokeDasharray="4 3"/>

        {/* Axes */}
        <line x1={PAD} y1={PAD + plotH} x2={PAD + plotW} y2={PAD + plotH}
              stroke="#334155" strokeWidth="1.2"/>
        <line x1={PAD} y1={PAD} x2={PAD} y2={PAD + plotH}
              stroke="#334155" strokeWidth="1.2"/>

        {/* Quadrant labels */}
        <text x={PAD + 6} y={PAD + 14} fontSize="7.5" fill="#ef4444" opacity="0.65">High Mom, Low RDR</text>
        <text x={PAD + plotW - 6} y={PAD + 14} textAnchor="end" fontSize="7.5"
              fill={isFlashFlood ? '#f59e0b' : '#64748b'} fontWeight={isFlashFlood ? '800' : '400'}>
          {isFlashFlood ? '⚡ FLASH FLOOD' : 'High Mom + High RDR'}
        </text>
        <text x={PAD + 6} y={PAD + plotH - 6} fontSize="7.5" fill="#10b981" opacity="0.65">Stable Growth</text>
        <text x={PAD + plotW - 6} y={PAD + plotH - 6} textAnchor="end" fontSize="7.5" fill="#64748b" opacity="0.65">High RDR, Low Mom</text>

        {/* Axis labels */}
        <text x={PAD + plotW / 2} y={H - 8} textAnchor="middle" fontSize="9" fill="#475569">RDR %</text>
        <text x={12} y={PAD + plotH / 2} textAnchor="middle" fontSize="9" fill="#475569"
              transform={`rotate(-90, 12, ${PAD + plotH / 2})`}>Momentum</text>

        {/* Tick markers */}
        {[0, 25, 50, 75, 100].map(v => (
          <g key={v}>
            <text x={PAD + v / 100 * plotW} y={PAD + plotH + 12} textAnchor="middle" fontSize="7" fill="#334155">{v}</text>
          </g>
        ))}

        {/* Current state reticle */}
        {/* Outer ring */}
        <circle cx={sx} cy={sy} r={isFlashFlood ? 16 : 12}
                fill="none" stroke={dotColor} strokeWidth="1" opacity="0.4">
          {isFlashFlood && (
            <animate attributeName="r" values="12;20;12" dur="1.2s" repeatCount="indefinite"/>
          )}
        </circle>
        {/* Cross-hair lines */}
        <line x1={sx - 10} y1={sy} x2={sx - 4} y2={sy} stroke={dotColor} strokeWidth="1.5"/>
        <line x1={sx + 4}  y1={sy} x2={sx + 10} y2={sy} stroke={dotColor} strokeWidth="1.5"/>
        <line x1={sx} y1={sy - 10} x2={sx} y2={sy - 4} stroke={dotColor} strokeWidth="1.5"/>
        <line x1={sx} y1={sy + 4}  x2={sx} y2={sy + 10} stroke={dotColor} strokeWidth="1.5"/>
        {/* Core dot */}
        <circle cx={sx} cy={sy} r="4" fill={dotColor}>
          <animate attributeName="opacity" values="1;0.4;1" dur="1.5s" repeatCount="indefinite"/>
        </circle>

        {/* Scenario label near the dot */}
        {scenario && (
          <text x={sx + 14} y={sy + 4} fontSize="8" fill={dotColor} fontWeight="700">
            {scenario}
          </text>
        )}
      </svg>

      {isFlashFlood && (
        <div className="absolute top-2 right-2 px-2 py-1 rounded-md text-[10px] font-black text-amber-300 bg-amber-950/70 border border-amber-700/60 animate-pulse">
          ⚡ FLASH FLOOD MODE
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// MODULE 2-C — Brain 5: Anti-Maturity Execution Grid
// ─────────────────────────────────────────────────────────────────────────────
function AntiMaturityGrid({ users = [] }) {
  const l4 = users.filter(u => u.current_level === 4)
  const l3 = users.filter(u => u.current_level === 3)
  const rows = [...l4, ...l3]  // L4 targets first

  return (
    <div className="overflow-auto max-h-64">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-900 z-10">
          <tr className="border-b border-slate-700/60 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
            <th className="text-left px-3 py-2">Member</th>
            <th className="text-center px-3 py-2">Lvl</th>
            <th className="text-center px-3 py-2">Pool</th>
            <th className="text-center px-3 py-2">SDE Status</th>
            <th className="text-right px-3 py-2">Time to Execute</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-8 text-center text-slate-600 text-xs">
                No L3/L4 members detected — system pressure minimal
              </td>
            </tr>
          )}
          {rows.map((u, i) => {
            const isTarget = u.current_level === 4
            return (
              <tr key={u.id ?? i} className={`border-b border-slate-800/50 ${isTarget ? 'bg-red-950/15' : ''}`}>
                <td className="px-3 py-2.5">
                  <span className={`font-medium text-xs ${isTarget ? 'text-white' : 'text-slate-300'}`}>
                    @{u.username ?? u.user_username ?? '—'}
                  </span>
                  <span className="text-[10px] text-slate-600 ml-1.5">{u.name ?? ''}</span>
                </td>
                <td className="px-3 py-2.5 text-center">
                  <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-black border ${
                    isTarget
                      ? 'bg-rose-950/60 text-rose-300 border-rose-700/50'
                      : 'bg-amber-950/40 text-amber-400 border-amber-800/40'
                  } ${isTarget ? 'animate-pulse' : ''}`}>
                    L{u.current_level}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-center">
                  <span className="text-[10px] font-mono text-slate-500">
                    #{u.current_pool_id ?? '—'}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-center">
                  {isTarget ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-black bg-rose-950/60 text-rose-300 border border-rose-800/50">
                      <Crosshair className="w-2.5 h-2.5"/>TARGET LOCKED
                    </span>
                  ) : (
                    <span className="text-[10px] text-amber-500/70">Candidate</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <span className={`text-[10px] font-mono ${isTarget ? 'text-rose-400' : 'text-slate-500'}`}>
                    {isTarget ? 'Next Sunday' : '~1–2 draws'}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {rows.length > 0 && (
        <div className="px-3 py-2 border-t border-slate-700/40 flex items-center justify-between">
          <span className="text-[10px] text-rose-400/80 font-semibold">
            {l4.length} TARGET LOCKED · {l3.length} candidates
          </span>
          {l4.length >= 4 && (
            <span className="text-[9px] font-bold text-red-400 bg-red-950/50 border border-red-800/50 px-2 py-0.5 rounded-full animate-pulse">
              HIGH SDE PRESSURE
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Skeleton loader
// ─────────────────────────────────────────────────────────────────────────────
function DarkSkeleton({ className = '' }) {
  return <div className={`animate-pulse bg-slate-800 rounded-xl ${className}`}/>
}

function DarkCard({ title, icon: Icon, iconColor = 'text-slate-400', badge, action, children }) {
  return (
    <div className="bg-slate-900 border border-slate-700/50 rounded-2xl overflow-hidden shadow-lg">
      <div className="px-5 py-3.5 border-b border-slate-700/40 flex items-center gap-2">
        <Icon className={`w-4 h-4 flex-shrink-0 ${iconColor}`}/>
        <h2 className="font-semibold text-slate-200 text-sm flex-1">{title}</h2>
        {badge && <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${badge.cls}`}>{badge.label}</span>}
        {action}
      </div>
      {children}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────────────────────────────────────
export default function CommandCenter() {
  const toast = useToast()

  const [lpiData,    setLpiData]    = useState(null)
  const [aiData,     setAiData]     = useState(null)
  const [finData,    setFinData]    = useState(null)
  const [chartData,  setChartData]  = useState([])
  const [poolData,   setPoolData]   = useState(null)
  const [l3l4Users,  setL3l4Users]  = useState([])

  const [loading,    setLoading]    = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastAt,     setLastAt]     = useState(null)

  const fetchAll = useCallback(async (silent = false) => {
    silent ? setRefreshing(true) : setLoading(true)

    const [lpiR, aiR, finR, chartR, poolR, userR] = await Promise.allSettled([
      getBrain5Lpi(),
      getAiSnapshot(),
      getFinancials(),
      getChartData(14, 'day'),
      getPoolStats(),
      getAdminUsers({ status: 'Active', limit: 500 }),
    ])

    if (lpiR.status   === 'fulfilled') setLpiData(lpiR.value.data)
    if (aiR.status    === 'fulfilled') setAiData(aiR.value.data)
    if (finR.status   === 'fulfilled') setFinData(finR.value.data)
    if (chartR.status === 'fulfilled') setChartData(chartR.value.data?.data ?? [])
    if (poolR.status  === 'fulfilled') setPoolData(poolR.value.data)
    if (userR.status  === 'fulfilled') {
      const all = userR.value.data ?? []
      setL3l4Users(all.filter(u => u.current_level === 3 || u.current_level === 4))
    }

    setLoading(false)
    setRefreshing(false)
    setLastAt(new Date())
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])
  // Auto-refresh every 30 s
  useEffect(() => {
    const id = setInterval(() => fetchAll(true), 30_000)
    return () => clearInterval(id)
  }, [fetchAll])

  // ── Derived values ────────────────────────────────────────────────────────
  const lpi         = fP(lpiData?.lpi)
  const rdr         = fP(aiData?.rdr)
  const momentum    = fP(aiData?.momentum)
  const burnRate    = fP(aiData?.burn_rate ?? (fI(poolData?.active_pools_count) * 2))
  const multiplier  = fP(aiData?.multiplier ?? 1.0)
  const scenario    = aiData?.scenario ?? ''

  const isFlashFlood = rdr > 70 && momentum > 0
  const condensationActive = lpiData?.pool_type_decision?.p4?.active ?? false

  const waitlistCount = fI(finData?.waitlist_count ?? lpiData?.total_active)
  const pools = poolData?.pools ?? []

  return (
    <div className={`p-6 space-y-6 transition-all duration-500 ${
      isFlashFlood ? 'ring-2 ring-amber-500/40 rounded-2xl' : ''
    }`}>

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2.5">
            <div className={`p-2 rounded-xl ${isFlashFlood ? 'bg-amber-500/20 animate-pulse' : 'bg-violet-900/40'}`}>
              <Terminal className={`w-5 h-5 ${isFlashFlood ? 'text-amber-400' : 'text-violet-400'}`}/>
            </div>
            Quantitative Command Center
            {isFlashFlood && (
              <span className="text-[10px] font-black px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse uppercase tracking-widest ml-1">
                ⚡ FLASH FLOOD
              </span>
            )}
          </h1>
          <p className="text-sm text-slate-500 mt-0.5 ml-11">
            {lastAt ? `Synced ${lastAt.toLocaleTimeString()}` : 'Connecting…'}
            <span className="ml-2 text-[10px] text-slate-600">Auto-refresh 30 s</span>
          </p>
        </div>
        <button
          onClick={() => fetchAll(true)} disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded-xl text-sm font-medium transition disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`}/>
          Refresh All
        </button>
      </div>

      {/* ══ MODULE 1: TELEMETRY HUD ══════════════════════════════════════════ */}
      <div className="grid grid-cols-12 gap-5">

        {/* LPI Thermometer — tall left column */}
        <div className="col-span-2">
          <DarkCard title="LPI" icon={Activity} iconColor="text-violet-400"
            badge={{ label: 'LIVE', cls: 'bg-emerald-900/60 text-emerald-400 border border-emerald-700/50' }}>
            <div className="p-4 flex flex-col items-center justify-center">
              {loading ? (
                <DarkSkeleton className="h-56 w-12"/>
              ) : (
                <LpiThermometer lpi={lpi}/>
              )}
            </div>
          </DarkCard>
        </div>

        {/* Breathing Chart — center */}
        <div className="col-span-6">
          <DarkCard title="Velocity vs Burn Rate — The Breathing Chart"
            icon={Waves ?? Activity} iconColor="text-blue-400"
            badge={burnRate > 0 ? {
              label: `Burn: ${burnRate}/wk`,
              cls: 'bg-red-950/60 text-red-400 border border-red-800/50'
            } : null}
          >
            <div className="px-4 pt-3 pb-4">
              {loading ? <DarkSkeleton className="h-40"/> : (
                <VelocityBurnChart chartData={chartData} burnRate={burnRate}/>
              )}
              <div className="mt-2 flex items-center gap-4 text-[10px] text-slate-500">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-0.5 bg-blue-500 inline-block rounded"/>Blue = Incoming Velocity
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-4 h-0.5 bg-red-500 inline-block" style={{ borderTop: '1px dashed #ef4444' }}/>Red dashed = Burn Rate
                </span>
              </div>
            </div>
          </DarkCard>
        </div>

        {/* Liability / Float Radar — right column */}
        <div className="col-span-4">
          <DarkCard title="Float vs Liability Radar" icon={IndianRupee} iconColor="text-emerald-400">
            <div className="px-5 py-4">
              {loading ? (
                <div className="space-y-3">
                  {[1,2,3].map(i => <DarkSkeleton key={i} className="h-8"/>)}
                </div>
              ) : <LiabilityFloatBar financials={finData}/>}

              {!loading && aiData && (
                <div className="mt-4 pt-3 border-t border-slate-800 grid grid-cols-3 gap-2">
                  {[
                    { l: 'Velocity', v: `${fP(aiData.velocity).toFixed(1)}/wk`, c: 'text-blue-400' },
                    { l: 'Multiplier', v: `${multiplier.toFixed(2)}×`, c: multiplier > 1.5 ? 'text-emerald-400' : 'text-amber-400' },
                    { l: 'Scenario', v: scenario || 'NORMAL', c: isFlashFlood ? 'text-amber-300' : 'text-slate-400' },
                  ].map(({ l, v, c }) => (
                    <div key={l} className="text-center">
                      <p className="text-[9px] text-slate-600 uppercase tracking-wide">{l}</p>
                      <p className={`text-xs font-bold mt-0.5 ${c}`}>{v}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </DarkCard>
        </div>
      </div>

      {/* ══ MODULE 2-A: BRAIN 1 & 4 TOPOLOGY MAP ════════════════════════════ */}
      <DarkCard title="Brain 1 & 4 — Hydraulic Topology Map"
        icon={Network ?? Layers} iconColor="text-blue-400"
        badge={condensationActive ? { label: 'CONDENSATION', cls: 'bg-red-950/60 text-red-400 border border-red-800/50 animate-pulse' } : null}
      >
        <div className="px-4 py-3">
          {loading ? <DarkSkeleton className="h-48"/> : (
            <TopologyMap
              pools={pools}
              waitlistCount={waitlistCount}
              multiplier={multiplier}
              condensationActive={condensationActive}
            />
          )}
          <div className="mt-1 flex items-center gap-6 text-[9px] text-slate-600">
            <span>● Full pool (green)</span>
            <span>● Near-full (blue)</span>
            <span>● Partial (amber)</span>
            <span>● Low fill (red)</span>
            <span className="ml-auto text-rose-600">● = L4 flagged</span>
          </div>
        </div>
      </DarkCard>

      {/* ══ MODULE 2-B + 2-C ═════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-5">

        {/* Brain 2 & 3 Scatterplot */}
        <DarkCard title="Brain 2 & 3 — Hype Scatterplot"
          icon={Radio} iconColor={isFlashFlood ? 'text-amber-400' : 'text-violet-400'}
          badge={isFlashFlood ? { label: '⚡ FLASH FLOOD', cls: 'bg-amber-950/60 text-amber-300 border border-amber-700/50 animate-pulse' } : null}
        >
          <div className="p-3">
            {loading ? <DarkSkeleton className="h-52"/> : (
              <BrainScatterplot rdr={rdr} momentum={momentum} scenario={scenario}/>
            )}
            {!loading && (
              <div className="mt-1 grid grid-cols-2 gap-2 text-center">
                <div className="bg-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500">RDR</p>
                  <p className="text-sm font-bold text-blue-400 tabular-nums">{fP(rdr).toFixed(1)}%</p>
                </div>
                <div className="bg-slate-800 rounded-lg p-2">
                  <p className="text-[9px] text-slate-500">Momentum</p>
                  <p className={`text-sm font-bold tabular-nums ${momentum >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {momentum >= 0 ? '+' : ''}{fP(momentum).toFixed(2)}
                  </p>
                </div>
              </div>
            )}
          </div>
        </DarkCard>

        {/* Brain 5 Anti-Maturity Grid */}
        <DarkCard title="Brain 5 — Anti-Maturity Execution Grid"
          icon={Crosshair} iconColor="text-rose-400"
          badge={l3l4Users.filter(u => u.current_level === 4).length > 0 ? {
            label: `${l3l4Users.filter(u => u.current_level === 4).length} TARGETED`,
            cls: 'bg-rose-950/60 text-rose-400 border border-rose-800/50',
          } : null}
        >
          <div>
            {loading ? (
              <div className="p-4 space-y-2">
                {[1,2,3,4].map(i => <DarkSkeleton key={i} className="h-8"/>)}
              </div>
            ) : <AntiMaturityGrid users={l3l4Users}/>}
          </div>
        </DarkCard>
      </div>

      {/* ── AI Brain Status Footer ────────────────────────────────────────── */}
      {!loading && lpiData && (
        <div className="grid grid-cols-5 gap-3">
          {[
            { l: 'LPI', v: `${lpi.toFixed(1)}%`, sub: 'Pressure Index',      c: lpi > 50 ? 'text-red-400' : lpi > 25 ? 'text-orange-400' : 'text-emerald-400' },
            { l: 'L4 Targets', v: fI(lpiData.l4_flagged_count), sub: 'Queued for SDE', c: fI(lpiData.l4_flagged_count) > 0 ? 'text-rose-400' : 'text-slate-500' },
            { l: 'L3 Candidates', v: fI(lpiData.l3_count ?? l3l4Users.filter(u=>u.current_level===3).length), sub: 'Next pipeline', c: 'text-amber-400' },
            { l: 'SDE Demand', v: `${fP(lpiData.sde_demand_pct).toFixed(1)}%`, sub: 'Clearance Demand', c: fP(lpiData.sde_demand_pct) > 50 ? 'text-red-400' : 'text-slate-400' },
            { l: 'Active Pools', v: fI(poolData?.active_pools_count), sub: 'Execution Engines', c: 'text-blue-400' },
          ].map(({ l, v, sub, c }) => (
            <div key={l} className="bg-slate-900 border border-slate-700/50 rounded-xl p-3 text-center">
              <p className="text-[9px] text-slate-500 uppercase tracking-widest mb-1">{l}</p>
              <p className={`text-lg font-black tabular-nums ${c}`}>{v}</p>
              <p className="text-[9px] text-slate-600 mt-0.5">{sub}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
