import { labelClasses } from './tokens'

export type SensitivityLabel = 'public' | 'internal' | 'restricted'

/** Sensitivity label chip. Visible on every citation and every policy row. */
export function RiskTag({ label, className = '' }: { label: SensitivityLabel; className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${labelClasses[label]} ${className}`}
      data-testid={`label-${label}`}
    >
      {label}
    </span>
  )
}
