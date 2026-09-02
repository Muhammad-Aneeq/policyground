/**
 * Spec 00 A1 makes this mandatory on every project. It appears on every screen rather than only
 * the landing page: a screenshot of the Admin dashboard should carry the caveat too, because a
 * screenshot is how most people will encounter this.
 */
export function SyntheticDataBanner({ degraded = false }: { degraded?: boolean }) {
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-amber-400/20 bg-amber-400/[0.07] px-4 py-1.5 text-xs text-amber-200/90"
      data-testid="synthetic-banner"
    >
      <span>
        <span aria-hidden="true">⚠️</span> All policy content is <strong>synthetic</strong>, authored
        for this project. It is not any organisation&rsquo;s real policy manual.
      </span>
      {degraded ? (
        <span className="text-amber-300/70" data-testid="degraded-badge">
          · No model credential: retrieval uses a deterministic hash embedder and compose is
          extractive. Citations, label filtering and refusal are unaffected.
        </span>
      ) : null}
    </div>
  )
}
