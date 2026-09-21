import type { ReactNode } from 'react'

/** Headline number with a caption. Used across the admin dashboard. */
export function MetricTile({
  label,
  value,
  caption,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  caption?: ReactNode
  tone?: 'neutral' | 'good' | 'warn' | 'bad'
}) {
  const accents = {
    neutral: 'text-ink',
    good: 'text-accent-fg',
    warn: 'text-caution-fg',
    bad: 'text-danger-fg',
  } as const

  return (
    <div className="pg-card p-4">
      <div className="pg-eyebrow">{label}</div>
      <div className={`mt-1.5 font-display text-2xl tabular-nums ${accents[tone]}`}>{value}</div>
      {caption ? <div className="mt-1 text-xs text-ink-muted">{caption}</div> : null}
    </div>
  )
}
