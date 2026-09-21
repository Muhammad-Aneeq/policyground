import type { ReactNode } from 'react'

export function EmptyState({
  title,
  children,
  icon = '·',
}: {
  title: string
  children?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong bg-surface-sunken/50 px-6 py-10 text-center">
      <div className="mb-2 font-display text-2xl text-ink-faint">{icon}</div>
      <div className="font-display text-ink">{title}</div>
      {children ? <div className="mt-1 max-w-md text-sm text-ink-muted">{children}</div> : null}
    </div>
  )
}
