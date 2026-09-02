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
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-white/10 px-6 py-10 text-center">
      <div className="mb-2 text-2xl text-slate-600">{icon}</div>
      <div className="font-display text-slate-300">{title}</div>
      {children ? <div className="mt-1 max-w-md text-sm text-slate-500">{children}</div> : null}
    </div>
  )
}
