import { motion } from 'framer-motion'

export default function GlassCard({ children, className = '', neon = 'cyan', animate = false }) {
  const ringClass = neon === 'purple' ? 'neon-ring-purple' : neon === 'none' ? '' : 'neon-ring-cyan'

  return (
    <motion.div
      initial={animate ? { opacity: 0, y: 16 } : false}
      animate={animate ? { opacity: 1, y: 0 } : false}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className={`glass-card ${ringClass} ${className}`}
    >
      {children}
    </motion.div>
  )
}
