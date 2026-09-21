/**
 * Sufficiency score rendered against its refusal threshold (spec 00 A2: "0-1 -> color+label").
 *
 * The threshold is drawn, not just described. A bare "0.42" means nothing to a reader; "0.42,
 * below the 0.45 refusal threshold" explains why the system refused, which is the whole point of
 * a product whose headline behaviour is declining to answer.
 */
export function ConfidencePill({
  score,
  threshold,
  className = '',
}: {
  score: number
  threshold: number
  className?: string
}) {
  const above = score >= threshold
  const label = above ? (score >= threshold + 0.25 ? 'strong' : 'sufficient') : 'below threshold'
  const tone = above
    ? score >= threshold + 0.25
      ? 'border-accent-line bg-accent-wash text-accent-fg'
      : 'border-info-line bg-info-wash text-info-fg'
    : 'border-caution-line bg-caution-wash text-caution-fg'

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs ${tone} ${className}`}
      title={`Evidence sufficiency ${score.toFixed(3)} against a refusal threshold of ${threshold}`}
      data-testid="confidence-pill"
    >
      <span className="font-semibold tabular-nums">{score.toFixed(2)}</span>
      <span className="opacity-80">{label}</span>
      <span className="opacity-55">/ {threshold.toFixed(2)}</span>
    </span>
  )
}
