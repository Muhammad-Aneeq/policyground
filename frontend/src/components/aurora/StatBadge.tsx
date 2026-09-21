import type { ReactNode } from 'react'

/** Small labelled pill for a single fact. */
export function StatBadge({
  label,
  value,
  tone = 'neutral',
  title,
}: {
  label: string
  value: ReactNode
  tone?: 'neutral' | 'good' | 'warn' | 'bad'
  title?: string
}) {
  const tones = {
    neutral: 'border-line bg-surface-sunken text-ink-muted',
    good: 'border-accent-line bg-accent-wash text-accent-fg',
    warn: 'border-caution-line bg-caution-wash text-caution-fg',
    bad: 'border-danger-line bg-danger-wash text-danger-fg',
  } as const

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${tones[tone]}`}
    >
      <span className="opacity-75">{label}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </span>
  )
}
