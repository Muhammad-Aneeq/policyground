import { Link, useParams, useSearchParams } from 'react-router-dom'
import { usePolicies, usePolicy } from '../api/client'
import { ApiError } from '../api/client'
import type { Role } from '../api/types'
import { HighlightedPassage } from '../components/HighlightedPassage'
import { Card, EmptyState, RiskTag, StatBadge } from '../components/aurora'

/**
 * Screen 2 (spec 08 section 9): the full policy, with the cited passage highlighted.
 *
 * This is the **second governance surface**. The policy list here is filtered by the same rule as
 * retrieval, and a policy above the session's clearance returns 404 — indistinguishable from one
 * that does not exist. The screen shows that state honestly rather than pretending the document is
 * missing: it says the role cannot see it, which is true and is the thing worth demonstrating.
 */
export function SourceViewer({ role }: { role: Role }) {
  const { policyId } = useParams<{ policyId: string }>()
  const [searchParams] = useSearchParams()
  const highlightChunk = searchParams.get('highlight')

  const policies = usePolicies(role)
  const policy = usePolicy(policyId, role)

  const section = highlightChunk
    ? policy.data?.sections.find((candidate) => candidate.chunk_id === highlightChunk)
    : undefined

  const notPermitted = policy.error instanceof ApiError && policy.error.status === 404

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <Card as="aside" className="lg:sticky lg:top-4 lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto">
        <header className="mb-3 flex items-baseline justify-between">
          <h2 className="pg-eyebrow">Policies</h2>
          <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-xs font-semibold tabular-nums text-ink-muted">
            {policies.data?.visible_count ?? '—'}
          </span>
        </header>

        {policies.data && policies.data.hidden_count > 0 ? (
          <p className="mb-3 rounded-lg border border-caution-line bg-caution-wash px-2.5 py-1.5 text-[11px] text-caution-fg">
            {policies.data.hidden_count} polic
            {policies.data.hidden_count === 1 ? 'y is' : 'ies are'} hidden at the{' '}
            <strong>{role}</strong> role ({policies.data.hidden_labels.join(', ')}).
          </p>
        ) : null}

        <nav className="space-y-1">
          {policies.data?.policies.map((summary) => (
            <Link
              key={summary.policy_id}
              to={`/sources/${summary.policy_id}`}
              data-testid="policy-link"
              className={`block rounded-lg border px-2.5 py-2 transition-colors ${
                summary.policy_id === policyId
                  ? 'border-accent-line bg-accent-wash'
                  : 'border-transparent hover:border-line hover:bg-surface-sunken'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[11px] text-ink-soft">{summary.policy_id}</span>
                <RiskTag label={summary.label} />
              </div>
              <div className="mt-0.5 text-xs font-medium leading-snug text-ink">{summary.title}</div>
            </Link>
          ))}
        </nav>
      </Card>

      <div>
        {!policyId ? (
          <EmptyState title="Pick a policy" icon="§">
            The manual is 30 synthetic accounting policies. What you can open here is filtered by
            the same rule that filters retrieval.
          </EmptyState>
        ) : notPermitted ? (
          <Card className="border-caution-line bg-caution-wash" data-testid="not-permitted">
            <h2 className="font-display font-semibold text-caution-fg">Not available at this role</h2>
            <p className="mt-2 text-sm text-caution-fg/85">
              <span className="font-mono">{policyId}</span> is either restricted above the{' '}
              <strong>{role}</strong> role or does not exist. The API returns the same response for
              both, deliberately — telling you which would confirm that a restricted document
              exists.
            </p>
            <p className="mt-2 text-sm text-caution-fg/70">
              Switch role in the header to see the difference live.
            </p>
          </Card>
        ) : policy.isLoading ? (
          <Card className="text-sm text-ink-soft">Loading…</Card>
        ) : policy.data ? (
          <Card as="article">
            <header className="mb-4 border-b border-line pb-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-ink-soft">{policy.data.policy_id}</span>
                <RiskTag label={policy.data.label} />
                <StatBadge label="version" value={policy.data.version} />
                <StatBadge label="owner" value={policy.data.owner} />
                <StatBadge label="effective" value={policy.data.effective_date} />
              </div>
              <h1 className="mt-2 font-display text-xl font-semibold text-ink">{policy.data.title}</h1>
              {section ? (
                <p className="mt-2 text-xs font-medium text-accent-fg" data-testid="highlight-caption">
                  Highlighting <span className="font-mono">{section.section_path}</span>
                </p>
              ) : null}
            </header>

            <HighlightedPassage
              markdown={policy.data.markdown}
              start={section?.start}
              end={section?.end}
            />
          </Card>
        ) : null}
      </div>
    </div>
  )
}
