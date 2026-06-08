export default function NeonInput({ label, sublabel, className = '', ...props }) {
  return (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-xs font-mono font-semibold text-white/40 uppercase tracking-widest">
          {label}
        </label>
      )}
      <input className={`neon-input ${className}`} {...props} />
      {sublabel && <p className="text-xs text-white/25 pl-1">{sublabel}</p>}
    </div>
  )
}
