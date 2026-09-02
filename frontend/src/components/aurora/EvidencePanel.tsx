import type { ReactNode } from 'react'
import { Card } from './Card'

/** Container for the sources side panel (spec 00 A2). */
export function EvidencePanel({
  title,
  count,
  children,
  footer,
}: {
  title: string
  count?: number
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <Card as="aside" className="flex h-full flex-col gap-3 p-4">
      <header className="flex items-baseline justify-between">
        <h2 className="font-display text-sm uppercase tracking-wide text-slate-400">{title}</h2>
        {count === undefined ? null : (
          <span className="text-xs tabular-nums text-slate-500">{count}</span>
        )}
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto">{children}</div>
      {footer ? <footer className="border-t border-white/10 pt-3">{footer}</footer> : null}
    </Card>
  )
}
