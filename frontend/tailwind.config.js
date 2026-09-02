/** Aurora tokens per spec 00 A2: dark navy #0B1E3B, emerald #10B981, frosted glass. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: '#0B1E3B', deep: '#050F1E', soft: '#12294B' },
        emerald: { brand: '#10B981' },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: { glass: '0 8px 32px rgba(0, 0, 0, 0.35)' },
    },
  },
  plugins: [],
}
