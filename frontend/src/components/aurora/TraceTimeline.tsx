import { stepClasses } from './tokens'

export type TraceStep = { node: string; detail: string }

/**
 * The graph run, step by step (spec 00 A2 lists TraceTimeline as a shared component).
 *
 * This is what makes the governance visible rather than merely claimed: a reader can see that
 * `citation_check` ran and how many claims it removed, or that `refuse` fired before `compose`
 * was ever called.
 */
export function TraceTimeline({ steps }: { steps: TraceStep[] }) {
  if (steps.length === 0) return null

  return (
    <ol className="space-y-2" data-testid="trace-timeline">
      {steps.map((step, index) => (
        <li key={`${step.node}-${index}`} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span
              className={`mt-1 h-2 w-2 shrink-0 rounded-full border ${
                stepClasses[step.node as keyof typeof stepClasses] ?? 'border-white/20 bg-white/10'
              }`}
            />
            {index < steps.length - 1 ? <span className="w-px flex-1 bg-white/10" /> : null}
          </div>
          <div className="pb-2">
            <div className="font-mono text-xs text-slate-300">{step.node}</div>
            <div className="text-xs text-slate-500">{step.detail}</div>
          </div>
        </li>
      ))}
    </ol>
  )
}
