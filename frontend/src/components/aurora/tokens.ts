/** Design tokens, exposed for the places that need raw values rather than utility classes. */
export const tokens = {
  canvas: '#FAFAF9',
  surface: '#FFFFFF',
  line: '#E7E5E4',
  ink: '#1C1917',
  accent: '#4F46E5',
  caution: '#B45309',
  danger: '#BE123C',
} as const

/**
 * Per-label styling. Sensitivity is a first-class visual property here: a controller reading an
 * answer built on restricted material should be able to see that at a glance, without hunting
 * through the sources panel.
 *
 * The three are ordered by how much they should alarm you, and they are coloured that way:
 * `public` is quiet blue, `internal` is a neutral stone, `restricted` is the same rose used
 * nowhere else in the interface.
 */
export const labelClasses = {
  public: 'border-info-line bg-info-wash text-info-fg',
  internal: 'border-line-strong bg-surface-sunken text-ink-muted',
  restricted: 'border-danger-line bg-danger-wash text-danger-fg',
} as const

/**
 * Answer and refusal must never share a surface treatment (spec 08 section 9: refusals are
 * "styled distinctly, never like a normal answer").
 *
 * On the previous dark theme the pair was emerald vs amber. On a light canvas that contrast
 * collapses — two pale tints on white read as the same card — so the answer keeps a white
 * surface with an accent edge, while the refusal takes a *tinted* surface. The difference is
 * now surface-level rather than border-level, which survives being seen from across a room or
 * in a compressed screenshot.
 *
 * They are kept adjacent so nobody can change one without seeing the other.
 */
export const outcomeClasses = {
  answer: 'border-line bg-surface',
  refusal: 'border-caution-line bg-caution-wash',
} as const

export const stepClasses = {
  retrieve: 'border-info-line bg-info-wash text-info-fg',
  assess_sufficiency: 'border-accent-line bg-accent-wash text-accent-fg',
  compose: 'border-accent-line bg-accent-wash text-accent-fg',
  citation_check: 'border-accent-line bg-accent-wash text-accent-fg',
  refuse: 'border-caution-line bg-caution-wash text-caution-fg',
} as const
