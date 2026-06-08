const PREFIXES = [
  'NEXUS','CIPHER','VOID','NOVA','ZETA','ALPHA','OMEGA','GHOST',
  'DELTA','FLUX','PRISM','ECHO','APEX','VECTOR','PHANTOM','QUASAR',
  'NEBULA','AXIOM','VERTEX','VORTEX','PYXIS','ORION','HELIX','RAVEN',
]
const SUFFIXES = [
  'X','Z','PRIME','CORE','SYS','NET','ARK','NODE','HEX','BIT',
  'RAW','PRO','MAX','ZERO','ONE','IX','Ω','λ',
]

export function generateUsername() {
  const p = PREFIXES[Math.floor(Math.random() * PREFIXES.length)]
  const s = SUFFIXES[Math.floor(Math.random() * SUFFIXES.length)]
  const n = Math.floor(Math.random() * 100).toString().padStart(2, '0')
  return `${p}_${s}${n}`
}

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'

export function typewriterReveal(finalText, setDisplay) {
  return new Promise(resolve => {
    const total = finalText.length * 6
    let step = 0
    const id = setInterval(() => {
      step++
      const revealed = Math.floor((step / total) * finalText.length)
      const display = finalText
        .split('')
        .map((ch, i) => (i < revealed ? ch : CHARS[Math.floor(Math.random() * CHARS.length)]))
        .join('')
      setDisplay(display)
      if (step >= total) {
        clearInterval(id)
        setDisplay(finalText)
        resolve()
      }
    }, 30)
  })
}
