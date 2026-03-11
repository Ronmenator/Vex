import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        vex: {
          bg:       '#0a0a0f',
          surface:  '#13131a',
          surface2: '#1a1a24',
          border:   '#2a2a3a',
          text:     '#e0e0e8',
          muted:    '#8888a0',
          accent:   '#7c5cfc',
          accent2:  '#5c9cfc',
          green:    '#4cda6a',
          yellow:   '#f5c842',
          red:      '#fc5c5c',
        },
      },
      keyframes: {
        bounce: {
          '0%, 80%, 100%': { transform: 'translateY(0)' },
          '40%':            { transform: 'translateY(-8px)' },
        },
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0.5' },
        },
      },
      animation: {
        'vex-bounce': 'bounce 1.2s ease-in-out infinite',
        'vex-pulse':  'pulse 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
export default config
