/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        neon: {
          cyan:   '#00f0ff',
          purple: '#bf00ff',
          blue:   '#0070ff',
          green:  '#00ff88',
          pink:   '#ff00aa',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Consolas', 'monospace'],
      },
      animation: {
        'pulse-glow': 'pulseGlow 2.5s ease-in-out infinite',
        'float':      'float 6s ease-in-out infinite',
      },
      keyframes: {
        pulseGlow: {
          '0%,100%': { boxShadow: '0 0 10px rgba(0,240,255,0.3), 0 0 20px rgba(0,240,255,0.1)' },
          '50%':     { boxShadow: '0 0 25px rgba(0,240,255,0.7), 0 0 50px rgba(0,240,255,0.3)' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0px)' },
          '50%':     { transform: 'translateY(-8px)' },
        },
      },
    },
  },
  plugins: [],
}

