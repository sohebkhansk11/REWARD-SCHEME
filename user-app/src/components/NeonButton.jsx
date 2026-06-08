import { motion } from 'framer-motion'

export default function NeonButton({ children, onClick, disabled, variant = 'primary', className = '', type = 'button' }) {
  if (variant === 'ghost') {
    return (
      <motion.button
        type={type}
        onClick={onClick}
        disabled={disabled}
        whileTap={{ scale: 0.97 }}
        className={`rounded-2xl px-6 py-3.5 font-bold tracking-wider border border-white/10 text-white/70 hover:text-white hover:border-white/20 transition-colors disabled:opacity-40 ${className}`}
      >
        {children}
      </motion.button>
    )
  }

  return (
    <motion.button
      type={type}
      onClick={onClick}
      disabled={disabled}
      whileTap={{ scale: 0.96 }}
      whileHover={{ scale: 1.01 }}
      className={`btn-primary px-6 py-3.5 w-full disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      style={{ WebkitTapHighlightColor: 'transparent' }}
    >
      {children}
    </motion.button>
  )
}
