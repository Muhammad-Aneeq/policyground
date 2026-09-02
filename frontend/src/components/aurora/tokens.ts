/** Aurora design tokens (spec 00 A2), exposed for the places that need raw values. */
export const tokens = {
  navy: '#0B1E3B',
  navyDeep: '#050F1E',
  emerald: '#10B981',
  amber: '#F59E0B',
  rose: '#F43F5E',
  glass: 'rgba(255, 255, 255, 0.04)',
} as const

/**
 * Per-label styling. Sensitivity is a first-class visual property here: a controller reading an
 * answer built on restricted material should be able to see that at a glance, without hunting
 * through the sources panel.
 */
export const labelClasses = {
  public: 'border-sky-400/40 bg-sky-400/10 text-sky-300',
  internal: 'border-amber-400/40 bg-amber-400/10 text-amber-300',
  restricted: 'border-rose-400/40 bg-rose-400/10 text-rose-300',
} as const

/**
 * Answer and refusal must never share a surface treatment (spec 08 section 9: refusals are
 * "styled distinctly, never like a normal answer"). Emerald reads as evidence; amber reads as
 * "we did not find this". They are kept adjacent here so nobody can change one without seeing
 * the other.
 */
export const outcomeClasses = {
  answer: 'border-emerald-brand/30 bg-emerald-brand/[0.06]',
  refusal: 'border-amber-400/40 bg-amber-400/[0.08]',
} as const

export const stepClasses = {
  retrieve: 'border-sky-400/40 bg-sky-400/10 text-sky-300',
  assess_sufficiency: 'border-violet-400/40 bg-violet-400/10 text-violet-300',
  compose: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300',
  citation_check: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300',
  refuse: 'border-amber-400/40 bg-amber-400/10 text-amber-300',
} as const
