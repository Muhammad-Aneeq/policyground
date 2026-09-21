/**
 * PolicyGround theme — a light, paper-like surface for a document product.
 *
 * Every colour below is **semantic, not descriptive**: components say `bg-surface`, `text-ink-muted`
 * and `border-caution-line`, never `bg-white` or `text-amber-700`. That is what made replacing the
 * previous dark theme a change to this one file plus the token map, rather than a hunt through
 * forty components for every hard-coded slate.
 *
 * The three outcome colours are load-bearing and must stay visually distinct at a glance, because
 * the product's core claim is that you can tell these apart without reading:
 *
 *   accent  (indigo) — an answer, and the evidence supporting it
 *   caution (amber)  — a refusal: "this is not in the manual"
 *   danger  (rose)   — restricted material, and the label filter withholding it
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Warm neutrals. A pure #FFF page under a #FFF card leaves the card invisible; the
        // canvas is deliberately a step darker than the surfaces sitting on it.
        canvas: '#FAFAF9',
        surface: { DEFAULT: '#FFFFFF', sunken: '#F5F5F4', raised: '#FFFFFF' },
        line: { DEFAULT: '#E7E5E4', strong: '#D6D3D1' },
        ink: { DEFAULT: '#1C1917', muted: '#57534E', soft: '#8A8581', faint: '#B6B2AE' },

        accent: {
          DEFAULT: '#4F46E5',
          fg: '#4338CA',
          wash: '#EEF2FF',
          line: '#C7D2FE',
        },
        caution: {
          DEFAULT: '#B45309',
          fg: '#92400E',
          wash: '#FFFBEB',
          line: '#FDE68A',
        },
        danger: {
          DEFAULT: '#BE123C',
          fg: '#9F1239',
          wash: '#FFF1F2',
          line: '#FECDD3',
        },
        info: {
          DEFAULT: '#0284C7',
          fg: '#0369A1',
          wash: '#F0F9FF',
          line: '#BAE6FD',
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        // Two small, tight shadows rather than one large soft one: on a light canvas a wide
        // blur reads as haze, where a short offset reads as a sheet of paper lifted slightly.
        card: '0 1px 2px rgba(28, 25, 23, 0.04), 0 1px 3px rgba(28, 25, 23, 0.06)',
        lift: '0 2px 4px rgba(28, 25, 23, 0.04), 0 4px 12px rgba(28, 25, 23, 0.08)',
      },
    },
  },
  plugins: [],
}
