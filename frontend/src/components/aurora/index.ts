/**
 * Aurora UI — the shared design system, implemented locally for this standalone repo
 * (PLAN.md D-002). One import line yields the shared look, which is spec 00 A2's acceptance
 * criterion.
 */

export { Card } from './Card'
export { ConfidencePill } from './ConfidencePill'
export { EmptyState } from './EmptyState'
export { EvidencePanel } from './EvidencePanel'
export { MetricTile } from './MetricTile'
export { RiskTag } from './RiskTag'
export type { SensitivityLabel } from './RiskTag'
export { StatBadge } from './StatBadge'
export { SyntheticDataBanner } from './SyntheticDataBanner'
export { TraceTimeline } from './TraceTimeline'
export type { TraceStep } from './TraceTimeline'
export { labelClasses, outcomeClasses, stepClasses, tokens } from './tokens'
