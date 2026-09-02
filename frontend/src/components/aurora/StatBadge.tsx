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
    neutral: 'border-white/15 bg-white/5 text-slate-300',
    good: 'border-emerald-brand/40 bg-emerald-brand/10 text-emerald-300',
    warn: 'border-amber-400/40 bg-amber-400/10 text-amber-300',
    bad: 'border-rose-400/40 bg-rose-400/10 text-rose-300',
  } as const

  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${tones[tone]}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </span>
  )
}
