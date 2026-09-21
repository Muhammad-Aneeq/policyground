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
        <h2 className="pg-eyebrow">{title}</h2>
        {count === undefined ? null : (
          <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs font-semibold tabular-nums text-ink-muted">
            {count}
          </span>
        )}
      </header>
      <div className="pg-scroll flex-1 space-y-3 overflow-y-auto">{children}</div>
      {footer ? <footer className="border-t border-line pt-3">{footer}</footer> : null}
    </Card>
  )
}
