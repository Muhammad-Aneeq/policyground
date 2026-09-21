import { Link } from 'react-router-dom'
import type { Refusal, Role } from '../api/types'
import { Card, ConfidencePill, StatBadge } from './aurora'

const REASON_TEXT: Record<Refusal['reason'], string> = {
  insufficient_evidence:
    'The policies that came back do not cover this closely enough to answer from.',
  no_surviving_claims:
    'Passages were retrieved, but no claim could be supported by them, so nothing was rendered.',
  empty_retrieval: 'Nothing in the policy manual matched this question at all.',
}

/**
 * A refusal, styled so it cannot be mistaken for an answer (spec 08 section 9).
 *
 * The separation is deliberate and total: a *tinted* amber surface rather than the answer's white
 * sheet with an accent edge, a "Not found" heading rather than an "Answer" chip, and near-misses
 * presented as *places to look*, never as citations. It carries no `data-testid="answer-card"`,
 * and a test asserts that a refusal renders no answer-shaped container at all — the rule expressed
 * as an assertion rather than a convention.
 *
 * Structurally it could not render an answer even if someone tried: the `Refusal` type has no
 * `claims` field to read, so reaching for one is a compile error.
 */
export function RefusalCard({ refusal, role }: { refusal: Refusal; role: Role }) {
  const withheld = refusal.trace.withheld_count

  return (
    <Card
      className="border-caution-line bg-caution-wash"
      data-testid="refusal-card"
      role="status"
      aria-label="Refusal: not found in the policies"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className="rounded bg-caution px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white"
          data-testid="refusal-chip"
        >
          Not found in the policies
        </span>
        <ConfidencePill score={refusal.trace.sufficiency} threshold={refusal.trace.threshold} />
        {withheld > 0 ? (
          <StatBadge
            label="withheld at this role"
            value={withheld}
            tone="warn"
            title="Passages matched but were removed by the label filter"
          />
        ) : null}
      </div>

      <p className="font-medium text-caution-fg">{refusal.message}</p>
      <p className="mt-2 text-sm text-caution-fg/80">{REASON_TEXT[refusal.reason]}</p>

      {withheld > 0 ? (
        <p className="mt-2 text-sm text-caution-fg/80" data-testid="withheld-note">
          {withheld} passage{withheld === 1 ? ' was' : 's were'} withheld at the{' '}
          <strong>{role}</strong> role. Material exists that a more privileged role could see.
        </p>
      ) : null}

      {refusal.closest_sections.length > 0 ? (
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-caution-fg/70">
            Closest sections — not an answer, just the nearest material
          </h3>
          <ul className="mt-2 space-y-1.5" data-testid="closest-sections">
            {refusal.closest_sections.map((section) => (
              <li key={`${section.policy_id}-${section.section_path}`} className="text-sm">
                <Link
                  to={`/sources/${section.policy_id}`}
                  className="font-medium text-caution-fg underline decoration-caution/40 underline-offset-2 hover:decoration-caution"
                >
                  {section.policy_id} — {section.policy_title}
                </Link>
                <span className="text-caution-fg/60"> · {section.section_path}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-4 border-t border-caution-line pt-3 text-sm text-caution-fg/80">
        {refusal.suggestion_prompt}
      </p>
    </Card>
  )
}
