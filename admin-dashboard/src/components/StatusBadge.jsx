const VARIANTS = {
  Active:                  'bg-emerald-100 text-emerald-700 ring-emerald-200',
  Waitlist:                'bg-amber-100   text-amber-700   ring-amber-200',
  Eliminated:              'bg-red-100     text-red-700     ring-red-200',
  Eliminated_Won:          'bg-purple-100  text-purple-700  ring-purple-200',
  Full:                    'bg-blue-100    text-blue-700    ring-blue-200',
  Waiting:                 'bg-slate-100   text-slate-600   ring-slate-200',
  Paid:                    'bg-emerald-100 text-emerald-700 ring-emerald-200',
  Unpaid:                  'bg-red-100     text-red-600     ring-red-200',
  Burned:                  'bg-slate-100   text-slate-500   ring-slate-200',
  // Pool lifecycle statuses
  Paused_Awaiting_Members: 'bg-orange-100  text-orange-700  ring-orange-200',
  Merged_Dissolved:        'bg-slate-200   text-slate-500   ring-slate-300',
}

// Human-readable label overrides (for multi-word status names)
const LABELS = {
  Paused_Awaiting_Members: '⏸ Paused',
  Merged_Dissolved:        '🔀 Dissolved',
}

export default function StatusBadge({ status }) {
  const cls   = VARIANTS[status] ?? 'bg-slate-100 text-slate-600 ring-slate-200'
  const label = LABELS[status]   ?? status?.replace(/_/g, ' ')
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ring-1 ${cls}`}>
      {label}
    </span>
  )
}
