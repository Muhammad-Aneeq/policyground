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
    neutral: 'text-slate-100',
    good: 'text-emerald-300',
    warn: 'text-amber-300',
    bad: 'text-rose-300',
  } as const

  return (
    <div className="aurora-glass p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 font-display text-2xl tabular-nums ${accents[tone]}`}>{value}</div>
      {caption ? <div className="mt-1 text-xs text-slate-400">{caption}</div> : null}
    </div>
  )
}
