/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        // One geometric sans for the interface, one monospace for every numeral.
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        paper: '#faf9f7',
        panel: '#ffffff',
        line: { DEFAULT: '#e3e0d8', strong: '#cfcbc0' },
        ink: { DEFAULT: '#1a1a18', soft: '#4a4740', mute: '#78756c' },
        subtle: '#f3f1ec',
        active: '#e9e5dc',
        // Semantic accents, chosen for contrast on paper rather than on black.
        accent: '#1f6f52',
        info: '#2b5d8a',
        warn: '#8a6a12',
        danger: '#a8321f',
        // Band palette derived from official PSI band semantics.
        band: {
          good: '#2f6b4a',
          moderate: '#8a6a12',
          unhealthy: '#b4530f',
          veryunhealthy: '#9b2c1a',
          hazardous: '#6d1a12',
        },
      },
    },
  },
  plugins: [],
}
